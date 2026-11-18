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
import time
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
    case 'check': { const on = () => el.tagName === 'INPUT' ? !!el.checked : el.getAttribute('aria-checked') === 'true';
      if (!on()) clickSeq(); return on() ? 'ok' : 'error: did not become checked'; }
    case 'uncheck': { const on = () => el.tagName === 'INPUT' ? !!el.checked : el.getAttribute('aria-checked') === 'true';
      if (on()) clickSeq(); return !on() ? 'ok' : 'error: still checked'; }
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
  const ok = p => p.startsWith('accept');
  window.alert = m => { st.log.push(['alert', String(m), take()]); };
  window.confirm = m => { const p = take(); st.log.push(['confirm', String(m), p]); return ok(p); };
  window.prompt = (m, d) => { const p = take(); st.log.push(['prompt', String(m), p]);
    return ok(p) ? (p.startsWith('accept:') ? p.slice(7) : (d || '')) : null; };
})();
"""

def _dialog_word(policy: str) -> str:
    if policy.startswith("accept:"):
        return f"accepted with {policy[7:]!r}"
    return "accepted" if policy == "accept" else "dismissed"


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
    checked: el.tagName === 'INPUT' && typeof el.checked === 'boolean' ? el.checked
      : (el.hasAttribute('aria-checked') ? el.getAttribute('aria-checked') === 'true' : null),
    selected: el.tagName === 'SELECT' && el.selectedIndex >= 0 ? el.options[el.selectedIndex].text.trim() : null,
    text: el.isContentEditable ? (el.innerText || '').trim() : (el.getAttribute('role') === 'combobox' ? (el.innerText || '').trim() : null),
    radio: radio(), files: el.files ? el.files.length : null,
    slider: el.getAttribute('role') === 'slider' ? el.getAttribute('aria-valuenow') : (el.type === 'range' ? el.value : null) };
}"""

# The browser's own form validation (required, type=email, pattern, minlength), checked before a submit is
# dispatched. Chromium would refuse the submit silently; Obscura doesn't validate at all and would send it.
# Native checkValidity() when the engine has it, plus the same rules by hand for engines that don't.
FORM_INVALID_JS = r"""(el, enter) => {
  let form = null;
  const b = el.closest && el.closest('button, input[type=submit], input[type=image]');
  if (b && !enter) {
    if ((b.type || '').toLowerCase() !== 'submit' && (b.type || '').toLowerCase() !== 'image') return null;
    if (b.formNoValidate || b.hasAttribute('formnovalidate')) return null;
    form = b.form || b.closest('form');
  } else if (enter && el.form && /^(input)$/i.test(el.tagName)) form = el.form;
  if (!form || form.noValidate || form.hasAttribute('novalidate')) return null;
  const label = x => ((x.labels && x.labels[0] && x.labels[0].innerText) || x.getAttribute('aria-label') || x.name || x.type || 'field').trim();
  const bad = [];
  for (const x of Array.from(form.elements || [])) {
    if (x.disabled || x.type === 'hidden' || x.type === 'submit' || x.type === 'button') continue;
    let msg = '';
    if (typeof x.checkValidity === 'function' && x.validity && !x.checkValidity()) msg = x.validationMessage || 'invalid';
    const v = (x.value || '');
    if (!msg && x.hasAttribute('required')) {
      if (x.type === 'checkbox' && !x.checked) msg = 'must be checked';
      else if (x.type === 'radio' && !form.querySelector(`input[type=radio][name="${CSS.escape(x.name)}"]:checked`)) msg = 'choose an option';
      else if (x.type !== 'checkbox' && x.type !== 'radio' && !v.trim()) msg = 'is required';
    }
    if (!msg && v && x.type === 'email' && !/^[^@\s]+@[^@\s]+$/.test(v)) msg = 'is not a valid email address';
    if (!msg && v && x.minLength > 0 && v.length < x.minLength) msg = `needs at least ${x.minLength} characters`;
    if (!msg && v && x.getAttribute('pattern')) { try { if (!new RegExp('^(?:' + x.getAttribute('pattern') + ')$').test(v)) msg = 'does not match the required format'; } catch (e) {} }
    if (msg && !bad.some(s => s.startsWith(label(x) + ':'))) bad.push(label(x) + ': ' + msg);
  }
  return bad.length ? bad : null;
}"""

# Occurrences of expected text on the page, not counting negated ones ("not saved", "unsuccessful").
# Also the other ten languages NEGATED_SUCCESS_RE knows, with the negation before the text ("nicht gespeichert",
# "no se ha guardado", "n'a pas été enregistré", "не сохранено", "未保存") or after it ("保存されていません",
# "저장되지 않", "सहेजा नहीं"). JS \b and \w are ASCII-only, so Latin and Cyrillic letters are spelled out.
EXPECT_COUNT_JS = r"""t => { const n = s => (s || '').replace(/\s+/g, ' ').toLowerCase();
  const body = n(document.body && (document.body.innerText || document.body.textContent)), w = n(t).trim();
  if (!w) return 0;
  const preIntl = /(?:^|[^a-zÀ-ɏЀ-ӿ])(?:nicht|kein(?:e[nmrs]?)?|nie|niemals|pas|non|jamais|aucune?|nessun[oa]?|no|nunca|ning[uú]n[oa]?|não|nao|не|ни|нет)\s+(?:[a-zÀ-ɏЀ-ӿ'’]+\s+){0,3}$|(?:未|[没沒]有?|不)\s?$|(?:^|[^ऀ-ॿ])(?:नहीं|न)\s+$/;
  const postIntl = /^(?:(?:されて|して|でき|され|し)?い?ません|に失敗|(?:でき|され|し)なかった)|^\s?(?:(?:되지|하지)\s?(?:않|못)|(?:하지\s)?못|실패)|^\s+(?:[ऀ-ॿ]+\s+){0,2}?(?:नहीं|न)(?![ऀ-ॿ])/;
  let c = 0, i = 0;
  while ((i = body.indexOf(w, i)) !== -1) {
    const pre = body.slice(Math.max(0, i - 30), i), pre40 = body.slice(Math.max(0, i - 40), i);
    const post = body.slice(i + w.length, i + w.length + 30);
    if (!/(\bnot|\bnever|n[’']t|\bno longer|\bun|\bfailed to|\bcould not be)\s*(\w+\s+){0,2}$/.test(pre)
        && !preIntl.test(pre40) && !postIntl.test(post)) c++;
    i += w.length;
  }
  return c; }"""

