"""Session layer: tabs, actions by snapshot ID, settle, diffs, dialogs, uploads.

    async with BrowserManager(init_scripts=[SETTLE_INIT_JS]) as bm:
        s = Session(bm)
        print(await s.open("https://example.com"))
        print(await s.act("fill", 3, "asha@example.com"))
        print(await s.fill_form({1: "Asha", 2: "asha@x.com"}, submit=True))

On Chromium, actions use Playwright (trusted input events). On Obscura they run as injected JS
on the element itself, because Playwright locators time out inside shadow DOM and iframes there
(spike-verified). Both paths resolve the element from the snapshot's ID map, so shadow-DOM and
same-origin-iframe elements work the same way.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import ElementHandle, Page

from lean_browser.diff import diff
from lean_browser.engine import BrowserManager, Tab
from lean_browser.settle import settle
from lean_browser.snapshot import Snapshot, Snapshotter, SnapshotTimeout

EXTRACT_JS = (Path(__file__).parent / "extract.js").read_text()

RESOLVE_JS = """id => { const r = window.__lab && window.__lab.byId.get(id); const el = r && r.deref();
  return el && el.isConnected ? el : null; }"""

# JS actions for Obscura. Mirrors what a user does: pointer/mouse sequence then click; values set
# through the native setter (so React-style controlled inputs see them) plus input/change events.
DOM_ACT_JS = r"""(el, [action, value]) => {
  const win = el.ownerDocument.defaultView || window;
  const fire = (type, Ctor, extra) => el.dispatchEvent(new (Ctor || win.Event)(type, Object.assign({ bubbles: true, cancelable: true, composed: true }, extra || {})));
  const M = win.MouseEvent || win.Event, P = win.PointerEvent || M;
  const clickSeq = (t) => { t = t || el; if (t.scrollIntoView) t.scrollIntoView({ block: 'center' });
    const f = (type, C) => t.dispatchEvent(new C(type, { bubbles: true, cancelable: true, composed: true }));
    f('pointerdown', P); f('mousedown', M); if (t.focus) t.focus(); f('pointerup', P); f('mouseup', M); t.click(); };
  const setVal = v => {
    const proto = el.tagName === 'TEXTAREA' ? win.HTMLTextAreaElement.prototype : el.tagName === 'SELECT' ? win.HTMLSelectElement.prototype : win.HTMLInputElement.prototype;
    const d = Object.getOwnPropertyDescriptor(proto, 'value');
    if (el.focus) el.focus();
    if (d && d.set) d.set.call(el, v); else el.value = v;
    fire('input', win.InputEvent); fire('change');
  };
  const labelOf = r => { const l = (r.id && r.getRootNode().querySelector(`label[for="${CSS.escape(r.id)}"]`)) || r.closest('label');
    return ((l && l.textContent) || r.getAttribute('aria-label') || r.value || '').replace(/\s+/g, ' ').trim(); };
  const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  switch (action) {
    case 'click': clickSeq(); return 'ok';
    case 'hover': fire('pointerover', P); fire('mouseover', M); fire('mouseenter', M, { bubbles: false }); return 'ok';
    case 'focus': if (el.focus) el.focus(); return 'ok';
    case 'fill': setVal(String(value)); return 'ok';
    case 'clear': setVal(''); return 'ok';
    case 'check': if (!el.checked) clickSeq(); return el.checked ? 'ok' : 'error: did not become checked';
    case 'uncheck': if (el.checked) clickSeq(); return !el.checked ? 'ok' : 'error: still checked';
    case 'select': {
      if (el.tagName === 'SELECT') {
        const o = [...el.options].find(o => norm(o.text) === norm(value)) || [...el.options].find(o => o.value === String(value))
          || [...el.options].find(o => norm(o.text).includes(norm(value)));
        if (!o) return 'error: no option ' + JSON.stringify(value) + '; options: ' + [...el.options].map(o => o.text.trim()).join(' | ');
        setVal(o.value); return 'ok';
      }
      if (el.type === 'radio') {
        const scope = el.form || el.getRootNode();
        const rs = [...scope.querySelectorAll(`input[type=radio][name="${CSS.escape(el.name)}"]`)];
        const r = rs.find(r => norm(labelOf(r)) === norm(value)) || rs.find(r => norm(labelOf(r)).includes(norm(value))) || rs.find(r => r.value === String(value));
        if (!r) return 'error: no option ' + JSON.stringify(value) + '; options: ' + rs.map(labelOf).join(' | ');
        clickSeq(r); return 'ok';
      }
      return 'error: not a select or radio group';
    }
  }
  return 'error: unknown action ' + action;
}"""

FIND_OPTION_JS = """(value) => {
  const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
  const opts = [...document.querySelectorAll('[role=option],[role=menuitem],[role=listbox] li')];
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 || r.height > 0; };
  return opts.find(o => vis(o) && norm(o.textContent) === norm(value)) || opts.find(o => vis(o) && norm(o.textContent).includes(norm(value))) || null;
}"""

SUBMIT_BUTTON_JS = """el => { const f = el.form || el.closest('form'); if (!f) return null;
  return f.querySelector('button[type=submit],input[type=submit],button:not([type])'); }"""

# Obscura never emits CDP dialog events: alert/confirm/prompt silently return as if accepted.
# This shim (Obscura contexts only) records each dialog and applies the agent's policy.
OBSCURA_DIALOG_SHIM = r"""
(() => {
  if (window.__labDialog) return;
  const st = window.__labDialog = { policy: 'accept', log: [] };
  const take = () => { const p = st.policy; st.policy = 'accept'; return p; };
  window.alert = m => { st.log.push(['alert', String(m), take()]); };
  window.confirm = m => { const p = take(); st.log.push(['confirm', String(m), p]); return p === 'accept'; };
  window.prompt = (m, d) => { const p = take(); st.log.push(['prompt', String(m), p]); return p === 'accept' ? (d || '') : null; };
})();
"""

TRUTHY = {"true", "on", "yes", "1", "checked", "y"}
NEEDS_ID = {"click", "hover", "check", "uncheck", "clear", "focus", "fill", "select", "upload"}
NO_CHANGE_HINT = 'no change. hint: try snapshot(mode="full") or screenshot(id)'


class ActionError(Exception):
    """Short, actionable error for the agent."""


@dataclass
class TabState:
    tab: Tab
    snapper: Snapshotter
    notes: list[str] = field(default_factory=list)
    dialog_policy: str = "accept"

    @property
    def page(self) -> Page:
        return self.tab.page


def _index(snap: Snapshot | None) -> dict[int, dict]:
    idx: dict[int, dict] = {}
    if not snap:
        return idx

    def walk(entries):
        for e in entries:
            if e["t"] == "el":
                idx[e["id"]] = e
                for o in e.get("options", []) if isinstance(e.get("options"), list) and e["role"] == "radiogroup" else []:
                    idx[o["id"]] = {**e, "id": o["id"], "_option": o["label"]}
            elif e["t"] == "group":
                walk(e["items"])
            elif e["t"] == "item":
                walk(e.get("refs", []))
    walk(snap.data.get("entries", []))
    for b in (snap.data.get("banner") or {}).get("buttons", []):
        idx[b["id"]] = {"t": "el", "id": b["id"], "role": "button", "name": b["name"]}
    return idx


def _short(e: Exception) -> str:
    msg = str(e).splitlines()[0] if str(e) else type(e).__name__
    if "intercepts pointer events" in str(e):
        return "another element covers it (a dialog, banner or overlay?) — deal with that first"
    if "Timeout" in type(e).__name__ or "Timeout" in msg:
        return "timed out waiting for the element to be clickable/visible"
    return msg[:200]


class Session:
    def __init__(self, bm: BrowserManager, *, upload_dirs: list[str | Path] | None = None,
                 snapshot_timeout_s: float = 2.0, settle_cap_s: float = 5.0):
        self.bm = bm
        self.tabs: list[TabState] = []
        self.active = -1
        self.upload_dirs = [Path(p).expanduser().resolve() for p in (upload_dirs or ["~/Downloads"])]
        self.snapshot_timeout_s = snapshot_timeout_s
        self.settle_cap_s = settle_cap_s
        self._watched_ctx: set[int] = set()
        self._opening = False  # pages we create ourselves are not popups

    # ---------- tabs ----------
    @property
    def cur(self) -> TabState:
        if self.active < 0:
            raise ActionError("no page open — call open(url) first")
        return self.tabs[self.active]

    def _wire(self, ts: TabState):
        page = ts.page

        async def on_dialog(d):
            policy, ts.dialog_policy = ts.dialog_policy, "accept"
            ts.notes.append(f"dialog {d.type} {d.message!r} {'accepted' if policy == 'accept' else 'dismissed'}")
            try:
                await (d.accept() if policy == "accept" else d.dismiss())
            except Exception:
                pass
        page.on("dialog", on_dialog)
        ctx = page.context
        if id(ctx) not in self._watched_ctx:
            self._watched_ctx.add(id(ctx))

            def on_page(p: Page):
                if self._opening:
                    return
                engine = "chromium" if ctx is self.bm._chromium_ctx else "obscura"
                nts = TabState(Tab(p, engine, "popup"), Snapshotter(timeout_s=self.snapshot_timeout_s))
                self.tabs.append(nts)
                self._wire(nts)
                prev = self.cur if self.active >= 0 else None
                self.active = len(self.tabs) - 1
                if prev:
                    prev.notes.append(f"+tab {self.active + 1} opened and is now active")
            ctx.on("page", on_page)

    async def open(self, url: str, mode: str = "actions", new_tab: bool = False) -> str:
        self._opening = True
        try:
            if new_tab or self.active < 0:
                tab = await self.bm.open(url)
                ts = TabState(tab, Snapshotter(timeout_s=self.snapshot_timeout_s))
                self.tabs.append(ts)
                self.active = len(self.tabs) - 1
                self._wire(ts)
            else:
                ts = self.cur
                old_page = ts.page
                ts.tab = await self.bm.navigate(ts.tab, url)
                if ts.page is not old_page:
                    ts.snapper = Snapshotter(timeout_s=self.snapshot_timeout_s)
                    self._wire(ts)
        finally:
            self._opening = False
        await settle(ts.page, cap_s=self.settle_cap_s)
        snap = await self._take(ts, mode)
        return self._render_full(ts, snap)

    # ---------- snapshots ----------
    async def _take(self, ts: TabState, mode: str = "actions") -> Snapshot:
        try:
            return await ts.snapper.take(ts.page, mode=mode, engine=ts.tab.header)
        except SnapshotTimeout:
            if ts.tab.engine != "obscura":
                raise
            self._opening = True
            try:
                ts.tab = await self.bm.switch_to_chromium(ts.tab, "snapshot too slow")
            finally:
                self._opening = False
            ts.snapper = Snapshotter(timeout_s=max(self.snapshot_timeout_s, 10))
            self._wire(ts)
            await settle(ts.page, cap_s=self.settle_cap_s)
            return await ts.snapper.take(ts.page, mode=mode, engine=ts.tab.header)

    def _render_full(self, ts: TabState, snap: Snapshot, budget: int | None = None) -> str:
        notes = self._drain(ts)
        return (notes + "\n" if notes else "") + ts.snapper.render(snap, budget=budget, skip_unchanged=False)

    def _drain(self, ts: TabState) -> str:
        n, ts.notes = ts.notes, []
        return "\n".join(n)

    async def snapshot(self, mode: str = "actions", budget: int | None = None, expand: str | None = None,
                       more: str | None = None, find: str | None = None) -> str:
        ts = self.cur
        if more:
            return ts.snapper.more(more, budget=budget or 800)
        snap = await self._take(ts, "actions" if (find or expand) else mode)
        if find:
            return ts.snapper.find(find)
        if expand:
            return ts.snapper.render(snap, budget=budget or 2000, expand=expand)
        notes = self._drain(ts)
        return (notes + "\n" if notes else "") + ts.snapper.render(snap, budget=budget)

    # ---------- element resolution ----------
    async def _handle(self, ts: TabState, el_id: int) -> ElementHandle:
        h = await ts.page.evaluate_handle(RESOLVE_JS, int(el_id))
        el = h.as_element()
        if not el:
            raise ActionError(f"id {el_id} not found (page changed?) — call snapshot()")
        if ts.tab.engine == "chromium" and not await el.evaluate("e => e.ownerDocument === document"):
            # Element lives in a same-origin iframe: Playwright needs a handle from that frame's own
            # context to compute click coordinates, so re-resolve it inside the frame.
            frame_el = (await el.evaluate_handle("e => e.ownerDocument.defaultView.frameElement")).as_element()
            frame = frame_el and await frame_el.content_frame()
            inner = frame and await frame.query_selector(f'[data-lab-id="{int(el_id)}"]')
            if inner:
                return inner
        return el

    async def _click(self, ts: TabState, el: ElementHandle):
        if ts.tab.engine == "chromium":
            try:
                await el.click(timeout=5000)
            except Exception as e:
                raise ActionError(_short(e)) from e
        else:
            await self._dom(el, "click")

    async def _dom(self, el: ElementHandle, action: str, value=None):
        r = await el.evaluate(DOM_ACT_JS, [action, value])
        if isinstance(r, str) and r.startswith("error"):
            raise ActionError(r[len("error: "):])

    def _check_upload(self, path: str) -> str:
        p = Path(path).expanduser()
        if not p.is_absolute():
            raise ActionError("upload path must be absolute")
        real = p.resolve()
        if not any(real == d or d in real.parents for d in self.upload_dirs):
            raise ActionError(f"upload path is outside the allowed folders ({', '.join(map(str, self.upload_dirs))})")
        if not real.is_file():
            raise ActionError(f"no such file: {path}")
        return str(real)

    # ---------- actions ----------
    async def _perform(self, ts: TabState, action: str, el_id, value, entry: dict | None):
        page, eng = ts.page, ts.tab.engine
        if action in NEEDS_ID and el_id is None:
            raise ActionError(f"{action} needs an id")
        el = await self._handle(ts, el_id) if el_id is not None and action not in ("scroll",) else None
        role = (entry or {}).get("role")
        if action == "click":
            await self._click(ts, el)
        elif action in ("fill", "clear"):
            v = "" if action == "clear" else str(value if value is not None else "")
            if eng == "chromium":
                try:
                    await el.fill(v, timeout=5000)
                except Exception as e:
                    raise ActionError(_short(e)) from e
            else:
                await self._dom(el, "fill", v)
        elif action in ("check", "uncheck"):
            if eng == "chromium":
                try:
                    await (el.check if action == "check" else el.uncheck)(timeout=5000)
                except Exception as e:
                    raise ActionError(_short(e)) from e
            else:
                await self._dom(el, action)
        elif action == "select":
            if value is None:
                raise ActionError("select needs a value (the option label)")
            tag = await el.evaluate("e => e.tagName + ':' + (e.type || '')")
            if tag.startswith("SELECT") or tag.endswith(":radio"):
                if eng == "chromium" and tag.startswith("SELECT"):
                    try:
                        await el.select_option(label=str(value), timeout=5000)
                    except Exception:
                        await self._dom(el, "select", value)  # value or partial-label match
                elif eng == "chromium":
                    r = await el.evaluate_handle("""(el, v) => { const n = s => (s||'').replace(/\\s+/g,' ').trim().toLowerCase();
                        const scope = el.form || el.getRootNode();
                        const rs = [...scope.querySelectorAll(`input[type=radio][name="${CSS.escape(el.name)}"]`)];
                        const lab = r => { const l = (r.id && r.getRootNode().querySelector(`label[for="${CSS.escape(r.id)}"]`)) || r.closest('label'); return (l && l.textContent) || r.value; };
                        return rs.find(r => n(lab(r)) === n(v)) || rs.find(r => n(lab(r)).includes(n(v))) || null; }""", str(value))
                    radio = r.as_element()
                    if not radio:
                        raise ActionError(f"no option {value!r}")
                    try:
                        await radio.check(timeout=5000)
                    except Exception as e:
                        raise ActionError(_short(e)) from e
                else:
                    await self._dom(el, "select", value)
            else:
                # custom combobox / listbox: open it, then click the matching option
                await self._click(ts, el)
                await settle(page, quiet_ms=150, cap_s=2)
                opt = (await page.evaluate_handle(FIND_OPTION_JS, str(value))).as_element()
                if not opt:
                    raise ActionError(f"opened {role or 'element'} {el_id} but found no visible option {value!r} — call snapshot()")
                await self._click(ts, opt)
        elif action == "hover":
            if eng == "chromium":
                await el.hover(timeout=5000)
            else:
                await self._dom(el, "hover")
        elif action == "focus":
            await (el.focus() if eng == "chromium" else self._dom(el, "focus"))
        elif action == "press":
            if not value:
                raise ActionError("press needs a key, e.g. Enter")
            if el is not None:
                await (el.focus() if eng == "chromium" else self._dom(el, "focus"))
            await page.keyboard.press(str(value))
        elif action == "upload":
            path = self._check_upload(str(value or ""))
            if eng != "chromium":
                self._opening = True
                try:
                    ts.tab = await self.bm.switch_to_chromium(ts.tab, "file upload")
                finally:
                    self._opening = False
                self._wire(ts)
                raise ActionError("this page moved to Chromium for the upload; call snapshot() and retry with the new id")
            try:
                await el.set_input_files(path, timeout=5000)
            except Exception as e:
                raise ActionError(_short(e)) from e
        elif action == "scroll":
            if el_id is not None:
                el = await self._handle(ts, el_id)
                await el.evaluate("e => e.scrollIntoView({block: 'center'})")
            else:
                v = str(value or "down")
                js = {"down": "window.scrollBy(0, window.innerHeight * 0.8)", "up": "window.scrollBy(0, -window.innerHeight * 0.8)",
                      "bottom": "window.scrollTo(0, document.body.scrollHeight)", "top": "window.scrollTo(0, 0)"}.get(v)
                if not js:
                    raise ActionError("scroll value must be down, up, bottom or top")
                await page.evaluate(js)
                await page.evaluate("window.dispatchEvent(new Event('scroll'))")
        else:
            raise ActionError(f"unknown action {action!r}")

    async def act(self, action: str, id: int | None = None, value=None) -> str:
        action = action.lower().strip()
        if action in ("back", "forward", "reload"):
            ts = self.cur
            fn = {"back": ts.page.go_back, "forward": ts.page.go_forward, "reload": ts.page.reload}[action]
            try:
                await fn(timeout=self.bm.nav_timeout_ms)
            except Exception as e:
                raise ActionError(_short(e)) from e
            await settle(ts.page, cap_s=self.settle_cap_s)
            return self._render_full(ts, await self._take(ts))
        if action == "wait_for":
            return await self._wait_for(str(value or ""))
        if action == "tab":
            return await self._tab(str(value or "list"))
        if action == "dialog":
            v = str(value or "").lower()
            if v not in ("accept", "dismiss"):
                raise ActionError("dialog value must be accept or dismiss")
            self.cur.dialog_policy = v
            return f"the next browser dialog will be {v}ed"

        ts = self.cur
        before = ts.snapper.last or await self._take(ts)
        entry = _index(before).get(int(id)) if id is not None else None
        tabs_before = len(self.tabs)
        await self._sync_dialog_policy(ts)
        await self._perform(ts, action, id, value, entry)
        return await self._after(ts, before, tabs_before)

    async def _sync_dialog_policy(self, ts: TabState):
        if ts.tab.engine == "obscura":
            try:
                await ts.page.evaluate("p => { if (window.__labDialog) window.__labDialog.policy = p; }", ts.dialog_policy)
            except Exception:
                pass

    async def _drain_dialog_shim(self, ts: TabState):
        if ts.tab.engine != "obscura":
            return
        try:
            log = await ts.page.evaluate("() => { const s = window.__labDialog; if (!s) return []; const l = s.log; s.log = []; return l; }")
        except Exception:
            return
        for kind, msg, policy in log:
            ts.notes.append(f"dialog {kind} {msg!r} {'accepted' if policy == 'accept' else 'dismissed'}")
        if log:
            ts.dialog_policy = "accept"

    async def _after(self, ts: TabState, before: Snapshot, tabs_before: int, prefix: str = "") -> str:
        await asyncio.sleep(0.05)
        settled = await settle(ts.page, cap_s=self.settle_cap_s)
        loading = "" if settled else "(still loading)\n"
        if len(self.tabs) > tabs_before:
            nts = self.cur
            await settle(nts.page, cap_s=self.settle_cap_s)
            note = self._drain(ts)
            return prefix + loading + (note + "\n" if note else "") + self._render_full(nts, await self._take(nts))
        await self._drain_dialog_shim(ts)
        after = await self._take(ts)
        d = diff(before, after)
        notes = self._drain(ts)
        head = prefix + loading + (notes + "\n" if notes else "")
        if d is None:
            return head + ts.snapper.render(after, skip_unchanged=False)
        ts.snapper.render(after)  # updates the unchanged-hash so the next snapshot() can say "unchanged"
        return head + (d if d else NO_CHANGE_HINT)

    async def fill_form(self, fields: dict, submit=False) -> str:
        ts = self.cur
        before = ts.snapper.last or await self._take(ts)
        idx = _index(before)
        tabs_before = len(self.tabs)
        await self._sync_dialog_policy(ts)
        errors = []
        for raw_id, value in fields.items():
            fid = int(raw_id)
            e = idx.get(fid)
            role = (e or {}).get("role")
            try:
                if role in ("checkbox", "switch"):
                    on = value is True or str(value).strip().lower() in TRUTHY
                    await self._perform(ts, "check" if on else "uncheck", fid, None, e)
                elif role in ("select", "radiogroup") or (role == "combobox" and e.get("custom")):
                    await self._perform(ts, "select", fid, value, e)
                elif role == "upload":
                    await self._perform(ts, "upload", fid, value, e)
                else:
                    await self._perform(ts, "fill", fid, value, e)
            except ActionError as err:
                errors.append(f"{fid}: {err}")
        if submit and not errors:
            if submit is True:
                first = await self._handle(ts, int(next(iter(fields))))
                btn = (await first.evaluate_handle(SUBMIT_BUTTON_JS)).as_element()
                if not btn:
                    errors.append("submit: no submit button found in the form — pass submit=<button id>")
                else:
                    await self._click(ts, btn)
            else:
                try:
                    await self._click(ts, await self._handle(ts, int(submit)))
                except ActionError as err:
                    errors.append(f"submit: {err}")
        prefix = ("errors:\n" + "\n".join(errors) + "\n") if errors else ""
        return await self._after(ts, before, tabs_before, prefix)

    async def extract(self, kind: str = "auto", within: int | None = None) -> dict:
        ts = self.cur
        if kind not in ("auto", "table", "list", "form"):
            raise ActionError("kind must be auto, table, list or form")
        if within is not None and not ts.snapper.last:
            await self._take(ts)
        res = await ts.page.evaluate(EXTRACT_JS, {"kind": kind, "within": within})
        if isinstance(res, dict) and res.get("error"):
            raise ActionError(res["error"])
        return res

    async def screenshot(self, id: int | None = None) -> bytes:
        """Viewport PNG, or a crop of one element. For captchas, charts and layout questions only."""
        ts = self.cur
        if id is None:
            return await ts.page.screenshot()
        el = await self._handle(ts, int(id))
        try:
            return await el.screenshot(timeout=10000)
        except Exception as e:
            raise ActionError(_short(e)) from e

    async def _wait_for(self, text: str, timeout_s: float = 10) -> str:
        ts = self.cur
        if not text:
            raise ActionError("wait_for needs the text to wait for")
        before = ts.snapper.last or await self._take(ts)
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            try:
                if await ts.page.evaluate("t => (document.body && document.body.innerText || '').includes(t)", text):
                    out = await self._after(ts, before, len(self.tabs))
                    return f"found {text!r}" + ("" if out.startswith("no change") else "\n" + out)
            except Exception:
                pass
            await asyncio.sleep(0.25)
        raise ActionError(f"{text!r} did not appear within {timeout_s:.0f}s")

    async def _tab(self, v: str) -> str:
        if v == "list":
            out = []
            for i, t in enumerate(self.tabs):
                try:
                    title = await t.page.title()
                except Exception:
                    title = "?"
                out.append(f"{i + 1}: {title} | {t.page.url}{'  (active)' if i == self.active else ''}")
            return "\n".join(out) or "no tabs"
        kind, _, arg = v.partition(":")
        if kind == "new":
            return await self.open(arg, new_tab=True)
        n = int(arg) - 1 if arg.isdigit() else -1
        if not (0 <= n < len(self.tabs)):
            raise ActionError(f"no tab {arg!r}; call act('tab', value='list')")
        if kind == "switch":
            self.active = n
            ts = self.cur
            return self._render_full(ts, await self._take(ts))
        if kind == "close":
            t = self.tabs.pop(n)
            await t.page.close()
            if not self.tabs:
                self.active = -1
                return "closed the last tab"
            self.active = min(self.active if self.active < n else self.active - 1, len(self.tabs) - 1)
            return f"closed tab {n + 1}; active tab is {self.active + 1}"
        raise ActionError("tab value must be list, new:<url>, switch:<n> or close:<n>")
