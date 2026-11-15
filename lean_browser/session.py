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
import json
import os
import re
from urllib.parse import urlparse
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import ElementHandle, Page

from lean_browser.diff import diff
from lean_browser.engine import BrowserManager, Tab
from lean_browser.settle import PageUnresponsive, settle
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

# Overlay that labels every snapshot element visible in the viewport with its id (set-of-marks).
ANNOTATE_JS = r"""() => {
  const old = document.getElementById('__lab_marks'); if (old) old.remove();
  const box = document.createElement('div');
  box.id = '__lab_marks';
  box.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:2147483647';
  const S = window.__lab; if (!S) return 0;
  let n = 0;
  for (const [id, ref] of S.byId) {
    const el = ref.deref();
    if (!el || !el.isConnected || el.ownerDocument !== document) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || r.bottom < 0 || r.right < 0 || r.top > innerHeight || r.left > innerWidth) continue;
    if (el.checkVisibility && !el.checkVisibility({ opacityProperty: true, visibilityProperty: true })) continue;
    const m = document.createElement('div');
    m.style.cssText = `position:fixed;left:${r.left}px;top:${r.top}px;width:${r.width}px;height:${r.height}px;` +
      'outline:2px solid #e8590c;box-sizing:border-box';
    const tag = document.createElement('span');
    tag.textContent = id;
    tag.style.cssText = `position:absolute;left:-2px;top:${r.top < 16 ? 0 : -16}px;background:#e8590c;color:#fff;font:bold 11px/14px monospace;padding:0 3px`;
    m.appendChild(tag); box.appendChild(m); n++;
  }
  document.documentElement.appendChild(box);
  return n;
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
NO_CHANGE_HINT = 'hint: try snapshot(mode="full") or screenshot(id)'

# Buttons/links whose name suggests a hard-to-undo effect. With confirm_risky=True, clicking one needs
# value="confirm"; without it the result still says "looks irreversible" so the agent can double-check.
RISKY = re.compile(r"\b(pay|buy|purchase|place order|checkout|delete|remove|send|transfer|submit payment|"
                   r"confirm (?:order|payment|purchase)|close account|unsubscribe)\b", re.I)

TARGET_STATE_JS = r"""el => {
  const radio = () => { if (el.type !== 'radio') return null;
    const scope = el.form || el.getRootNode();
    const r = [...scope.querySelectorAll(`input[type=radio][name="${CSS.escape(el.name)}"]`)].find(x => x.checked);
    if (!r) return '';
    const l = (r.id && r.getRootNode().querySelector(`label[for="${CSS.escape(r.id)}"]`)) || r.closest('label');
    return ((l && l.textContent) || r.value || '').replace(/\s+/g, ' ').trim(); };
  return { connected: el.isConnected, type: (el.getAttribute('type') || '').toLowerCase(),
    value: typeof el.value === 'string' ? el.value : null,
    checked: typeof el.checked === 'boolean' ? el.checked : null,
    selected: el.tagName === 'SELECT' && el.selectedIndex >= 0 ? el.options[el.selectedIndex].text.trim() : null,
    text: el.isContentEditable ? (el.innerText || '').trim() : (el.getAttribute('role') === 'combobox' ? (el.innerText || '').trim() : null),
    radio: radio(), files: el.files ? el.files.length : null };
}"""

_norm = lambda x: " ".join(str(x or "").split()).lower()


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
                 snapshot_timeout_s: float = 2.0, settle_cap_s: float = 5.0, confirm_risky: bool = False):
        self.bm = bm
        self.confirm_risky = confirm_risky
        self.tabs: list[TabState] = []
        self.active = -1
        self.upload_dirs = [Path(p).expanduser().resolve() for p in (upload_dirs or ["~/Downloads"])]
        self.snapshot_timeout_s = snapshot_timeout_s
        self.settle_cap_s = settle_cap_s
        self._watched_ctx: set[int] = set()
        self._opening = False  # pages we create ourselves are not popups
        self._seen: dict[tuple, set[str]] = {}  # extract(new_only=True) memory, per page path + scope

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
        await self._settle(ts)
        snap = await self._take(ts, mode)
        return self._render_full(ts, snap)

    async def _settle(self, ts: TabState, cap_s: float | None = None) -> bool:
        """settle(), but a page whose script thread has hung (seen on Obscura) moves to Chromium."""
        try:
            return await settle(ts.page, cap_s=cap_s or self.settle_cap_s)
        except PageUnresponsive:
            if ts.tab.engine != "obscura":
                raise ActionError("the page stopped responding to scripts")
            self._opening = True
            try:
                ts.tab = await self.bm.switch_to_chromium(ts.tab, "page unresponsive on obscura")
            finally:
                self._opening = False
            ts.snapper = Snapshotter(timeout_s=max(self.snapshot_timeout_s, 10))
            self._wire(ts)
            return await settle(ts.page, cap_s=cap_s or self.settle_cap_s)

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
            await self._settle(ts)
            return await ts.snapper.take(ts.page, mode=mode, engine=ts.tab.header)

    def _render_full(self, ts: TabState, snap: Snapshot, budget: int | None = None) -> str:
        notes = self._drain(ts)
        return (notes + "\n" if notes else "") + ts.snapper.render(snap, budget=budget, skip_unchanged=False)

    def _drain(self, ts: TabState) -> str:
        n, ts.notes = ts.notes, []
        return "\n".join(n)

    async def snapshot(self, mode: str = "actions", budget: int | None = None, expand: str | None = None,
                       more: str | None = None, find: str | None = None, within: int | None = None) -> str:
        ts = self.cur
        if more:
            return ts.snapper.more(more, budget=budget or 800)
        if within is not None:
            if not ts.snapper.last:
                await self._take(ts)
            try:
                snap = await ts.snapper.take(ts.page, mode=mode, engine=ts.tab.header, within=int(within))
            except ValueError as e:
                raise ActionError(str(e)) from e
            return ts.snapper.render(snap, budget=budget, skip_unchanged=False)
        snap = await self._take(ts, "actions" if (find or expand) else mode)  # modes: minimal|actions|read|full
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
            await self._settle(ts)
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
        note = ""
        if id is not None and action != "scroll":
            id, before, entry, note = await self._resolve_or_recover(ts, int(id), before, entry)
        name = (entry or {}).get("name", "")
        risky = action in ("click", "press") and bool(RISKY.search(name or ""))
        if risky and self.confirm_risky and str(value or "").lower() != "confirm":
            raise ActionError(f'blocked: {(entry or {}).get("role", "element")} "{name}" looks irreversible; '
                              'call act again with value="confirm" to proceed')
        tabs_before = len(self.tabs)
        await self._sync_dialog_policy(ts)
        await self._perform(ts, action, id, value if action != "click" else None, entry)
        expect = {"kind": "action", "action": action, "id": id, "value": value, "entry": entry, "risky": risky}
        return await self._after(ts, before, tabs_before, note, expect)

    async def _resolve_or_recover(self, ts: TabState, el_id: int, before: Snapshot, entry: dict | None):
        """If the id's element is gone (framework re-render), re-resolve it ONCE by role + name on a fresh
        snapshot. Only an unambiguous match is used; nothing has been executed yet at this point."""
        h = await ts.page.evaluate_handle(RESOLVE_JS, el_id)
        if h.as_element():
            return el_id, before, entry, ""
        if not entry:
            raise ActionError(f"id {el_id} not found (page changed?) — call snapshot()")
        fresh = await self._take(ts)
        idx = _index(fresh)
        role, nm = entry["role"], entry.get("name", "")
        old_fp = entry.get("fp") or {}
        same = {e["id"]: e for e in idx.values()
                if e["role"] == role and e.get("name") == nm and e.get("_option") == entry.get("_option")}
        # A candidate may not contradict any fingerprint field the old element had (link target, test id,
        # field name, form, row text, landmark). This stops "the other Delete button" from being clicked.
        keys = [k for k in ("testid", "href", "nm", "form", "ctx", "lm") if old_fp.get(k)]
        cands = {i: e for i, e in same.items() if all((e.get("fp") or {}).get(k) == old_fp[k] for k in keys)}
        matched = ", ".join(["role", "name"] + keys)
        if len(cands) == 1:
            new = next(iter(cands.values()))
            return new["id"], fresh, new, (f'recovered: id {el_id} was re-rendered as {new["id"]} '
                                           f'(same {role} "{nm}"; matched on {matched})\n')
        if len(cands) > 1:
            raise ActionError(f'ambiguous: id {el_id} is gone and {len(cands)} elements match {role} "{nm}" '
                              f"(ids {', '.join(map(str, sorted(cands)))}) — pick one")
        if same:
            raise ActionError(f'id {el_id} is gone: {len(same)} {role} "{nm}" exist(s) but none match the original '
                              f"({', '.join(f'{k}={old_fp[k]!r}' for k in keys)}) — call snapshot()")
        raise ActionError(f'id {el_id} is gone: {role} "{nm}" is no longer on the page — call snapshot()')

    async def _target_state(self, ts: TabState, el_id) -> dict | None:
        try:
            el = (await ts.page.evaluate_handle(RESOLVE_JS, int(el_id))).as_element()
            return await el.evaluate(TARGET_STATE_JS) if el else None
        except Exception:
            return None

    def _check_value(self, action: str, value, entry: dict | None, st: dict | None, after_entry: dict | None) -> tuple[bool, str]:
        """Did the field end up in the requested state? Returns (ok, reason)."""
        role = (entry or {}).get("role")
        if st is None:
            return False, "element disappeared after the action"
        if action in ("fill", "clear"):
            want = "" if action == "clear" else str(value if value is not None else "")
            got = st["value"] if st["value"] is not None else (st["text"] or "")
            if got == want or (st["text"] is not None and _norm(got) == _norm(want)):
                return True, "value set"
            if st["type"] == "password":
                return False, "value differs from what was typed"
            return False, f'value is "{got[:40]}", expected "{want[:40]}"'
        if action == "select":
            got = st["selected"] or st["radio"] or (after_entry or {}).get("val") or st["text"] or ""
            ok = _norm(value) in _norm(got) or _norm(got) in _norm(value) and bool(got)
            return (True, f'"{got}" selected') if ok else (False, f'selected is "{got}", expected "{value}"')
        if action in ("check", "uncheck"):
            want = action == "check"
            return (True, "checked" if want else "unchecked") if st["checked"] == want else (False, f"checked={st['checked']}")
        if action == "upload":
            return (True, "file attached") if st["files"] else (False, "no file attached")
        return True, ""

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

    async def _after(self, ts: TabState, before: Snapshot, tabs_before: int, prefix: str = "",
                     expect: dict | None = None) -> str:
        await asyncio.sleep(0.05)
        settled = await self._settle(ts)
        if len(self.tabs) > tabs_before:
            nts = self.cur
            await self._settle(nts)
            note = self._drain(ts)
            status = "status: verified (new tab opened)\n" if expect else ""
            return status + prefix + (note + "\n" if note else "") + self._render_full(nts, await self._take(nts))
        await self._drain_dialog_shim(ts)
        # Field states are read before the after-snapshot so they describe the same moment.
        states = {}
        if expect and expect["kind"] == "action" and expect["action"] in ("fill", "clear", "select", "check", "uncheck", "upload"):
            states[expect["id"]] = await self._target_state(ts, expect["id"])
        after = await self._take(ts)
        d = diff(before, after)
        if d == "" and expect and expect.get("action") in ("click", "press") and not ts.notes:
            # Nothing changed in this tab. A popup's "page" event can arrive after settle on slow machines,
            # so give a new tab a short grace period before reporting "no visible change". Clicks that did
            # change something never wait.
            for _ in range(15):
                if len(self.tabs) > tabs_before:
                    nts = self.cur
                    await self._settle(nts)
                    note = self._drain(ts)
                    return ("status: verified (new tab opened)\n" + prefix + (note + "\n" if note else "")
                            + self._render_full(nts, await self._take(nts)))
                await asyncio.sleep(0.1)
        notes = self._drain(ts)
        page_changed = d is None
        changed = page_changed or bool(d)
        status = self._status(expect, states, after, page_changed, changed, settled, bool(notes)) if expect else ""
        head = status + prefix + (notes + "\n" if notes else "")
        if page_changed:
            return head + ts.snapper.render(after, skip_unchanged=False)
        ts.snapper.render(after)  # updates the unchanged-hash so the next snapshot() can say "unchanged"
        if not d:
            return (head + NO_CHANGE_HINT) if expect else (head + "no change. " + NO_CHANGE_HINT)
        return head + d

    def _status(self, expect: dict, states: dict, after: Snapshot, page_changed: bool, changed: bool,
                settled: bool, dialog: bool) -> str:
        after_idx = _index(after)
        evidence: list[str] = []
        if page_changed:
            evidence.append(f"page changed: {after.data.get('path')}")
        elif after.data.get("routeChanged"):
            evidence.append(f"route changed: {after.data.get('path')}")
        if expect["kind"] == "form":
            ok_n, n, problems = expect["ok"], expect["n"], expect["problems"]
            parts = [f"{ok_n}/{n} fields set"] + problems
            ok = ok_n == n
            if expect["submitted"]:
                parts.append("submitted" + (f", {evidence[0]}" if evidence else (", page updated" if changed else ", no visible change")))
                ok = ok and changed
            word = "verified" if ok else ("timed_out" if not settled else "unverified")
            return f"status: {word} ({'; '.join(parts)})\n"
        action, el_id = expect["action"], expect["id"]
        if action in ("fill", "clear", "select", "check", "uncheck", "upload"):
            ok, reason = self._check_value(action, expect["value"], expect["entry"], states.get(el_id), after_idx.get(el_id))
            evidence.insert(0, reason)
            err = (after_idx.get(el_id) or {}).get("err")
            if err:
                evidence.append(f'field shows error "{err}"')
        elif action in ("hover", "focus", "scroll"):
            return "status: done\n"
        else:  # click / press: success means something observable happened
            ok = changed or dialog
            if not evidence:
                evidence.append("dialog shown" if dialog and not changed else ("changes below" if changed else "no visible change"))
        if expect.get("risky"):
            evidence.append("looks irreversible")
        word = "verified" if ok else ("timed_out" if not settled else "unverified")
        return f"status: {word} ({'; '.join(e for e in evidence if e)})\n"

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
        problems, ok_n = [], 0
        for raw_id, value in fields.items():
            fid = int(raw_id)
            e = idx.get(fid)
            role = (e or {}).get("role")
            act_ = ("check" if (value is True or str(value).strip().lower() in TRUTHY) else "uncheck") if role in ("checkbox", "switch") \
                else "select" if role in ("select", "radiogroup") or (role == "combobox" and (e or {}).get("custom")) \
                else "upload" if role == "upload" else "fill"
            ok, reason = self._check_value(act_, value, e, await self._target_state(ts, fid), None)
            if ok:
                ok_n += 1
            elif not any(x.startswith(f"{fid}:") for x in errors):
                problems.append(f"{fid}: {reason}")
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
        expect = {"kind": "form", "ok": ok_n, "n": len(fields), "problems": problems,
                  "submitted": bool(submit) and not errors}
        return await self._after(ts, before, tabs_before, prefix, expect)

    async def extract(self, kind: str = "auto", within: int | None = None, fields: list[str] | None = None,
                      new_only: bool = False) -> dict:
        """Deterministic JSON with provenance (source URL, row/item number, element ids).
        new_only=True drops rows/items already returned for this page + scope (pagination, infinite scroll)."""
        ts = self.cur
        if kind not in ("auto", "table", "list", "form"):
            raise ActionError("kind must be auto, table, list or form")
        if within is not None and not ts.snapper.last:
            await self._take(ts)
        res = await ts.page.evaluate(EXTRACT_JS, {"kind": kind, "within": within, "fields": list(fields or [])})
        if isinstance(res, dict) and res.get("error"):
            raise ActionError(res["error"])
        if new_only and res.get("kind") in ("table", "list"):
            key = (urlparse(ts.page.url).path, res["kind"], within, tuple(fields or ()))
            seen = self._seen.setdefault(key, set())
            rows_key = "rows" if res["kind"] == "table" else "items"
            fresh = []
            for r in res[rows_key]:
                h = json.dumps({k: v for k, v in r.items() if not k.startswith("_")}, sort_keys=True)
                if h not in seen:
                    seen.add(h)
                    fresh.append(r)
            res["already_seen"] = len(res[rows_key]) - len(fresh)
            res[rows_key] = fresh
        return res

    async def screenshot(self, id: int | None = None, annotate: bool = False) -> bytes:
        """Viewport PNG, or a crop of one element. annotate=True draws each snapshot id on its element,
        so what the agent sees in the image maps back to ids it can act on."""
        ts = self.cur
        if annotate:
            if not ts.snapper.last:
                await self._take(ts)
            await ts.page.evaluate(ANNOTATE_JS)
        try:
            if id is None:
                return await ts.page.screenshot()
            el = await self._handle(ts, int(id))
            try:
                return await el.screenshot(timeout=10000)
            except Exception as e:
                raise ActionError(_short(e)) from e
        finally:
            if annotate:
                await ts.page.evaluate("() => { const o = document.getElementById('__lab_marks'); if (o) o.remove(); }")

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