_norm = lambda x: " ".join(str(x or "").split()).lower()

# Outcome signals. English plus common words in German, French, Italian, Spanish, Portuguese, Russian, Chinese,
# Japanese, Korean and Hindi; a site that shows none of them stays "unverified": pass expect= then.
# \b only works for Latin and Cyrillic here. CJK has no word boundaries, so those words stand outside \b, and
# Devanagari vowel signs aren't \w in Python, so Hindi words get their own lookarounds.
_DEVA = r"[\u0900-\u097F]"
_HI = lambda words: r"(?<!" + _DEVA + r")(" + words + r")(?!" + _DEVA + r")"
# Non-English success words that also appear in the negation check below.
_SUCCESS_WORDS_INTL = (
    r"gespeichert|erfolgreich|gesendet|versendet|abgeschickt|bestätigt|erstellt|aktualisiert|abgeschlossen|"
    r"enregistrée?s?|réussie?s?|envoyée?s?|confirmée?s?|créée?s?|terminée?s?|"
    r"salvat[oaie]|completat[oaie]|inviat[oaie]|confermat[oaie]|creat[oai]|riuscit[oaie]|"
    r"guardad[oa]s?|exitos[oa]s?|exitosamente|enviad[oa]s?|confirmad[oa]s?|cread[oa]s?|completad[oa]s?|"
    r"salv[oa]s?(?!\s+(que|el|la|los|las|en)\b)|conclu[íi]d[oa]s?|criad[oa]s?|"
    r"сохранен[оаы]?|сохранён|успешно|отправлен[оаы]?|создан[оаы]?|подтвержден[оаы]?|выполнен[оаы]?")
SUCCESS_RE = re.compile(
    r"\b(thank(s| you)|success(ful(ly)?)?|saved|created|received|submitted|placed|confirmed|sent|"
    r"updated|added|welcome|complete(d)?|booked|registered|published|posted|"
    r"danke|vielen dank|merci(?!\s+(de|d['’])\b)|succès|grazie|successo|gracias|éxito|obrigad[oa]s?|sucesso|"
    r"спасибо|готово|" + _SUCCESS_WORDS_INTL + r")\b|"
    r"成功|已保存|已提交|已发送|已完成|谢谢|感谢|保存しました|保存されました|送信しました|登録しました|完了|ありがとう|"
    r"저장(되었|됐|했|됨|완료)|완료|감사합니다|성공|" + _HI(r"सफल|सफलतापूर्वक|सहेजा|सहेजी|सहेजे|धन्यवाद|भेजा गया"),
    re.I)
ERROR_RE = re.compile(r"\b(errors?|invalid|incorrect|failed|failure|wrong|already (taken|exists|registered|in use)|"
                      r"is taken|denied|not allowed|forbidden|unable|could ?n[o\'’]t|try again|declined|rejected|"
                      r"must (be|have|include|match|accept)|(is|are) required|do(es)? not match|"
                      # a few common error words in other languages
                      r"fehler|fehlgeschlagen|erreur|échec|errore|fallito|fall[oó]|erro|falhou|ошибка|не удалось)\b|"
                      r"错误|失败|エラー|失敗|오류|실패|" + _HI(r"त्रुटि|विफल|असफल"), re.I)
_SUCCESS_WORDS = (r"(sent|saved|submitted|placed|confirmed|created|received|updated|added|completed?|booked|"
                  r"registered|published|posted|processed|accepted|approved|delivered|successful(ly)?|"
                  + _SUCCESS_WORDS_INTL + r")")
_NEGATORS = (r"not|never|no longer|nicht|kein(e[nmrs]?)?|nie|pas|non|jamais|aucune?|nessun[oa]?|no(?!\s+\d)|nunca|"
             r"ning[uú]n[oa]?|não|nao|не|ни|нет")
# "was not saved", "wasn't sent", "could not be completed", "never received", "unsuccessful", "nicht gespeichert",
# "non enregistré", "no guardado", "не сохранено", "未保存", "保存されていません", "저장되지 않", "सहेजा नहीं":
# failures that contain a success word. They count as errors and never as success.
NEGATED_SUCCESS_RE = re.compile(
    r"(\b(" + _NEGATORS + r")\b|n[\'’]t\b)(\s+\w+){0,3}?\s+" + _SUCCESS_WORDS + r"\b|"
    r"\b(unsuccessful|erfolglos|nicht erfolgreich|(sans|senza|sin|sem) (succès|successo|éxito|sucesso)|"
    r"неудачно|безуспешно|неуспешно)\b|"
    r"[未没沒]有?(保存|提交|发送|發送|完成|成功)|不成功|"
    r"(保存|送信|登録|完了)(されて|して)?(いません|できません|されません|しません)|できませんでした|"
    r"(저장|완료|전송|등록|제출)(되지|하지)\s?(않|못)|(저장|완료|전송|등록|제출)(하지 )?못|"
    + _HI(r"सहेजा|सहेजी|सहेजे|सफल|भेजा|भेजी|पूरा") + r"(\s+" + _DEVA + r"+){0,2}?\s+" + _HI(r"नहीं|न"),
    re.I)
