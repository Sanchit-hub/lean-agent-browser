"""Traces: one JSONL line per tool call, for debugging agent runs and measuring tool overhead.

Opt-in (`leanb --trace ...`, `trace = true` in config, or LEANB_TRACE=1), because a trace stores page
text. Files live in ~/.lean-browser/traces/ (folder 700, files 600). Values typed into password
fields are replaced with "••••".

    leanb trace list
    leanb trace show latest
"""
from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime
from pathlib import Path

TRACE_DIR = Path(os.environ.get("LEANB_TRACE_DIR", "~/.lean-browser/traces")).expanduser()


class Tracer:
    def __init__(self, directory: Path | str | None = None):
        self.dir = Path(directory or os.environ.get("LEANB_TRACE_DIR") or TRACE_DIR).expanduser()
        self.dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.dir, 0o700)
        self.run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
        self.path = self.dir / f"{self.run_id}.jsonl"
        self.seq = 0

    def record(self, tool: str, args: dict, parts: list, started: float, engine: str | None, url: str | None):
        self.seq += 1
        text = next((p for p in parts if isinstance(p, str)), "")
        body = text.removeprefix('<page untrusted="true">\n').removesuffix("\n</page>")
        first = body.split("\n", 1)[0]
        rec = {
            "seq": self.seq, "ts": round(started, 3), "ms": int((time.time() - started) * 1000),
            "tool": tool, "args": args, "engine": engine, "url": url,
            "error": text.startswith("Error:"),
            "status": first.split(" ", 2)[1] if first.startswith("status: ") else None,
            "chars": len(body), "est_tokens": len(body) // 4,
            "image": any(isinstance(p, bytes) for p in parts),
            "result": body[:4000],
        }
        new = not self.path.exists()
        with open(self.path, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if new:
            os.chmod(self.path, 0o600)


def redact_args(tool: str, args: dict, index: dict) -> dict:
    """Copy of args with values for password fields masked (index: snapshot id -> entry)."""
    a = json.loads(json.dumps(args, default=str))
    is_pw = lambda i: (index.get(int(i)) or {}).get("type") == "password" if str(i).isdigit() else False
    if tool == "act" and a.get("action") in ("fill", "press") and a.get("id") is not None and is_pw(a["id"]):
        a["value"] = "••••"
    if tool == "fill_form" and isinstance(a.get("fields"), dict):
        a["fields"] = {k: ("••••" if is_pw(k) else v) for k, v in a["fields"].items()}
    return a


def _runs(directory: Path = TRACE_DIR) -> list[Path]:
    return sorted(directory.glob("*.jsonl")) if directory.exists() else []


def list_runs(directory: Path | None = None) -> str:
    directory = Path(directory or TRACE_DIR)
    runs = _runs(directory)
    if not runs:
        return f"no traces in {directory} (run leanb with --trace)"
    out = []
    for p in runs[-20:]:
        recs = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
        first_url = next((r["args"].get("url") for r in recs if r["tool"] == "open"), "")
        out.append(f"{p.stem}  {len(recs):>3} calls  {sum(r['est_tokens'] for r in recs):>7,} ~tok  {first_url}")
    return "\n".join(out)


def _summ(tool: str, args: dict) -> str:
    if tool == "open":
        return args.get("url", "")
    if tool == "act":
        return " ".join(str(x) for x in (args.get("action"), args.get("id"), args.get("value")) if x is not None)
    if tool == "fill_form":
        return f"{len(args.get('fields') or {})} fields" + (", submit" if args.get("submit") else "")
    return " ".join(f"{k}={v}" for k, v in args.items())


def show_run(run: str = "latest", directory: Path | None = None, full: bool = False) -> str:
    directory = Path(directory or TRACE_DIR)
    runs = _runs(directory)
    if not runs:
        return f"no traces in {directory}"
    p = runs[-1] if run == "latest" else directory / f"{run}.jsonl"
    if not p.exists():
        return f"no trace {run!r}; see: leanb trace list"
    recs = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    total_ms = sum(r["ms"] for r in recs)
    lines = [f"run {p.stem}: {len(recs)} calls, {total_ms / 1000:.1f} s, ~{sum(r['est_tokens'] for r in recs):,} tokens of tool output",
             f"{'#':>3}  {'tool':<10} {'args':<44} {'result':<12} {'engine':<9} {'ms':>6} {'~tok':>6}"]
    for r in recs:
        res = "ERROR" if r["error"] else (r["status"] or ("image" if r["image"] else "ok"))
        lines.append(f"{r['seq']:>3}  {r['tool']:<10} {_summ(r['tool'], r['args'])[:44]:<44} {res:<12} "
                     f"{(r['engine'] or '-'):<9} {r['ms']:>6} {r['est_tokens']:>6}")
        if full or r["error"]:
            lines += ["       " + l for l in r["result"].splitlines()[:12]]
    return "\n".join(lines)


# ---------- replay / export / delete ----------
READ_ONLY_TOOLS = {"open", "snapshot", "extract", "screenshot", "memory"}


def _load(run: str, directory: Path | None) -> tuple[Path, list[dict]]:
    directory = Path(directory or TRACE_DIR)
    runs = _runs(directory)
    p = (runs[-1] if runs else None) if run == "latest" else directory / f"{run}.jsonl"
    if not p or not p.exists():
        raise FileNotFoundError(f"no trace {run!r} in {directory}")
    return p, [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def _outcome(text: str) -> str:
    """Comparable outcome of one call: error, status word, or the page title line."""
    body = text.removeprefix('<page untrusted="true">\n').removesuffix("\n</page>")
    if body.startswith("Error:"):
        return "error"
    first = body.split("\n", 1)[0]
    if first.startswith("status: "):
        return first.split(" ", 2)[1]
    if first.startswith("page: "):
        return first.split(" | url:", 1)[0]
    return "ok"


async def replay(run: str = "latest", directory: Path | None = None, allow_actions: bool = False,
                 config=None) -> str:
    """Re-run a trace and report the first call whose outcome differs. Local-page traces replay fully;
    traces that touched public sites replay only read-only calls unless allow_actions=True. Calls whose
    recorded values were redacted (passwords) are skipped."""
    from urllib.parse import urlparse

    from lean_browser.engine import is_private_host
    from lean_browser.tools import Config, LeanBrowser

    path, recs = _load(run, directory)
    urls = [r["args"].get("url") or r.get("url") for r in recs]
    hosts = {urlparse(u).hostname for u in urls if u}
    local = bool(hosts) and all(is_private_host(h or "") for h in hosts)
    full = local or allow_actions
    cfg = config or Config.load(allow_private_network=True if local else None)
    lines = [f"replaying {path.stem}: {len(recs)} calls ({'all calls' if full else 'read-only calls only: pass --allow-actions to replay actions'})",
             f"{'#':>3}  {'tool':<10} {'recorded':<26} {'replayed':<26} result"]
    first_div = None
    async with LeanBrowser(cfg) as b:
        for r in recs:
            tool, args = r["tool"], r["args"]
            rec_out = "error" if r["error"] else _outcome(r["result"])
            if "••••" in json.dumps(args, ensure_ascii=False):
                lines.append(f"{r['seq']:>3}  {tool:<10} {rec_out[:26]:<26} {'-':<26} skipped (redacted value)")
                continue
            if not full and tool not in READ_ONLY_TOOLS:
                lines.append(f"{r['seq']:>3}  {tool:<10} {rec_out[:26]:<26} {'-':<26} skipped (action on a live site)")
                continue
            parts = await b.call(tool, args)
            text = next((p for p in parts if isinstance(p, str)), "")
            new_out = "image" if (not text and parts) else _outcome(text)
            if r.get("image") and new_out == "image":
                rec_out = "image"
            same = new_out == rec_out
            if not same and first_div is None:
                first_div = r["seq"]
            lines.append(f"{r['seq']:>3}  {tool:<10} {rec_out[:26]:<26} {new_out[:26]:<26} {'same' if same else 'DIFFERENT'}")
    lines.append(f"first divergence at call #{first_div}" if first_div else "no divergence: every replayed call had the same outcome")
    if not local:
        lines.append("note: live sites change; a divergence may come from the site, not from Lean")
    return "\n".join(lines)


def export_run(run: str, out: Path, directory: Path | None = None) -> str:
    path, recs = _load(run, directory)
    out = Path(out)
    out.write_text(path.read_text())
    os.chmod(out, 0o600)
    return (f"exported {len(recs)} calls to {out} (mode 600). Passwords are redacted, but the file still holds "
            f"page text from {len({r.get('url') for r in recs})} URL(s): review it before sharing.")


def delete_runs(run: str, directory: Path | None = None) -> str:
    directory = Path(directory or TRACE_DIR)
    targets = _runs(directory) if run == "all" else [directory / f"{run}.jsonl"]
    n = 0
    for p in targets:
        if p.exists():
            p.unlink()
            n += 1
    return f"deleted {n} trace(s) from {directory}"
