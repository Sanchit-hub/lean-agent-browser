"""`leanb setup` and `leanb uninstall`: the guided first run, and a clean removal.

setup: platform check -> engines (pinned, checksummed; asks first) -> default config (only if missing)
-> doctor -> Claude Code registration (shows the exact entry, asks first) -> next steps.
Safe to re-run: verified engines are skipped, an existing config is never overwritten, and an existing
Claude Code entry is updated rather than duplicated.
"""
from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

from lean_browser import claude_code, doctor

HOME = Path.home() / ".lean-browser"
CONFIG = HOME / "config.toml"
CONFIG_TEMPLATE = """\
# Lean Agent Browser config. Every line is commented out, so the defaults apply.
# prefer = "obscura"                # or "chromium"
# allow_private_network = false     # localhost / LAN / cloud metadata are blocked unless true
# allowed_domains = []              # e.g. ["example.com"]: refuse to open anything else
# fallback_domains = []             # always use Chromium for these hosts
# allowed_upload_dirs = ["~/Downloads"]
# block = true                      # Chromium: skip images, fonts, media and tracker hosts
# confirm_risky = false             # true: pay/delete/send-like buttons need act(..., value="confirm")
# trace = false                     # JSONL trace of every call in ~/.lean-browser/traces (local only)
"""
FIRST_PROMPT = ("Use Lean Agent Browser to open https://example.com. Take a compact snapshot and explain the page's "
                "main content. Do not submit forms, purchase anything, or perform any external side effect.")


def say(msg: str = ""):
    print(msg, flush=True)


def ask(question: str, yes: bool) -> bool:
    if yes:
        say(f"{question} [Y/n] yes (--yes)")
        return True
    if not sys.stdin.isatty():
        say(f"{question} [Y/n] no (not an interactive terminal; re-run with --yes to accept)")
        return False
    try:
        return input(f"{question} [Y/n] ").strip().lower() in ("", "y", "yes")
    except EOFError:
        return False


def _engines_ready() -> bool:
    from lean_browser.engine import OBSCURA_SHA256, EngineError, find_obscura, verify_obscura
    from lean_browser.installer import BROWSERS
    if not any(BROWSERS.glob("chromium-*")):
        return False
    if OBSCURA_SHA256:
        b = find_obscura()
        try:
            verify_obscura(b) if b else None
        except EngineError:
            return False
        return b is not None
    return True


def setup_engines(yes: bool) -> bool:
    from lean_browser.engine import OBSCURA_SHA256, OBSCURA_VERSION
    from lean_browser.installer import main as install_main
    if _engines_ready():
        say(f"Engines: already installed and verified in {doctor._home(str(HOME))}")
        return True
    say("Lean needs two browser engines, installed only into ~/.lean-browser:")
    if OBSCURA_SHA256:
        say(f"  - Obscura {OBSCURA_VERSION} (~135 MB) from github.com/h4ckf0r0day/obscura, SHA256-checked against a pinned value")
    say("  - Playwright's Chromium (~570 MB) from Playwright's download servers")
    if not ask("Download and install them now?", yes):
        say("Skipped. Install them later with: leanb install")
        return False
    install_main()
    return True


def setup_config(yes: bool):
    if CONFIG.exists():
        say(f"Config: keeping your existing {doctor._home(str(CONFIG))}")
        return
    HOME.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(CONFIG_TEMPLATE)
    say(f"Config: wrote {doctor._home(str(CONFIG))} (all defaults, commented out)")