# Text that says the result isn't known yet. While it is on screen, a vanished button proves nothing.
PENDING_RE = re.compile(r"\b(processing|please wait|loading|submitting|sending|saving|in progress|verifying|"
                        r"authori[sz]ing|redirecting|hold on|one moment)\b|…\s*$|\.\.\.\s*$", re.I)
TIMEISH_RE = re.compile(r"\b\d+\s*(s|secs?|seconds?|m|mins?|minutes?|h|hrs?|hours?)\b|\bago\b|\b\d{1,2}:\d{2}(:\d{2})?\b", re.I)
SAFE_ACTIONS = {"hover", "focus", "scroll", "wait_for"}
SUBMIT_KEYS = {"enter"}


def retry_safety(action: str, entry: dict | None, value=None) -> str:
    """safe: repeating it has no side effect. conditional: repeat only after checking the current state.
    unsafe: may submit, send, buy or delete; never repeated automatically after an uncertain outcome."""
    if action in SAFE_ACTIONS:
        return "safe"
    e = entry or {}
    fp = e.get("fp") or {}
    if action == "click" and (RISKY.search(e.get("name") or "") or fp.get("sub")):
        return "unsafe"
    if action == "press" and str(value or "").lower() in SUBMIT_KEYS and (
            RISKY.search(e.get("name") or "") or fp.get("sub") or (fp.get("form") and e.get("role") == "textbox")):
        return "unsafe"
    return "conditional"


def risk_level(action: str, entry: dict | None, value=None) -> str:
    if action in ("click", "press") and RISKY.search((entry or {}).get("name") or ""):
        return "high"
    return "medium" if retry_safety(action, entry, value) == "unsafe" else "low"


def _texts(snap: Snapshot | None) -> list[tuple[str, str]]:
    """(kind, text) for headings and live-region text (role=alert/status, aria-live) in a snapshot."""
    out: list[tuple[str, str]] = []

    def walk(entries):
        for e in entries:
            if e["t"] == "h":
                out.append(("h", e["text"]))
            elif e["t"] == "txt" and e.get("live"):
                out.append(("live", e["text"]))
            elif e["t"] == "group":
                walk(e["items"])
    if snap:
        walk(snap.data.get("entries", []))
    return out


def _plain_texts(snap: Snapshot | None) -> list[tuple[str, str]]:
    """(kind, text) for ordinary text lines (not headings or live regions)."""
    out: list[tuple[str, str]] = []

    def walk(entries):
        for e in entries:
            if e["t"] == "txt" and not e.get("live"):
                out.append(("txt", e.get("text", "")))
            elif e["t"] == "group":
                walk(e["items"])
    if snap:
        walk(snap.data.get("entries", []))
    return out


def error_category(msg: str) -> str:
    """Stable category for an error message (traces, LeanBrowserError.category)."""
    m = msg.lower()
    for cat, keys in (("blocked", ("blocked:", "duplicate:", "not in allowed_domains", "outside the allowed")),
                      ("ambiguous", ("ambiguous",)),
                      ("stale", ("is gone", "page changed?", "re-rendered")),
                      ("not_found", ("not found", "no such", "no option", "found no", "nothing to extract", "no page open")),
                      ("timeout", ("timed out", "timeout", "stopped responding")),
                      ("network", ("private", "net::", "err_", "dns", "connection")),
                      ("invalid", ("needs ", "must be", "unknown ", "missing argument", "value must"))):
        if any(k in m for k in keys):
            return cat
    return "engine"


class ActionError(Exception):
    """Short, actionable error for the agent."""


_NAV_ERR = ("execution context was destroyed", "navigat", "frame was detached", "target closed",
            "context or browser has been closed", "cannot find context")


