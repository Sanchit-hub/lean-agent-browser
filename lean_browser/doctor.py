"""`leanb doctor`: check the install, from the package to a real MCP round trip.

Each check ends as PASS, WARN, FAIL or NOT SUPPORTED. FAIL means something advertised does not work;
WARN means it works with a reduced capability or a missing optional piece. `--json` prints the same
result with home-folder paths shortened to `~`, so it can be pasted into a bug report.
"""
from __future__ import annotations

import asyncio
import importlib.metadata as md
import json
import os
import platform
import shutil
import sys
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

import lean_browser
from lean_browser import claude_code

PASS, WARN, FAIL, UNSUPPORTED = "PASS", "WARN", "FAIL", "NOT SUPPORTED"
# Platforms that pass the full test suite and the clean-install test in CI.
SUPPORTED = {"aarch64-macos": "macOS on Apple Silicon", "x86_64-linux": "Linux x86_64", "aarch64-linux": "Linux arm64"}
EXPECTED_TOOLS = ["act", "extract", "fill_form", "memory", "open", "screenshot", "snapshot"]
TEST_PAGE = "data:text/html,<title>leanb doctor</title><main><h1>Doctor</h1><button>Ping</button></main>"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


def _home(s: str) -> str:
    """Shorten the home folder to ~ (also its resolved form, e.g. /private/tmp/... for /tmp/...)."""
    for h in sorted({str(Path.home().resolve()), str(Path.home())}, key=len, reverse=True):
        if h and h != "/":
            s = s.replace(h, "~")
    return s


def install_kind() -> str:
    root = Path(lean_browser.__file__).resolve().parent.parent
    if (root / ".git").exists() and (root / "pyproject.toml").exists():
        return "source checkout"
    if (Path(sys.prefix) / "pipx_metadata.json").is_file():  # pipx writes this into every venv it manages
        return "pipx"
    return "pip"


def check_package() -> Check:
    path = Path(lean_browser.__file__).resolve().parent
    return Check("package", PASS, f"lean-agent-browser {lean_browser.__version__} ({install_kind()}) at {path}")


def check_platform() -> Check:
    from lean_browser.engine import PLATFORM
    name = f"{platform.system()} {platform.machine()}"
    if PLATFORM in SUPPORTED:
        return Check("platform", PASS, f"{SUPPORTED[PLATFORM]} (tested in CI)")
    return Check("platform", UNSUPPORTED, f"{name} is not tested. Chromium alone may work, but nothing is promised.",
                 "Supported: macOS on Apple Silicon, Linux x86_64 and arm64.")


def check_python() -> Check:
    v = sys.version_info
    deps = []
    for d in ("playwright", "mcp"):
        try:
            deps.append(f"{d} {md.version(d)}")
        except md.PackageNotFoundError:
            return Check("python", FAIL, f"dependency {d} is missing", "Reinstall lean-agent-browser.")
    if v < (3, 12):
        return Check("python", FAIL, f"Python {v.major}.{v.minor}; 3.12 or later is required", "Install Python 3.12+.")
    return Check("python", PASS, f"Python {v.major}.{v.minor}.{v.micro}, " + ", ".join(deps))


def check_config(path: str | None = None) -> Check:
    from lean_browser.tools import Config
    p = Path(path or "~/.lean-browser/config.toml").expanduser()
    if not p.is_file():
        return Check("config", PASS, "no config file; using safe defaults (private network blocked)")
    try:
        data = tomllib.loads(p.read_text())
    except (tomllib.TOMLDecodeError, OSError) as e:
        return Check("config", FAIL, f"{p} is not valid TOML: {e}", f"Fix or delete {p}.")
    unknown = sorted(set(data) - set(Config.__dataclass_fields__))
    if unknown:
        return Check("config", WARN, f"{p}: unknown keys ignored: {', '.join(unknown)}", "Check the key names in the README's Config section.")
    if data.get("allow_private_network"):
        return Check("config", WARN, f"{p}: allow_private_network = true (localhost and LAN pages are reachable)",
                     "Set it back to false unless you are testing a local app.")
    return Check("config", PASS, f"{p} is valid")