def setup_claude(yes: bool, scope: str) -> bool | None:
    """True registered, False failed or declined, None Claude Code not installed."""
    claude = claude_code.find_claude()
    if not claude:
        say("Claude Code: the `claude` CLI was not found. Install Claude Code, then run: leanb setup --client claude")
        return None
    entry, shown = claude_code.proposed(scope)
    old = claude_code.get_registration(claude)
    if old and old.get("command") == entry["command"] and old.get("args") == entry["args"] and old.get("scope") == scope:
        say(f"Claude Code: '{claude_code.NAME}' is already registered ({scope} scope) with this leanb. Nothing to change.")
        return True
    say("Claude Code: this will run")
    say("  " + " ".join(shown[:-1]) + " '" + shown[-1] + "'")
    if old:
        say(f"  replacing the current '{claude_code.NAME}' entry ({old.get('scope')} scope): "
            f"{old.get('command')} {' '.join(old.get('args', []))}")
    say(f"  Scope {scope!r}: " + {"user": "available in every project", "local": "only this folder, only you",
                                  "project": "shared through .mcp.json in this folder"}[scope]
        + ". Other MCP servers are not touched.")
    if not ask("Register Lean Agent Browser with Claude Code?", yes):
        say("Skipped. Register later with: leanb setup --client claude")
        return False
    ok, msg = claude_code.register(claude, scope)
    say(("Claude Code: " if ok else "Claude Code: FAILED: ") + msg)
    if ok:
        reg = claude_code.get_registration(claude) or {}
        if reg.get("status"):
            say(f"Claude Code reports: {reg['status']}")
    return ok


def run_setup(a) -> int:
    from lean_browser import __version__
    say(f"Lean Agent Browser {__version__} setup ({doctor.install_kind()} install)\n")
    plat = doctor.check_platform()
    say(f"Platform: {plat.detail}")
    if plat.status != doctor.PASS:
        say(f"  {plat.fix}")
        if not ask("Continue anyway?", a.yes):
            return 1
    from lean_browser.engine import IS_MAC, OBSCURA_SHA256, sandbox_tool
    if OBSCURA_SHA256 and not IS_MAC and not sandbox_tool():
        say("Note: bubblewrap is not installed, so Obscura stays off and Chromium serves every page.\n"
            "      Chromium works, but without Obscura's sandbox and memory savings. Install it with: sudo apt install bubblewrap")
    say()
    setup_engines(a.yes)
    setup_config(a.yes)
    say("\nChecking the install (leanb doctor)...")
    checks = asyncio.run(doctor.run_checks(a.config, claude=False))
    say(doctor.render(checks))
    ok, text = doctor.summary(checks)
    say(text + "\n")
    if not ok:
        say("Fix the failed checks above, then run leanb setup again. Claude Code was not changed.")
        return 1
    client = a.client or ("claude" if claude_code.find_claude() else "none")
    registered = setup_claude(a.yes, a.scope) if client == "claude" else None
    if registered is False:
        return 1
    say("\nReady." if registered else "\nThe browser works. Connect an MCP client to use it from an agent.")
    if registered:
        say("Next:\n  1. Start a new Claude Code session (or restart it). Run /mcp and check that lean-browser is connected.\n"
            f"  2. Try this prompt:\n     {FIRST_PROMPT}")
    say("Troubleshooting: leanb doctor (add --json for a bug report). Docs: docs/TROUBLESHOOTING.md")
    return 0


def _size(p: Path) -> str:
    total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else (p.stat().st_size if p.exists() else 0)
    return f"{total / 1e6:.0f} MB"


def run_uninstall(a) -> int:
    targets = [HOME] if a.all else [p for p in (HOME / "bin", HOME / "pw-browsers") if p.exists()]
    claude = claude_code.find_claude()
    reg = claude_code.get_registration(claude) if claude else None
    say("This removes:")
    if reg:
        say(f"  - the '{claude_code.NAME}' MCP server from Claude Code ({reg.get('scope')} scope); other servers stay")
    for t in targets:
        if t.exists():
            say(f"  - {doctor._home(str(t))} ({_size(t)})")
    if not a.all and HOME.exists():
        say(f"  Kept: your config and traces in {doctor._home(str(HOME))} (add --all to remove them too)")
    if not reg and not any(t.exists() for t in targets):
        say("  nothing: no engines, data or Claude Code entry found")
    elif ask("Remove these?", a.yes):
        if reg:
            ok, msg = claude_code.unregister(claude)
            say(("Claude Code: " if ok else "Claude Code: FAILED: ") + msg)
        for t in targets:
            shutil.rmtree(t, ignore_errors=True)
            say(f"removed {doctor._home(str(t))}")
    else:
        say("Nothing removed.")
        return 1
    kind = doctor.install_kind()
    say("\nTo remove the program itself: " + {"pipx": "pipx uninstall lean-agent-browser",
                                             "pip": "pip uninstall lean-agent-browser",
                                             "source checkout": "delete this checkout folder"}[kind])
    return 0
