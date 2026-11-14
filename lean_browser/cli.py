"""leanb: command-line front end.

  leanb open <url> [--mode actions|read|full]     one-shot snapshot of a page
  leanb shell <url>                               interactive session (act/fill/snapshot/...)
  leanb mcp                                       run the MCP server on stdio
  leanb install                                   download the engines (pinned, checksummed Obscura + Chromium)
  leanb doctor                                    check the install (hashes, sandbox, both engines)
  leanb trace list | show [run|latest] [--full]   inspect traces (record them with --trace)
  leanb bench [--quick] [--runs N] [--modes ...]  run the eval suite (needs the claude CLI or an API key)

Common flags: --engine obscura|chromium, --allow-private-network, --config PATH
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shlex
import sys

from lean_browser.tools import Config, LeanBrowser

SHELL_HELP = """commands:
  snapshot [actions|read|full]      find <text>      expand <handle>      more <k>
  act <action> [id] [value]         e.g.  act click 6   act fill 3 asha@x.com   act press Enter
  fill <id>=<value> ... [--submit]  extract [auto|table|list|form]
  screenshot [id] [file.png]        quit"""


def _config(a) -> Config:
    return Config.load(a.config, prefer=a.engine, allow_private_network=True if a.allow_private_network else None,
                       trace=True if getattr(a, "trace", False) else None)


def _show(parts):
    for p in parts:
        print(p if isinstance(p, str) else f"<{len(p)} byte PNG>")


async def cmd_open(a):
    async with LeanBrowser(_config(a)) as lb:
        _show(await lb.call("open", {"url": a.url, "mode": a.mode}))


async def cmd_shell(a):
    async with LeanBrowser(_config(a)) as lb:
        _show(await lb.call("open", {"url": a.url}))
        print(SHELL_HELP)
        loop = asyncio.get_running_loop()
        while True:
            try:
                line = await loop.run_in_executor(None, lambda: input("leanb> "))
            except (EOFError, KeyboardInterrupt):
                break
            try:
                w = shlex.split(line)
            except ValueError as e:
                print(f"Error: {e}")
                continue
            if not w:
                continue
            c, rest = w[0], w[1:]
            if c in ("quit", "exit"):
                break
            elif c == "help":
                print(SHELL_HELP)
            elif c == "snapshot":
                _show(await lb.call("snapshot", {"mode": rest[0]} if rest else {}))
            elif c in ("find", "expand", "more") and rest:
                _show(await lb.call("snapshot", {c: " ".join(rest)}))
            elif c == "open" and rest:
                _show(await lb.call("open", {"url": rest[0]}))
            elif c == "act" and rest:
                args = {"action": rest[0]}
                if len(rest) > 1:
                    if rest[1].isdigit():
                        args["id"] = int(rest[1])
                        if len(rest) > 2:
                            args["value"] = " ".join(rest[2:])
                    else:
                        args["value"] = " ".join(rest[1:])
                _show(await lb.call("act", args))
            elif c == "fill":
                submit = "--submit" in rest
                fields = dict(x.split("=", 1) for x in rest if "=" in x)
                _show(await lb.call("fill_form", {"fields": fields, "submit": submit}))
            elif c == "extract":
                _show(await lb.call("extract", {"kind": rest[0]} if rest else {}))
            elif c == "screenshot":
                args = {"id": int(rest[0])} if rest and rest[0].isdigit() else {}
                parts = await lb.call("screenshot", args)
                out = next((x for x in rest if x.endswith(".png")), "screenshot.png")
                if parts and isinstance(parts[0], bytes):
                    open(out, "wb").write(parts[0])
                    print(f"saved {out}")
                else:
                    _show(parts)
            else:
                print("unknown command — type help")


async def cmd_doctor(a) -> int:
    """Verify the Obscura binaries, start it sandboxed, and load a page in both engines."""
    from lean_browser.engine import BrowserManager, EngineError, ObscuraProcess, find_obscura, verify_obscura
    ok = True
    page = "data:text/html,<title>ok</title><main><button>Ping</button></main>"
    b = find_obscura()
    if not b:
        print("obscura:  not installed (Chromium will serve every page) — run ./install.sh")
    else:
        try:
            verify_obscura(b)
            p = ObscuraProcess(b)
            await asyncio.to_thread(p.start)
            p.stop()
            print(f"obscura:  {b} — hash OK, starts sandboxed on 127.0.0.1 with a token")
        except EngineError as e:
            ok = False
            print(f"obscura:  FAILED — {e}")
    for prefer in (["obscura"] if b else []) + ["chromium"]:
        try:
            async with BrowserManager(prefer=prefer) as bm:
                tab = await bm.open(page)
                title = await tab.page.title()
                print(f"{prefer + ':':9} loads pages (engine used: {tab.engine}, title {title!r})")
                if prefer == "obscura" and tab.engine != "obscura":
                    ok = False
                    print(f"          fell back: {tab.reason}")
        except Exception as e:
            ok = False
            print(f"{prefer + ':':9} FAILED — {type(e).__name__}: {str(e).splitlines()[0][:150]}")
    print("all good" if ok else "problems found")
    return 0 if ok else 1


def cmd_bench(a) -> int:
    """Thin wrapper over the eval drivers so the benchmark is one command."""
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    if not (root / "evals").is_dir():
        print("leanb bench runs from a source checkout (it needs evals/)")
        return 2
    module = "evals.claude_driver" if a.agent == "claude-cli" else "evals.runner"
    args = [sys.executable, "-m", module]
    if a.quick:
        args.append("--quick")
    else:
        args += ["--runs", str(a.runs)]
    modes = a.modes or "playwright-mcp,lean"
    args += ["--modes", modes]
    if a.tasks:
        args += ["--tasks", a.tasks]
    if a.agent == "api":
        args.append("-y")
    return subprocess.call(args, cwd=root)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="leanb", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=["obscura", "chromium"])
    ap.add_argument("--allow-private-network", action="store_true", help="allow localhost/LAN pages (dev testing)")
    ap.add_argument("--config", help="config file (default ~/.lean-browser/config.toml)")
    ap.add_argument("--trace", action="store_true", help="record a JSONL trace to ~/.lean-browser/traces")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("open", help="print a snapshot of a page")
    p.add_argument("url")
    p.add_argument("--mode", choices=["actions", "read", "full"], default="actions")
    p = sub.add_parser("shell", help="interactive session")
    p.add_argument("url")
    sub.add_parser("mcp", help="run the MCP server on stdio")
    sub.add_parser("install", help="download the engines (Obscura + Chromium) into ~/.lean-browser")
    sub.add_parser("doctor", help="check the install")
    p = sub.add_parser("trace", help="inspect recorded traces")
    p.add_argument("what", choices=["list", "show"])
    p.add_argument("run", nargs="?", default="latest")
    p.add_argument("--full", action="store_true", help="print each call's result")
    p.add_argument("--dir", help="trace folder (default ~/.lean-browser/traces; bench runs keep theirs in evals/results/*/traces)")
    p = sub.add_parser("bench", help="run the eval suite with a real agent")
    p.add_argument("--agent", choices=["claude-cli", "api"], default="claude-cli",
                   help="claude-cli uses your Claude Code login (no API key); api uses ANTHROPIC_API_KEY")
    p.add_argument("--quick", action="store_true", help="6 tasks, 1 run")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--modes", default=None, help="comma-separated; default: playwright-mcp,lean")
    p.add_argument("--tasks", default=None, help="comma-separated task ids")
    a = ap.parse_args(argv)
    if a.cmd == "open":
        asyncio.run(cmd_open(a))
    elif a.cmd == "shell":
        asyncio.run(cmd_shell(a))
    elif a.cmd == "trace":
        from lean_browser import trace
        print(trace.list_runs(a.dir) if a.what == "list" else trace.show_run(a.run, a.dir, full=a.full))
    elif a.cmd == "bench":
        sys.exit(cmd_bench(a))
    elif a.cmd == "install":
        from lean_browser.installer import main as install_main
        sys.exit(install_main())
    elif a.cmd == "doctor":
        sys.exit(asyncio.run(cmd_doctor(a)))
    elif a.cmd == "mcp":
        from lean_browser.mcp_server import serve_stdio
        asyncio.run(serve_stdio(_config(a)))


if __name__ == "__main__":
    main()
