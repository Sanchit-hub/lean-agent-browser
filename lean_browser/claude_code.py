"""Register Lean Agent Browser with Claude Code, through Claude Code's own `claude mcp` commands.

Lean never edits Claude Code's config files itself: `claude mcp add-json / get / remove` do the
writing, so other MCP servers are left alone. Only the entry named `lean-browser` is touched.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

NAME = "lean-browser"
SCOPES = {"User config": "user", "Local config": "local", "Project config": "project"}


def find_claude() -> str | None:
    return os.environ.get("LEANB_CLAUDE") or shutil.which("claude")


def leanb_command() -> list[str]:
    """The absolute command that starts this installation of leanb (the one running now)."""
    for cand in (Path(sys.executable).parent / "leanb", Path(sys.argv[0]) if Path(sys.argv[0]).name == "leanb" else None):
        if cand and cand.is_file() and os.access(cand, os.X_OK):
            return [str(cand.absolute())]
    found = shutil.which("leanb")
    if found:
        return [str(Path(found).absolute())]
    return [str(Path(sys.executable).absolute()), "-m", "lean_browser.cli"]


def _run(claude: str, *args: str, timeout: float = 90) -> subprocess.CompletedProcess:
    return subprocess.run([claude, "mcp", *args], capture_output=True, text=True, timeout=timeout, cwd=Path.home())


def get_registration(claude: str) -> dict | None:
    """{'scope', 'status', 'command', 'args'} for the lean-browser entry visible from the home folder, or None."""
    try:
        r = _run(claude, "get", NAME)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    reg: dict = {"args": []}
    for line in r.stdout.splitlines():
        key, _, val = line.strip().partition(":")
        val = val.strip()
        if key == "Scope":
            reg["scope"] = next((v for k, v in SCOPES.items() if val.startswith(k)), val)
        elif key == "Status":
            reg["status"] = val
        elif key == "Command":
            reg["command"] = val
        elif key == "Args":
            reg["args"] = val.split() if val else []
    return reg


def proposed(scope: str = "user") -> tuple[dict, list[str]]:
    cmd = leanb_command()
    entry = {"type": "stdio", "command": cmd[0], "args": [*cmd[1:], "mcp"], "env": {}}
    return entry, ["claude", "mcp", "add-json", "-s", scope, NAME, json.dumps(entry)]


def register(claude: str, scope: str = "user") -> tuple[bool, str]:
    """Add (or replace) the lean-browser entry. Returns (ok, message)."""
    entry, _ = proposed(scope)
    old = get_registration(claude)
    if old and old.get("command") == entry["command"] and old.get("args") == entry["args"] and old.get("scope") == scope:
        return True, f"already registered ({scope} scope), nothing to change"
    if old:
        r = _run(claude, "remove", NAME, "-s", old.get("scope", scope))
        if r.returncode != 0:
            return False, f"could not remove the old entry: {(r.stderr or r.stdout).strip()}"
    r = _run(claude, "add-json", "-s", scope, NAME, json.dumps(entry))
    if r.returncode != 0:
        return False, f"claude mcp add-json failed: {(r.stderr or r.stdout).strip()}"
    return True, ("updated" if old else "added") + f" '{NAME}' ({scope} scope): {entry['command']} {' '.join(entry['args'])}"


def unregister(claude: str) -> tuple[bool, str]:
    old = get_registration(claude)
    if not old:
        return True, f"no '{NAME}' entry registered"
    r = _run(claude, "remove", NAME, "-s", old.get("scope", "user"))
    if r.returncode != 0:
        return False, (r.stderr or r.stdout).strip()
    return True, f"removed '{NAME}' ({old.get('scope')} scope); other MCP servers were not touched"
