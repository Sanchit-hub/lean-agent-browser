"""Snapshot layer: run snapshot.js in the page and render its JSON as compact text.

    snap = await Snapshotter().take(page)           # actions mode (default)
    text = snapper.render(snap, budget=800)

Modes: actions (interactive elements + headings), read (main content as markdown),
full (everything expanded, plus body text). Collapsed groups expand with expand=<handle>,
cut-off output continues with more(<k>), and find(<text>) searches everything, collapsed or not.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import Page

SNAPSHOT_JS = (Path(__file__).parent / "snapshot.js").read_text()
DEFAULT_BUDGET = {"actions": 800, "read": 1500, "full": 4000}  # tokens (≈ chars / 4)
CHARS_PER_TOKEN = 4


class SnapshotTimeout(Exception):
    """snapshot.js took longer than the budget (the engine layer then routes the page to Chromium)."""


@dataclass
class Snapshot:
    data: dict
    engine: str = ""
    seq: int = 0
    page_changed: bool = False

    @property
    def mode(self) -> str:
        return self.data.get("mode", "actions")

    @property
    def ms(self) -> int:
        return self.data.get("ms", 0)


# ---------- line formatting ----------
def _q(s: str) -> str:
    return '"' + (s or "").replace('"', "'") + '"'


def el_line(e: dict) -> str:
    role = e["role"]
    s = f"{e['id']}: {role} {_q(e.get('name', ''))}"
    if e.get("req"):
        s += "*"
    if e.get("rich"):
        s += " (rich)"
    if e.get("custom"):
        s += " (custom)"
    if e.get("type"):
        s += f" type={e['type']}"
    if role == "select":
        opts = "|".join(e.get("options", []))
        s += f" [{opts}{'|+' + str(e['more']) if e.get('more') else ''}]"
    if role == "radiogroup":
        s += " [" + "|".join(o["label"] for o in e.get("options", [])) + "]"
    if role in ("checkbox", "switch"):
        s += " on" if e.get("checked") else " off"
    if e.get("accept"):
        s += f" accept={e['accept']}"
    if "val" in e:
        quote = role in ("textbox", "combobox") and e.get("type") != "password"
        s += f" = {_q(e['val']) if quote else e['val']}"
    if "expanded" in e:
        s += " [open]" if e["expanded"] else ""
    if e.get("selected"):
        s += " (selected)"
    if e.get("readonly"):
        s += " readonly"
    if e.get("disabled"):
        s += " disabled"
    if e.get("err"):
        s += f" !{_q(e['err'])}"
    if e.get("frame"):
        s = f"[frame:{e['frame']}] " + s
    return s


def _ref(e: dict, text: str) -> str:
    name = e.get("name", "")
    if e["role"] in ("link", "button") and name and name.lower() in text.lower():
        return f"[{e['id']} {e['role']}]"
    return "[" + el_line(e) .replace(": ", " ", 1) + "]"


def item_line(it: dict) -> str:
    text = it.get("text", "")
    refs = " ".join(_ref(r, text) for r in it.get("refs", []))
    return f"- {text}" + (f"  {refs}" if refs else "")


def group_preview(g: dict) -> str:
    kind = g["kind"]
    label = f" {_q(g['label'])}" if g.get("label") else ""
    if kind in ("list", "table"):
        unit = "rows" if kind == "table" else "items"
        prev = ", ".join(_q(i.get("text", "")[:40]) for i in g["items"][:2])
        return f"{kind}{label} {g['count']} {unit}: {prev}, … [expand:{g['handle']}]"
    names = []
    for i in g["items"]:
        if i["t"] == "el" and i.get("name"):
            names.append(i["name"][:20])
        if len(names) == 3:
            break
    extra = g.get("count", 0) - len(names)
    return f"{kind}{label}: {', '.join(names)}{f' (+{extra})' if extra > 0 else ''} [expand:{g['handle']}]"


def render_entries(entries: list[dict], expand_all: bool = False, expand: str | None = None, indent: str = "") -> list[str]:
    out = []
    for e in entries:
        t = e["t"]
        if t == "el":
            out.append(indent + el_line(e))
        elif t == "h":
            out.append(indent + "#" * e["lvl"] + " " + e["text"])
        elif t == "txt":
            out.append(indent + "text: " + e["text"])
        elif t == "item":
            out.append(indent + item_line(e))
        elif t == "group":
            if e["kind"] not in ("list", "table") and e.get("count", 0) <= 3 and expand != e["handle"]:
                out.extend(render_entries(e["items"], expand_all, expand, indent))  # collapsing would save nothing
            elif expand_all or expand == e["handle"]:
                label = f" {_q(e['label'])}" if e.get("label") else ""
                out.append(f"{indent}{e['kind']}{label} [{e['handle']}]:")
                out.extend(render_entries(e["items"], expand_all, expand, indent + "  "))
            else:
                out.append(indent + group_preview(e))
    return out


def _walk(entries, group=None):
    for e in entries:
        yield e, group
        if e["t"] == "group":
            yield from _walk(e["items"], e)
        elif e["t"] == "item":
            for r in e.get("refs", []):
                yield r, group


def find_group(entries: list[dict], handle: str) -> dict | None:
    for e, _ in _walk(entries):
        if e["t"] == "group" and e["handle"] == handle:
            return e
    return None


@dataclass
class Snapshotter:
    """Per-tab snapshot state: change detection, more-cursors, last snapshot for expand/find."""
    timeout_s: float = 2.0
    seq: int = 0
    last: Snapshot | None = None
    _last_hash: str = ""
    _doc_id: str = ""
    _cursors: dict = field(default_factory=dict)
    _k: int = 0

    async def take(self, page: Page, mode: str = "actions", engine: str = "") -> Snapshot:
        try:
            data = await asyncio.wait_for(page.evaluate(SNAPSHOT_JS, {"mode": mode}), self.timeout_s)
        except asyncio.TimeoutError as e:
            raise SnapshotTimeout(f"snapshot took longer than {self.timeout_s}s") from e
        self.seq += 1
        changed = bool(self._doc_id) and data["docId"] != self._doc_id
        self._doc_id = data["docId"]
        snap = Snapshot(data, engine, self.seq, changed)
        if mode == "actions":
            self.last = snap
        return snap

    def _header(self, snap: Snapshot) -> str:
        d = snap.data
        parts = [f"page: {d['title']}", f"url: {d['path']}"]
        if snap.engine:
            parts.append(snap.engine)
        flags = []
        if snap.page_changed:
            flags.append("page changed")
        elif d.get("routeChanged"):
            flags.append("route changed")
        return " | ".join(parts) + (f" | {', '.join(flags)}" if flags else "")

    def _budgeted(self, lines: list[str], budget: int) -> list[str]:
        limit = budget * CHARS_PER_TOKEN
        used, out = 0, []
        for i, line in enumerate(lines):
            if used + len(line) + 1 > limit and out:
                self._k += 1
                key = f"k{self._k}"
                self._cursors[key] = lines[i:]
                out.append(f"[more:{key}] ({len(lines) - i} more lines)")
                return out
            out.append(line)
            used += len(line) + 1
        return out

    def render(self, snap: Snapshot, budget: int | None = None, expand: str | None = None,
               skip_unchanged: bool = True) -> str:
        d = snap.data
        budget = budget or DEFAULT_BUDGET.get(snap.mode, 800)
        if snap.mode == "read":
            body = d.get("markdown", "").split("\n")
            return "\n".join([self._header(snap)] + self._budgeted(body, budget))
        h = hashlib.sha1(json.dumps(d["entries"], sort_keys=True).encode()).hexdigest()
        if skip_unchanged and expand is None and h == self._last_hash and not snap.page_changed and snap.mode == "actions":
            return f"unchanged (snapshot #{snap.seq - 1})"
        if snap.mode == "actions" and expand is None:
            self._last_hash = h
        lines = [self._header(snap)]
        if d.get("dialog"):
            lines.append(f"dialog {_q(d['dialog']['name'])} (page behind it is hidden until it closes):")
        if d.get("banner"):
            b = d["banner"]
            lines.append(f"banner: {b['label']} " + " ".join(f"[{x['name'].lower()}:{x['id']}]" for x in b["buttons"]))
        if expand:
            g = find_group(d["entries"], expand)
            if not g:
                return f"no group {expand!r} in the latest snapshot — call snapshot() again"
            lines += render_entries([g], expand=expand)
        else:
            lines += render_entries(d["entries"], expand_all=snap.mode == "full")
        return "\n".join(self._budgeted(lines, budget))

    def more(self, key: str, budget: int = 800) -> str:
        rest = self._cursors.pop(key, None)
        if rest is None:
            return f"no continuation {key!r} (it was already shown, or the page changed)"
        return "\n".join(self._budgeted(rest, budget))

    def find(self, text: str, limit: int = 20) -> str:
        if not self.last:
            return "no snapshot yet"
        needle = text.lower()
        hits = []
        for e, g in _walk(self.last.data["entries"]):
            hay = " ".join(str(e.get(k, "")) for k in ("name", "val", "text", "label")).lower()
            if e["t"] == "group" or needle not in hay:
                continue
            line = render_entries([e])[0].strip()
            hits.append(f"{line}" + (f"   (in {g['kind']} [{g['handle']}])" if g else ""))
            if len(hits) >= limit:
                break
        return "\n".join(hits) if hits else f"no match for {text!r}"


def wrap_untrusted(text: str) -> str:
    return f'<page untrusted="true">\n{text}\n</page>'