def check_sandbox() -> Check:
    from lean_browser.engine import IS_MAC, OBSCURA_SHA256, sandbox_tool
    if not OBSCURA_SHA256:
        return Check("sandbox", UNSUPPORTED, "no Obscura build for this platform, so no Obscura sandbox is needed")
    tool = sandbox_tool()
    if tool:
        return Check("sandbox", PASS, f"{'sandbox-exec' if IS_MAC else 'bubblewrap'} found ({tool})")
    return Check("sandbox", WARN, "bubblewrap not found: Obscura is disabled and Chromium serves every page",
                 "sudo apt install bubblewrap (Ubuntu 24.04 also needs unprivileged user namespaces allowed).")


async def check_obscura() -> Check:
    from lean_browser.engine import (OBSCURA_SHA256, OBSCURA_VERSION, EngineError, ObscuraProcess, find_obscura,
                                     sandbox_tool, verify_obscura)
    if not OBSCURA_SHA256:
        return Check("obscura", UNSUPPORTED, "no pinned Obscura build for this platform; Chromium serves every page")
    if not sandbox_tool():
        return Check("obscura", WARN, f"Obscura {OBSCURA_VERSION} not used: it only runs sandboxed", "Install bubblewrap.")
    b = find_obscura()
    if not b:
        return Check("obscura", WARN, f"Obscura {OBSCURA_VERSION} is not installed; Chromium serves every page", "leanb install")
    try:
        verify_obscura(b)
        p = ObscuraProcess(b)
        await asyncio.to_thread(p.start)
        p.stop()
    except EngineError as e:
        return Check("obscura", FAIL, str(e), "leanb install (re-downloads and re-checks the pinned build)")
    return Check("obscura", PASS, f"Obscura {OBSCURA_VERSION} at {b}: hashes match the pin, starts sandboxed on 127.0.0.1")


async def check_engine(prefer: str) -> Check:
    from lean_browser.engine import IS_MAC, BrowserManager
    try:
        async with BrowserManager(prefer=prefer) as bm:
            tab = await bm.open(TEST_PAGE)
            title = await tab.page.title()
            if prefer == "obscura" and tab.engine != "obscura":
                return Check("obscura page", FAIL, f"fell back to {tab.engine}: {tab.reason}")
    except Exception as e:  # noqa: BLE001 - report any launch failure
        msg = str(e).splitlines()[0][:200] if str(e) else type(e).__name__
        fix = "leanb install"
        if prefer == "chromium" and not IS_MAC:
            fix += f"; if Chromium's system libraries are missing: sudo {sys.executable} -m playwright install-deps chromium"
        return Check(f"{prefer} page", FAIL, f"{type(e).__name__}: {msg}", fix)
    return Check(f"{prefer} page", PASS, f"loaded a test page (title {title!r})")


async def check_mcp(timeout: float = 90) -> Check:
    """Start the MCP server exactly as a client would, list its tools and open a page through it."""
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    cmd = claude_code.leanb_command()

    async def run():
        params = StdioServerParameters(command=cmd[0], args=[*cmd[1:], "mcp"], cwd=str(Path.home()))
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            names = sorted(t.name for t in (await s.list_tools()).tools)
            if names != EXPECTED_TOOLS:
                return Check("mcp", FAIL, f"unexpected tools: {names}", "Reinstall lean-agent-browser.")
            out = (await s.call_tool("open", {"url": TEST_PAGE})).content[0].text
            if 'button "Ping"' not in out:
                return Check("mcp", FAIL, "open() through MCP did not return the test page: " + out[:200])
            return Check("mcp", PASS, f"{' '.join(cmd)} mcp: handshake, {len(names)} tools, open() returned a snapshot")

    try:
        return await asyncio.wait_for(run(), timeout)
    except Exception as e:  # noqa: BLE001
        return Check("mcp", FAIL, f"the MCP server did not start or answer: {type(e).__name__}: {str(e)[:200]}",
                     f"Run `{' '.join(cmd)} mcp` by hand to see the error.")


