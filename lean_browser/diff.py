"""Diff layer: compare the before/after actions snapshots of one page.

    ~2 textbox "Email" = "asha@x.com"   (error cleared)
    +9 text "Application received"
    -8 button "Submit application"

Returns None when the page changed so much that a diff is not useful (new document, a dialog
opened or closed); the caller then sends a full snapshot instead.
"""
from __future__ import annotations

import re

from lean_browser.snapshot import Snapshot, el_line, group_preview

_HANDLE = re.compile(r" \[expand:[a-z]\d+\]")


def _flatten(data: dict) -> dict[str, tuple[str, dict]]:
    """Top-level view keyed by a stable key -> (line, entry). Collapsed groups are one line."""
    out: dict[str, tuple[str, dict]] = {}
    b = data.get("banner")
    if b:
        out["banner"] = ("banner: " + b["label"] + " " + " ".join(f"[{x['name'].lower()}:{x['id']}]" for x in b["buttons"]), {})
    seen_text: dict[str, int] = {}
    for e in data.get("entries", []):
        t = e["t"]
        if t == "el":
            out[f"el:{e['id']}"] = (el_line(e), e)
        elif t == "group":
            key = f"group:{e['kind']}:{e.get('label', '')}"
            out[key] = (group_preview(e), e)
            # elements inside collapsed region groups still matter when they change value
            for it in e["items"]:
                if it["t"] == "el":
                    out[f"el:{it['id']}"] = (el_line(it), {**it, "_hidden_in": e["handle"]})
        else:
            text = ("#" * e["lvl"] + " " if t == "h" else "text: ") + e["text"]
            n = seen_text.get(text, 0)
            seen_text[text] = n + 1
            out[f"{t}:{text}:{n}"] = (text, e)
    return out


def _note(before: dict, after: dict) -> str:
    notes = []
    if before.get("err") and not after.get("err"):
        notes.append("error cleared")
    elif after.get("err") and not before.get("err"):
        notes.append("error appeared")
    return f"   ({', '.join(notes)})" if notes else ""


def diff(before: Snapshot, after: Snapshot) -> str | None:
    b, a = before.data, after.data
    if after.page_changed or b.get("docId") != a.get("docId"):
        return None
    if bool(b.get("dialog")) != bool(a.get("dialog")):
        return None
    fb, fa = _flatten(b), _flatten(a)
    lines: list[str] = []
    for k, (line, e) in fa.items():
        if k not in fb:
            if e.get("_hidden_in"):
                continue  # newly rendered inside a collapsed group: covered by the group's count line
            lines.append("+" + line)
        elif _HANDLE.sub("", fb[k][0]) != _HANDLE.sub("", line):
            if k.startswith("group:"):
                lines.append("~" + line)
            elif e.get("_hidden_in") and fb[k][1].get("_hidden_in"):
                lines.append("~" + line + f"   (in [{e['_hidden_in']}])")
            else:
                lines.append("~" + line + _note(fb[k][1], e))
    for k, (line, e) in fb.items():
        if k not in fa and not e.get("_hidden_in"):
            lines.append("-" + line)
    header = []
    if a.get("routeChanged") or b.get("path") != a.get("path"):
        header.append(f"route changed: {a['path']}")
    if b.get("title") != a.get("title"):
        header.append(f"title: {a['title']}")
    return "\n".join(header + lines) if (lines or header) else ""