@dataclass
class TabState:
    tab: Tab
    snapper: Snapshotter
    notes: list[str] = field(default_factory=list)
    dialog_policy: str = "accept"
    nav_status: int | None = None
    pre_lines: set | None = None        # visible text lines before a submit-like action (pending detection)
    pre_expect: dict | None = None      # expect= state before the action (stale evidence doesn't count)

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
        self.last_outcome: dict | None = None  # machine-readable result of the last act/fill_form
        self._unsafe_log: dict[tuple, tuple[float, str]] = {}  # duplicate guard: key -> (time, status)
        self.duplicate_window_s = 600

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
            ts.notes.append(f"dialog {d.type} {d.message!r} {_dialog_word(policy)}")
            try:
                if policy.startswith("accept:") and d.type == "prompt":
                    await d.accept(policy[7:])
                else:
                    await (d.accept() if policy.startswith("accept") else d.dismiss())
            except Exception:
                pass
        page.on("dialog", on_dialog)

        def on_response(r):
            try:
                if r.request.is_navigation_request() and r.frame == page.main_frame:
                    ts.nav_status = r.status
            except Exception:
                pass
        page.on("response", on_response)
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
        elif role == "slider" and action in ("fill", "select"):
            await self._slide(ts, el, value)
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

    async def act(self, action: str, id: int | None = None, value=None, expect: str | None = None,
                  dry_run: bool = False) -> str:
        action = action.lower().strip()
        self.last_outcome = None
        if dry_run and action in ("back", "forward", "reload", "tab", "dialog", "wait_for"):
            return json.dumps({"executed": False, "action": action, "value": value, "target": None,
                               "risk": "low", "retry_safety": "conditional" if action != "wait_for" else "safe",
                               "requires_confirmation": False,
                               "note": "preview only; nothing was done"})
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
            v = str(value or "")
            if v.lower() in ("accept", "dismiss"):
                v = v.lower()
            elif not v.lower().startswith("accept:"):
                raise ActionError("dialog value must be accept, dismiss or accept:TEXT (text for a prompt)")
            else:
                v = "accept:" + v[7:]
            self.cur.dialog_policy = v
            return f"the next browser dialog will be {_dialog_word(v)}"

        ts = self.cur
        before = ts.snapper.last or await self._take(ts)
        entry = _index(before).get(int(id)) if id is not None else None
        note = ""
        if id is not None and action != "scroll":
            # Re-resolving a re-rendered target only reads the page; nothing has been executed yet.
            id, before, entry, note = await self._resolve_or_recover(ts, int(id), before, entry)
        name = (entry or {}).get("name", "")
        risky = action in ("click", "press") and bool(RISKY.search(name or ""))
        safety = retry_safety(action, entry, value)
        risk = risk_level(action, entry, value)
        target = None if id is None else {"id": id, "role": (entry or {}).get("role"), "name": name}
        v = str(value or "").lower() if action == "click" else ""
        dup = self._dup_key(ts, action, entry, value) if safety == "unsafe" else None
        prior = self._unsafe_log.get(dup) if dup else None
        if prior and (time.time() - prior[0] > self.duplicate_window_s or prior[1] not in ("verified", "ambiguous", "timed_out")):
            prior = None
        needs_confirm = (risky and self.confirm_risky and v not in ("confirm", "repeat")) or (prior is not None and v != "repeat")
        if dry_run:
            ctx = {k: (entry or {}).get("fp", {}).get(k) for k in ("form", "ctx", "lm") if (entry or {}).get("fp", {}).get(k)}
            return json.dumps({
                "executed": False, "action": action, "value": None if (entry or {}).get("type") == "password" else value,
                "target": target and {**target, **({"context": ctx} if ctx else {})},
                "recovered": note.strip() or None, "risk": risk, "retry_safety": safety,
                "requires_confirmation": needs_confirm,
                **({"previous": f"same action {int(time.time() - prior[0])}s ago, status {prior[1]}"} if prior else {}),
                "note": "preview only; nothing was dispatched, and the page can change before you execute"},
                ensure_ascii=False)
        base_outcome = {"action": action, "target": target, "retry_safety": safety, "risk": risk,
                        "recovery": [note.strip()] if note else []}
        if risky and self.confirm_risky and v not in ("confirm", "repeat"):
            self.last_outcome = {**base_outcome, "executed": False, "status": "blocked",
                                 "evidence": ["needs confirmation (confirm_risky)"]}
            raise ActionError(f'blocked: {(entry or {}).get("role", "element")} "{name}" looks irreversible; '
                              'call act again with value="confirm" to proceed')
        if prior is not None and v != "repeat":
            ago = int(time.time() - prior[0])
            self.last_outcome = {**base_outcome, "executed": False, "status": "blocked",
                                 "evidence": [f"duplicate of an action {ago}s ago (status {prior[1]})"]}
            raise ActionError(f'duplicate: {(entry or {}).get("role", "element")} "{name}" was already used on this page '
                              f'{ago}s ago (status: {prior[1]}). Check the page first; to really do it again call act '
                              'with value="repeat"')
        if action == "click" or (action == "press" and str(value or "").lower() in SUBMIT_KEYS):
            el = (await ts.page.evaluate_handle(RESOLVE_JS, int(id))).as_element() if id is not None else None
            bad = await self._form_invalid(el, action == "press") if el else None
            if bad:
                self.last_outcome = {**base_outcome, "executed": False, "status": "blocked",
                                     "evidence": ["form validation: " + "; ".join(bad[:4])]}
                raise ActionError("blocked: the form's own validation stops this submit (a browser would too): "
                                  + "; ".join(bad[:4]) + ". Fill those fields, then submit again")
        ts.pre_lines = await self._page_lines(ts) if safety == "unsafe" else None
        # For clicks and key presses, expect= is the evidence, so it has to be new. For field actions the field's
        # own state is the evidence, and expect= is an extra condition that just has to hold afterwards.
        ts.pre_expect = None if action in ("fill", "clear", "select", "check", "uncheck", "upload") \
            else await self._expect_pre(ts, expect)
        tabs_before = len(self.tabs)
        await self._sync_dialog_policy(ts)
        ts.nav_status = None
        rec = base_outcome["recovery"]
        uncertain, id = await self._perform_guarded(ts, action, id, value if action != "click" else None, entry, safety, rec)
        exp = {"kind": "action", "action": action, "id": id, "value": value, "entry": entry, "risky": risky,
               "safety": safety, "expect": expect, "uncertain": uncertain, "base": base_outcome}
        out = await self._after(ts, before, tabs_before, note, exp)
        if dup and self.last_outcome:
            self._unsafe_log[dup] = (time.time(), self.last_outcome["status"])
        return out

    async def _page_lines(self, ts: TabState) -> set[str]:
        """Short visible text lines of the page (for spotting a new "Processing…" that snapshots leave out)."""
        try:
            lines = await ts.page.evaluate("() => (document.body && document.body.innerText || '').split('\\n')")
        except Exception:
            return set()
        return {" ".join(x.split()) for x in lines if 0 < len(x.strip()) < 80}

    async def _new_pending(self, ts: TabState) -> list[str]:
        pre = ts.pre_lines
        if pre is None:
            return []
        return [t for t in await self._page_lines(ts) - pre if PENDING_RE.search(t)]

    async def _form_invalid(self, el, enter: bool = False) -> list[str] | None:
        try:
            return await el.evaluate(FORM_INVALID_JS, enter)
        except Exception:
            return None

    def _dup_key(self, ts: TabState, action: str, entry: dict | None, value=None) -> tuple:
        e = entry or {}
        fp = e.get("fp") or {}
        return (ts.page.url.split("#")[0], action, e.get("role"), e.get("name"), fp.get("form"), fp.get("ctx"),
                str(value or "").lower() if action == "press" else "")

    async def _perform_guarded(self, ts: TabState, action: str, el_id, value, entry: dict | None, safety: str,
                               rec: list) -> tuple[str | None, int | None]:
        """Run the action with bounded, safety-aware recovery. Returns (uncertain, id): `uncertain` is a reason
        when the action may or may not have been dispatched (the caller reports ambiguous instead of
        guessing); `id` is the element finally acted on (it changes if the target was re-identified)."""
        try:
            await self._perform(ts, action, el_id, value, entry)
            if action in ("fill", "clear", "select", "check", "uncheck") and el_id is not None \
                    and await self._target_state(ts, el_id) is None:
                # The value went into a node the page threw away mid-action (framework re-render).
                raise ActionError("the target was replaced while the action ran")
            return None, el_id
        except ActionError as e:
            if action not in ("fill", "clear", "select", "check", "uncheck") or el_id is None:
                raise
            # Partial success first: maybe the field already is in the wanted state.
            st = await self._target_state(ts, el_id)
            ok, _ = self._check_value(action, value, entry, st, None)
            if ok:
                rec.append(f"{action} raised ({e}) but the field is already in the wanted state; not retried")
                return None, el_id
            if st is not None:
                raise
            # Target detached mid-action (re-render): re-identify once and retry once. Conditional actions
            # only, and the state was checked above.
            try:
                new_id, _, new_entry, note = await self._resolve_or_recover(ts, int(el_id), await self._take(ts), entry)
            except ActionError:
                if "replaced while the action ran" in str(e):
                    return None, el_id  # nothing to retry on; verification reports the element as gone
                raise e
            rec.append(f"{action} failed because the target was re-rendered; retried once on id {new_id}")
            await self._perform(ts, action, new_id, value, new_entry)
            return None, new_id
        except Exception as e:
            msg = str(e).lower()
            if action in ("click", "press") and any(k in msg for k in _NAV_ERR):
                rec.append("the page navigated while the action ran; treated as dispatched")
                return None, el_id
            if action in ("click", "press") and safety == "unsafe":
                rec.append(f"{action} raised {type(e).__name__}; not retried (unsafe action)")
                return f"{action} may have been sent before the error ({_short(e)})", el_id
            raise

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

    async def _slide(self, ts: TabState, el, value):
        """Set a slider: a native range input gets its value plus input/change events; an ARIA slider is
        moved with the arrow keys (as a person would) until it reports the wanted value."""
        try:
            want = float(str(value).strip().rstrip("%"))
        except ValueError:
            raise ActionError("a slider value must be a number") from None
        native = await el.evaluate("e => e.tagName === 'INPUT'")
        if native:
            got = await el.evaluate("""(e, v) => { e.focus(); e.value = String(v);
                e.dispatchEvent(new Event('input', {bubbles: true})); e.dispatchEvent(new Event('change', {bubbles: true}));
                return +e.value; }""", want)
            if got != want:
                raise ActionError(f"slider took {got:g}, not {want:g} (outside its range or step?)")
            return
        read = "e => { const v = e.getAttribute('aria-valuenow'); return v === null || v === '' ? null : +v; }"
        await (el.focus() if ts.tab.engine == "chromium" else self._dom(el, "focus"))
        cur = await el.evaluate(read)
        if cur is None:
            raise ActionError("the slider reports no current value (aria-valuenow)")
        for _ in range(200):
            if cur == want:
                return
            await ts.page.keyboard.press("ArrowRight" if cur < want else "ArrowLeft")
            nxt = await el.evaluate(read)
            if nxt is None or nxt == cur or (nxt > want) != (cur > want) and nxt != want:
                cur = nxt if nxt is not None else cur
                break
            cur = nxt
        if cur != want:
            raise ActionError(f"slider stopped at {cur:g}, not {want:g} (its step may not land on that value)")

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
        if role == "slider" and action in ("fill", "select"):
            got = st.get("slider")
            try:
                ok = got is not None and float(got) == float(str(value).strip().rstrip("%"))
            except ValueError:
                ok = False
            return (True, f"slider at {got}") if ok else (False, f"slider is at {got}, expected {value}")
        if action in ("fill", "clear"):
            want = "" if action == "clear" else str(value if value is not None else "")
            got = st["value"] if st["value"] is not None else (st["text"] or "")
            if got == want or (st["text"] is not None and _norm(got) == _norm(want)):
                return True, "value set"
            from lean_browser.trace import _sensitive
            if st["type"] == "password" or _sensitive(entry or {}):
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
            ts.notes.append(f"dialog {kind} {msg!r} {_dialog_word(policy)}")
        if log:
            ts.dialog_policy = "accept"

    async def _after(self, ts: TabState, before: Snapshot, tabs_before: int, prefix: str = "",
                     expect: dict | None = None) -> str:
        await asyncio.sleep(0.05)
        settled = await self._settle(ts)
        if len(self.tabs) > tabs_before:
            return await self._new_tab_result(ts, prefix, expect)
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
                    return await self._new_tab_result(ts, prefix, expect)
                await asyncio.sleep(0.1)
        notes = self._drain(ts)
        page_changed = d is None
        changed = page_changed or bool(d)
        status = ""
        if expect:
            sig = self._signals(ts, before, after, page_changed, expect)
            submit_like = expect.get("submitted") if expect["kind"] == "form" else expect.get("safety") == "unsafe"
            if submit_like and not page_changed:
                sig["pending"] = sig["pending"] or await self._new_pending(ts)
            # The page says it is still working ("Processing…"): wait for the real answer, up to ~8 s.
            waited = 0.0
            while submit_like and sig["pending"] and not sig["errors"] and not sig["success"] and waited < 8:
                await asyncio.sleep(0.5)
                waited += 0.5
                settled = await self._settle(ts) and settled
                await self._drain_dialog_shim(ts)
                late = self._drain(ts)
                notes = (notes + "\n" + late if notes else late) if late else notes
                after = await self._take(ts)
                d = diff(before, after)
                page_changed = d is None
                changed = page_changed or bool(d)
                sig = self._signals(ts, before, after, page_changed, expect)
                if not page_changed:
                    sig["pending"] = sig["pending"] or await self._new_pending(ts)
                    if not sig["pending"] and not sig["errors"] and not sig["success"]:
                        sig["errors"] = [f'"{t[:80]}"' for t in await self._page_lines(ts) - (ts.pre_lines or set())
                                         if ERROR_RE.search(t) or NEGATED_SUCCESS_RE.search(t)][:3]
                        sig["success"] = [t for t in await self._page_lines(ts) - (ts.pre_lines or set())
                                          if SUCCESS_RE.search(t) and not ERROR_RE.search(t) and not NEGATED_SUCCESS_RE.search(t)][:1]
            exp_res = await self._check_expect(ts, expect.get("expect"), after) if expect.get("expect") else None
            status = self._status(expect, states, after, page_changed, changed, settled, bool(notes), sig, exp_res)
            if waited:
                notes = (notes + "\n" if notes else "") + f"waited {waited:.1f}s for the page to finish processing"
        head = status + prefix + (notes + "\n" if notes else "")
        if page_changed:
            return head + ts.snapper.render(after, skip_unchanged=False)
        ts.snapper.render(after)  # updates the unchanged-hash so the next snapshot() can say "unchanged"
        if not d:
            return (head + NO_CHANGE_HINT) if expect else (head + "no change. " + NO_CHANGE_HINT)
        return head + d

    async def _new_tab_result(self, ts: TabState, prefix: str, expect: dict | None) -> str:
        nts = self.cur
        # A popup's "page" event can fire while it is still on about:blank, before its own navigation starts.
        # Wait for it to load its real page (Playwright's documented popup pattern), briefly.
        try:
            for _ in range(30):
                if nts.page.url not in ("", "about:blank"):
                    break
                await asyncio.sleep(0.1)
            await nts.page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:  # noqa: BLE001 - a page that never loads is reported by the snapshot below
            pass
        await self._settle(nts)
        note = self._drain(ts)
        submit_like = expect and (expect.get("submitted") if expect.get("kind") == "form" else expect.get("safety") == "unsafe")
        if not expect:
            status = ""
        elif submit_like and not expect.get("expect"):
            status = self._finish(expect, "unverified", ["a new tab opened; read it to see whether this worked"])
        elif expect.get("expect"):
            nts.pre_expect = None
            ok, why = await self._check_expect(nts, expect["expect"], None)
            status = self._finish(expect, "verified" if ok else "unverified", ["new tab opened", why])
        else:
            status = self._finish(expect, "verified", ["new tab opened"])
        return status + prefix + (note + "\n" if note else "") + self._render_full(nts, await self._take(nts))

    def _signals(self, ts: TabState, before: Snapshot, after: Snapshot, page_changed: bool, expect: dict) -> dict:
        """Application-level evidence after an action: errors the page shows, success messages, whether the
        target or its form went away. Only things that are new since `before` count."""
        bi, ai = _index(before), _index(after)
        old = set() if page_changed else set(_texts(before))
        # A clock that ticks ("Last updated 3s ago", "12:01:07") is not new evidence: a time-like text that only
        # changed in its digits is ignored. ("Order #2 placed" after "Order #1 placed" still counts.)
        churn = {(k, re.sub(r"\d+", "#", t)) for k, t in old}
        new = [(k, t) for k, t in _texts(after) if (k, t) not in old
               and not ((k, re.sub(r"\d+", "#", t)) in churn and TIMEISH_RE.search(t))]
        errors = []
        for i, e in ai.items():
            if e.get("err") and (page_changed or (bi.get(i) or {}).get("err") != e["err"]):
                errors.append(f'{e.get("name") or e["role"]}: "{e["err"]}"')
        for k, t in new:
            negated = bool(NEGATED_SUCCESS_RE.search(t))
            if (negated or (ERROR_RE.search(t) and not SUCCESS_RE.search(t))) and (k == "live" or page_changed or negated):
                errors.append(f'"{t[:80]}"')
        if ts.nav_status and ts.nav_status >= 400 and page_changed:
            errors.append(f"HTTP {ts.nav_status}")
        success = [t for k, t in new if SUCCESS_RE.search(t) and not ERROR_RE.search(t) and not NEGATED_SUCCESS_RE.search(t)
                   and (k == "live" or page_changed or k == "h")]
        pending = [t for k, t in _texts(after) + _plain_texts(after) if PENDING_RE.search(t) and len(t) < 80]
        # After a submit the page changed, yet the same form came back with the same headings and no message:
        # a silent rejection or reload, not proof of success.
        same_form = False
        if page_changed and expect["kind"] == "action":
            ent = expect.get("entry") or {}
            heads = lambda snap: sorted(t for k, t in _texts(snap) if k == "h")
            same_form = bool(ent.get("name")) and heads(before) == heads(after) and any(
                e.get("role") == ent.get("role") and e.get("name") == ent.get("name") for e in ai.values())
        tid = expect.get("id")
        target_gone = expect["kind"] == "action" and tid is not None and not page_changed and tid in bi and tid not in ai
        # A submitted form whose text fields were emptied (todo inputs, chat boxes) is a success signal too.
        form_key = ((expect.get("entry") or {}).get("fp") or {}).get("form") if expect["kind"] == "action" else expect.get("form")
        cleared = False
        if form_key and not page_changed:
            filled = [i for i, e in bi.items() if e.get("role") == "textbox" and e.get("val") and (e.get("fp") or {}).get("form") == form_key]
            cleared = bool(filled) and all(i in ai and not ai[i].get("val") for i in filled)
        return {"errors": errors, "success": success, "target_gone": target_gone, "cleared": cleared,
                "pending": pending, "same_form": same_form}

    async def _expect_pre(self, ts: TabState, want: str | None) -> dict | None:
        """The expectation's state before the action, so evidence that was already there doesn't count."""
        if not want:
            return None
        w = want.strip()
        try:
            if w.lower().startswith("url:"):
                return {"url": ts.page.url}
            if w.lower().startswith("gone:"):
                el = (await ts.page.evaluate_handle(RESOLVE_JS, int(w[5:].strip()))).as_element()
                return {"present": el is not None}
            return {"count": await ts.page.evaluate(EXPECT_COUNT_JS, w)}
        except Exception:
            return None

    async def _check_expect(self, ts: TabState, want: str, after: Snapshot | None) -> tuple[bool, str]:
        """Caller's postcondition: "url:<part>", "gone:<id>", or text that must appear. Bounded to ~3 s.
        For clicks, key presses and submits the evidence must be new: text must appear more often than before the action (and not as "not <text>"),
        a URL part must not already have been in the URL, and a gone element must have existed before."""
        w = want.strip()
        pre = ts.pre_expect or {}
        deadline = time.time() + 3
        while True:
            try:
                if w.lower().startswith("url:"):
                    part = w[4:].strip()
                    ok, why = part in ts.page.url, f"url contains {part!r}"
                    if ok and "url" in pre and part in pre["url"] and pre["url"] == ts.page.url:
                        return False, f"the url already contained {part!r} before the action; not evidence"
                elif w.lower().startswith("gone:"):
                    gid = int(w[5:].strip())
                    if pre.get("present") is False:
                        return False, f"id {gid} was already gone before the action; not evidence"
                    el = (await ts.page.evaluate_handle(RESOLVE_JS, gid)).as_element()
                    ok, why = el is None or not await el.evaluate("e => e.isConnected && !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length)"), f"id {gid} gone"
                else:
                    n = await ts.page.evaluate(EXPECT_COUNT_JS, w)
                    before = pre.get("count") or 0
                    ok, why = n > before, f"text {w[:60]!r} found"
                    if not ok and before and time.time() >= deadline:
                        return False, f"text {w[:60]!r} was already on the page before the action; not evidence"
            except (ValueError, TypeError):
                raise ActionError('expect must be text, "url:<part>" or "gone:<id>"')
            except Exception:
                ok, why = False, "page not readable"
            if ok or time.time() >= deadline:
                return (True, "expected " + why) if ok else (False, "expected " + why.replace(" found", "").replace(" gone", " to be gone").replace("url contains", "url to contain") + ", not seen")
            await asyncio.sleep(0.25)

    def _finish(self, expect: dict, word: str, evidence: list[str]) -> str:
        ev = [e for e in evidence if e]
        base = expect.get("base") or {}
        self.last_outcome = {**base, "executed": True, "status": word, "evidence": ev}
        if expect.get("kind") == "form":
            self.last_outcome.setdefault("action", "fill_form")
        return f"status: {word} ({'; '.join(ev)})\n" if ev else f"status: {word}\n"

    def _status(self, expect: dict, states: dict, after: Snapshot, page_changed: bool, changed: bool,
                settled: bool, dialog: bool, sig: dict, exp_res: tuple[bool, str] | None) -> str:
        after_idx = _index(after)
        nav: list[str] = []
        if page_changed:
            nav.append(f"page changed: {after.data.get('path')}")
        elif after.data.get("routeChanged"):
            nav.append(f"route changed: {after.data.get('path')}")
        evidence: list[str] = []
        fields_ok = True
        if expect["kind"] == "form":
            ok_n, n, problems = expect["ok"], expect["n"], expect["problems"]
            evidence = [f"{ok_n}/{n} fields set"] + problems
            fields_ok = ok_n == n
            if not expect["submitted"]:
                if exp_res is not None:
                    evidence.append(exp_res[1])
                    fields_ok = fields_ok and exp_res[0]
                return self._finish(expect, "verified" if fields_ok else "unverified", evidence)
            submit_like = True
            evidence.append("submitted")
        else:
            action, el_id = expect["action"], expect["id"]
            if action in ("fill", "clear", "select", "check", "uncheck", "upload"):
                ok, reason = self._check_value(action, expect["value"], expect["entry"], states.get(el_id), after_idx.get(el_id))
                evidence = [reason] + nav
                err = (after_idx.get(el_id) or {}).get("err")
                if err:
                    evidence.append(f'field shows error "{err}"')
                if exp_res is not None:
                    evidence.append(exp_res[1])
                    ok = ok and exp_res[0]
                word = "verified" if ok else ("timed_out" if not settled else "unverified")
                return self._finish(expect, word, evidence)
            if action in ("hover", "focus", "scroll"):
                return self._finish(expect, "done", [])
            submit_like = expect.get("safety") == "unsafe"
        # click / press / form submit: the outcome needs evidence beyond "the event was sent".
        uncertain = expect.get("uncertain")
        if sig["errors"]:
            word = "blocked"
            evidence += nav + ["page shows errors: " + "; ".join(sig["errors"][:3])]
        elif exp_res is not None:
            word = "verified" if exp_res[0] else ("timed_out" if not settled else "unverified")
            evidence += nav + [exp_res[1]]
        elif dialog and not changed and not submit_like:
            word, evidence = "verified", evidence + ["dialog shown"]
        else:
            if sig["same_form"] and not sig["success"]:
                nav = [n + " (the same form came back, no success message)" for n in nav]
                strong = []
            else:
                strong = nav + [f'success message "{t[:60]}"' for t in sig["success"][:1]]
            if sig["target_gone"] and changed and not sig["pending"]:
                strong.append("target went away")
            if sig["cleared"] and not sig["pending"]:
                strong.append("form was cleared")
            if dialog and not changed:
                evidence.append("a dialog was answered, but nothing changed after it")
            if sig["pending"] and not strong:
                evidence.append(f'page still shows "{sig["pending"][0][:40]}"')
            if submit_like:
                if strong:
                    word, evidence = "verified", evidence + strong
                elif changed:
                    word, evidence = "unverified", evidence + ["page updated but no success signal; pass expect= to check"]
                else:
                    word = "ambiguous" if uncertain else ("timed_out" if not settled else "unverified")
                    evidence.append(uncertain or "no visible change")
            else:
                word = "verified" if changed else ("ambiguous" if uncertain else ("timed_out" if not settled else "unverified"))
                evidence += strong or ["changes below" if changed else (uncertain or "no visible change")]
        if word == "verified" and not fields_ok:
            word = "unverified"
        if expect.get("risky"):
            evidence.append("looks irreversible")
        if word in ("timed_out", "ambiguous") and submit_like:
            evidence.append("it may still take effect: check the page before repeating")
        return self._finish(expect, word, evidence)

    async def fill_form(self, fields: dict, submit=False, expect: str | None = None, dry_run: bool = False) -> str:
        ts = self.cur
        self.last_outcome = None
        before = ts.snapper.last or await self._take(ts)
        idx = _index(before)
        missing = [str(k) for k in fields if int(k) not in idx]
        first = idx.get(int(next(iter(fields)))) if fields else None
        form_key = ((first or {}).get("fp") or {}).get("form")
        dup = (ts.page.url.split("#")[0], "fill_form", form_key, tuple(sorted(map(str, fields)))) if submit else None
        prior = self._unsafe_log.get(dup) if dup else None
        if prior and (time.time() - prior[0] > self.duplicate_window_s or prior[1] not in ("verified", "ambiguous", "timed_out")):
            prior = None
        repeat = str(submit).lower() == "repeat" if isinstance(submit, str) else False
        if dry_run:
            out = {"executed": False, "action": "fill_form",
                   "fields": [{"id": int(k), "role": (idx.get(int(k)) or {}).get("role"), "name": (idx.get(int(k)) or {}).get("name"),
                               "value": "••••" if (idx.get(int(k)) or {}).get("type") == "password" else v}
                              for k, v in fields.items()],
                   "submit": bool(submit), "risk": "medium" if submit else "low",
                   "retry_safety": "unsafe" if submit else "conditional",
                   "requires_confirmation": prior is not None,
                   "note": "preview only; nothing was typed or submitted, and the page can change before you execute"}
            if missing:
                out["unknown_ids"] = missing
            if prior:
                out["previous"] = f"same form submitted {int(time.time() - prior[0])}s ago, status {prior[1]}"
            return json.dumps(out, ensure_ascii=False)
        base = {"action": "fill_form", "target": {"form": form_key, "fields": len(fields)},
                "retry_safety": "unsafe" if submit else "conditional", "risk": "medium" if submit else "low", "recovery": []}
        if prior is not None and not repeat:
            ago = int(time.time() - prior[0])
            self.last_outcome = {**base, "executed": False, "status": "blocked",
                                 "evidence": [f"duplicate of a submission {ago}s ago (status {prior[1]})"]}
            raise ActionError(f"duplicate: this form was already submitted from this page {ago}s ago (status: {prior[1]}). "
                              'Check the page first; to really submit again pass submit="repeat"')
        if repeat:
            submit = True
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
                    await self._perform_guarded(ts, "check" if on else "uncheck", fid, None, e, "conditional", base["recovery"])
                elif role in ("select", "radiogroup") or (role == "combobox" and e.get("custom")):
                    await self._perform_guarded(ts, "select", fid, value, e, "conditional", base["recovery"])
                elif role == "upload":
                    await self._perform(ts, "upload", fid, value, e)
                else:
                    await self._perform_guarded(ts, "fill", fid, value, e, "conditional", base["recovery"])
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
        uncertain = None
        ts.nav_status = None
        ts.pre_lines = await self._page_lines(ts) if submit else None
        ts.pre_expect = await self._expect_pre(ts, expect)
        if submit and not errors:
            try:
                if submit is True:
                    first_el = await self._handle(ts, int(next(iter(fields))))
                    btn = (await first_el.evaluate_handle(SUBMIT_BUTTON_JS)).as_element()
                    if not btn:
                        errors.append("submit: no submit button found in the form — pass submit=<button id>")
                    else:
                        bad = await self._form_invalid(btn)
                        if bad:
                            raise ActionError("blocked: the form's own validation stops this submit: " + "; ".join(bad[:4]))
                        await self._click(ts, btn)
                else:
                    btn = await self._handle(ts, int(submit))
                    bad = await self._form_invalid(btn)
                    if bad:
                        raise ActionError("blocked: the form's own validation stops this submit: " + "; ".join(bad[:4]))
                    await self._click(ts, btn)
            except ActionError as err:
                errors.append(f"submit: {err}")
            except Exception as err:
                if any(k in str(err).lower() for k in _NAV_ERR):
                    base["recovery"].append("the page navigated while submitting; treated as dispatched")
                else:
                    base["recovery"].append(f"submit raised {type(err).__name__}; not retried (unsafe action)")
                    uncertain = f"submit may have been sent before the error ({_short(err)})"
        prefix = ("errors:\n" + "\n".join(errors) + "\n") if errors else ""
        exp = {"kind": "form", "ok": ok_n, "n": len(fields), "problems": problems,
               "submitted": bool(submit) and not any(x.startswith("submit:") for x in errors) and not errors,
               "form": form_key, "expect": expect, "uncertain": uncertain, "base": base}
        out = await self._after(ts, before, tabs_before, prefix, exp)
        if dup and exp["submitted"] and self.last_outcome:
            self._unsafe_log[dup] = (time.time(), self.last_outcome["status"])
        return out

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