def check_claude() -> Check:
    claude = claude_code.find_claude()
    if not claude:
        return Check("claude code", WARN, "Claude Code CLI not found (only needed to use Lean from Claude Code)",
                     "Install Claude Code, then run: leanb setup --client claude")
    reg = claude_code.get_registration(claude)
    if reg is None:
        return Check("claude code", WARN, f"{claude}: no '{claude_code.NAME}' MCP server registered here",
                     "leanb setup --client claude")
    cmd = reg.get("command", "")
    if not cmd or not (Path(cmd).exists() or shutil.which(cmd)):
        return Check("claude code", FAIL, f"'{claude_code.NAME}' points to {cmd or '(nothing)'}, which does not exist",
                     "leanb setup --client claude (updates the registration)")
    want = claude_code.leanb_command()
    note = "" if [cmd, *reg.get("args", [])] == [*want, "mcp"] else f" (a different leanb than this one: {want[0]})"
    return Check("claude code", PASS, f"'{claude_code.NAME}' registered ({reg.get('scope', '?')} scope): {cmd} {' '.join(reg.get('args', []))}{note}")


async def run_checks(config: str | None = None, claude: bool = True, mcp: bool = True) -> list[Check]:
    from lean_browser.engine import find_obscura, sandbox_tool
    checks = [check_package(), check_platform(), check_python(), check_config(config), check_sandbox()]
    checks.append(await check_obscura())
    if find_obscura() and sandbox_tool() and checks[-1].status == PASS:
        checks.append(await check_engine("obscura"))
    checks.append(await check_engine("chromium"))
    if mcp:
        checks.append(await check_mcp())
    if claude:
        checks.append(await asyncio.to_thread(check_claude))
    return checks


def summary(checks: list[Check]) -> tuple[bool, str]:
    n = {s: sum(c.status == s for c in checks) for s in (PASS, WARN, FAIL, UNSUPPORTED)}
    ok = n[FAIL] == 0
    parts = [f"{n[PASS]} passed"] + [f"{n[s]} {label}" for s, label in
                                     ((WARN, "warning"), (FAIL, "failed"), (UNSUPPORTED, "not supported")) if n[s]]
    plural = ", ".join(p + ("s" if p.endswith("warning") and not p.startswith("1 ") else "") for p in parts)
    return ok, ("all good: " if ok else "problems found: ") + plural


def render(checks: list[Check]) -> str:
    lines = []
    for c in checks:
        lines.append(f"{c.status:<13} {c.name:<13} {_home(c.detail)}")
        if c.fix and c.status != PASS:
            lines.append(f"{'':<13} {'':<13} fix: {_home(c.fix)}")
    return "\n".join(lines)


def to_json(checks: list[Check]) -> str:
    from lean_browser.engine import OBSCURA_VERSION
    ok, text = summary(checks)
    return json.dumps({
        "version": lean_browser.__version__, "install": install_kind(), "os": platform.platform(),
        "machine": platform.machine(), "python": platform.python_version(), "obscura_pin": OBSCURA_VERSION,
        "ok": ok, "summary": text,
        "checks": [{k: _home(v) for k, v in asdict(c).items()} for c in checks],
        "env": {k: _home(os.environ[k]) for k in ("PLAYWRIGHT_BROWSERS_PATH", "LEANB_OBSCURA", "LEANB_OBSCURA_VERSION") if k in os.environ},
    }, indent=2)


async def main(config: str | None = None, as_json: bool = False, claude: bool = True, mcp: bool = True) -> int:
    checks = await run_checks(config, claude=claude, mcp=mcp)
    ok, text = summary(checks)
    print(to_json(checks) if as_json else render(checks) + "\n" + text)
    return 0 if ok else 1
