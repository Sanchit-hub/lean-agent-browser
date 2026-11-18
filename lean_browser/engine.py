"""Engine layer: a hardened Obscura process plus a Chromium fallback, behind one interface.

Obscura is the default engine (low memory). Chromium takes over a page when:
  - the page uses a feature Obscura 0.2.6 cannot handle (routing, decided before any action), or
  - something already failed on Obscura (fallback).
See SPEC.md "Engine layer" and spike/FINDINGS.md for the evidence behind each rule.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import platform
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

log = logging.getLogger("lean_browser.engine")

# Release platform names, as in Obscura's archive names (obscura-<platform>.tar.gz).
PLATFORM = {("Darwin", "arm64"): "aarch64-macos", ("Linux", "x86_64"): "x86_64-linux",
            ("Linux", "aarch64"): "aarch64-linux"}.get((platform.system(), platform.machine()))
IS_MAC = platform.system() == "Darwin"

# Pinned, verified Obscura releases: SHA256 of the extracted binaries per platform. The default stays on
# the version that passed the full suite; others can be tried with LEANB_OBSCURA_VERSION=<version>.
OBSCURA_HASHES = {
    "0.2.6": {  # macOS release digest 19faa248…bd0, verified 2026-11-14 (macOS only: rollback version)
        "aarch64-macos": {"obscura": "2690b133d1c46b40473e0de31cea53757b5283f5caa8911f738bbb1ac8db036d",
                          "obscura-worker": "7b2e6e0234283b5a18ed03649adcf66aefe90ef43ed3817241e47b63ad59c5a5"},
    },
    "0.2.7": {  # verified 2026-11-15 (macOS) and 2026-11-16 (Linux) against GitHub's asset digests
        "aarch64-macos": {"obscura": "d09acc26fb1c5b0ea2ef297f55ea2430f765395d8cfd2eda78fcb50458153195",
                          "obscura-worker": "241bc00417865ff34436e16c8c186ff67b1c28b4226f929e2ad556a3f3265c88"},
        "x86_64-linux": {"obscura": "547f9d8a60048983f0e45c310f160d1239575af062af28e4f6755e361f8abcbf",
                         "obscura-worker": "6956274a7e517666386493962866f95a39ace2f71d864ad2e3bac7640145c311"},
        "aarch64-linux": {"obscura": "d94c66b50753992272f83960763cf278a84de62563ba56278aa3a1d4f2f31d6f",
                          "obscura-worker": "1972bd1d77284d343a9d0e2e4e7b80cd655a67dd091c62ed1842309ecbdd645a"},
    },
}
DEFAULT_OBSCURA_VERSION = "0.2.7"  # 0.2.6 kept for rollback on macOS (LEANB_OBSCURA_VERSION=0.2.6)
# SHA256 of the release archive obscura-<platform>.tar.gz per version (from GitHub's asset digests)
OBSCURA_RELEASE_SHA256 = {
    "0.2.6": {"aarch64-macos": "19faa248ac762f466ddb822dbb03ed4f097312d10d1a4d5b2143e6040a9bebd0"},
    "0.2.7": {"aarch64-macos": "fc7e73f23058f18d6d5be983d83b24ba374d12167677657a307a9476c0f5a7c1",
              "x86_64-linux": "11b53d27cd743e00e196e216920e7f3f794cf378e3f1792b8d25d3beabaf9cad",
              "aarch64-linux": "4ee0aeeb38fa8bb2cb004ba104abe1c79f1bdfd02f51672c694e8234a5ae0e5c"},
}
OBSCURA_VERSION = os.environ.get("LEANB_OBSCURA_VERSION", DEFAULT_OBSCURA_VERSION)
if OBSCURA_VERSION not in OBSCURA_HASHES:
    raise RuntimeError(f"unknown LEANB_OBSCURA_VERSION {OBSCURA_VERSION!r}; pinned: {', '.join(OBSCURA_HASHES)}")
OBSCURA_SHA256 = OBSCURA_HASHES[OBSCURA_VERSION].get(PLATFORM or "", {})
_REPO = Path(__file__).resolve().parent.parent
_VENDOR = _REPO / f".vendor/obscura-v{OBSCURA_VERSION}/bin/obscura"
_HOME_BIN = Path.home() / ".lean-browser/bin/obscura"
OBSCURA_SEARCH = [
    Path(os.environ["LEANB_OBSCURA"]) if os.environ.get("LEANB_OBSCURA") else None,
    # ~/.lean-browser holds the default version (install.sh / leanb install); other versions live in .vendor
    _HOME_BIN if OBSCURA_VERSION == DEFAULT_OBSCURA_VERSION else _VENDOR,
    _VENDOR if OBSCURA_VERSION == DEFAULT_OBSCURA_VERSION else None,
]

# Obscura's WebSocket is a stub: it fires onopen at once and never connects, so a page would think it is live.
# On Obscura this init script replaces it with an honest failure (error + close, readyState CLOSED) and marks the
# page, so the routing probe moves pages that open one at load to Chromium, and Session moves the domain after
# an action opens one.
WS_MARK_JS = """(() => { if (!window.WebSocket) return;
  class LeanWebSocket extends EventTarget {
    constructor(url, protocols) { super(); window.__leanWebSocket = true;
      this.url = String(url); this.readyState = 3; this.protocol = ''; this.extensions = ''; this.bufferedAmount = 0;
      this.binaryType = 'blob'; this.onopen = this.onmessage = this.onerror = this.onclose = null;
      setTimeout(() => { const e = new Event('error'); this.onerror && this.onerror(e); this.dispatchEvent(e);
        const c = new Event('close'); c.code = 1006; c.reason = 'WebSocket unsupported on this engine'; c.wasClean = false;
        this.onclose && this.onclose(c); this.dispatchEvent(c); }, 0); }
    send() { throw new DOMException('WebSocket is closed', 'InvalidStateError'); }
    close() {}
  }
  for (const [k, v] of [['CONNECTING', 0], ['OPEN', 1], ['CLOSING', 2], ['CLOSED', 3]]) {
    LeanWebSocket[k] = v; LeanWebSocket.prototype[k] = v; }
  window.WebSocket = LeanWebSocket; })();"""

# JS probe run after navigation on Obscura. Each key maps to a spike-verified failure.
ROUTING_PROBE = """() => {
  const vis = el => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'; };
  const out = [];
  if (document.querySelector('input[type=file]') || document.querySelector('form[enctype="multipart/form-data"]'))
    out.push('file-upload');
  if ([...document.querySelectorAll('[contenteditable]:not([contenteditable=false])')].some(vis))
    out.push('contenteditable');
  const here = location.origin;
  if ([...document.querySelectorAll('iframe[src]')].some(f => { try { return vis(f) && new URL(f.src, location.href).origin !== here; } catch (e) { return false; } }))
    out.push('cross-origin-iframe');
  const frames = [...document.querySelectorAll('iframe')].filter(vis);
  if (frames.some(f => f.hasAttribute('srcdoc'))) out.push('srcdoc-iframe');  // Obscura runs no scripts in srcdoc frames
  if (frames.some(f => { try { return !!(f.contentDocument && f.contentDocument.querySelector('iframe')); } catch (e) { return false; } }))
    out.push('nested-iframe');  // Obscura loads the inner frame but its elements can't be reached
  if (window.__leanWebSocket) out.push('websocket');  // set by WS_MARK_JS
  return out;
}"""


BLOCK_TYPES = {"image", "media", "font"}
# Never block captcha providers: an agent (or a human) may need to see the challenge.
CAPTCHA_HOSTS = ("google.com", "gstatic.com", "recaptcha.net", "hcaptcha.com", "challenges.cloudflare.com")


def _load_blocklist() -> frozenset[str]:
    f = Path(__file__).parent / "blocklist.txt"
    return frozenset(l.strip().lower() for l in f.read_text().splitlines() if l.strip() and not l.startswith("#"))


BLOCKLIST = _load_blocklist()


def _host_matches(host: str, domains) -> bool:
    host = host.lower()
    return any(host == d or host.endswith("." + d) for d in domains)


async def _bounded(coro, seconds: float):
    """Await with a timeout, swallowing errors (used for cleanup that must not hang). Unlike wait_for,
    this does not wait for a cancelled call to finish: Playwright calls against a hung engine can
    ignore cancellation, and waiting for them would hang shutdown anyway."""
    task = asyncio.ensure_future(coro)
    done, _ = await asyncio.wait({task}, timeout=seconds)
    if not done:
        task.cancel()
        task.add_done_callback(lambda t: t.cancelled() or t.exception())  # silence "never retrieved"
        return None
    try:
        return task.result()
    except Exception:
        return None


class EngineError(RuntimeError):
    pass


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_PRIVATE_CACHE: dict[str, bool] = {}


def is_private_host(host: str) -> bool:
    """True for loopback, RFC1918, link-local (incl. cloud metadata), unique-local, unspecified,
    or a hostname that resolves to any of those. Resolution failures count as public (the
    request will fail on its own)."""
    import ipaddress
    host = host.strip("[]").lower()
    if host in _PRIVATE_CACHE:
        return _PRIVATE_CACHE[host]
    if host == "localhost" or host.endswith(".localhost"):
        _PRIVATE_CACHE[host] = True
        return True
    try:
        addrs = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addrs = [ipaddress.ip_address(a[4][0].split("%")[0]) for a in socket.getaddrinfo(host, None)]
        except OSError:
            addrs = []
    def bad(a):
        if getattr(a, "ipv4_mapped", None):
            a = a.ipv4_mapped
        return a.is_private or a.is_loopback or a.is_link_local or a.is_unspecified or a.is_reserved
    res = any(bad(a) for a in addrs)
    _PRIVATE_CACHE[host] = res
    return res


def sandbox_tool() -> str | None:
    """The sandbox Obscura runs under: sandbox-exec on macOS, bubblewrap (bwrap) on Linux. Obscura never
    runs without one; with no sandbox available, Chromium serves every page."""
    if IS_MAC:
        return "/usr/bin/sandbox-exec" if os.access("/usr/bin/sandbox-exec", os.X_OK) else None
    return shutil.which("bwrap")


def find_obscura() -> Path | None:
    if not OBSCURA_SHA256 or not sandbox_tool():
        return None
    for p in OBSCURA_SEARCH:
        if p and p.is_file():
            return p
    return None


def verify_obscura(binary: Path) -> None:
    """Refuse to run a binary whose hash does not match the pinned release."""
    if not OBSCURA_SHA256:
        raise EngineError(f"no pinned Obscura {OBSCURA_VERSION} build for this platform ({PLATFORM or platform.platform()})")
    for name, want in OBSCURA_SHA256.items():
        f = binary.parent / name
        if not f.is_file():
            raise EngineError(f"{f} missing")
        got = _sha256(f)
        if got != want:
            raise EngineError(f"{f.name} hash mismatch: got {got[:16]}…, want {want[:16]}…")


def sandbox_profile(tmpdir: str, bin_dir: str, localhost_only: bool) -> str:
    """macOS sandbox for Obscura: no reads of $HOME (except its own folder), writes only to its
    temp dir, inbound connections only on localhost. Optionally outbound only to localhost."""
    home = str(Path.home())
    net_out = ('(deny network-outbound)\n(allow network-outbound (remote ip "localhost:*"))\n'
               '(allow network-outbound (remote unix-socket))\n') if localhost_only else ""
    return f"""(version 1)
(allow default)
(deny file-write*)
(allow file-write* (subpath "{tmpdir}") (subpath "/private/var/folders") (subpath "/dev"))
(deny file-read* (subpath "{home}"))
(allow file-read* (subpath "{bin_dir}") (subpath "{tmpdir}"))
(deny network-inbound)
(allow network-inbound (local ip "localhost:*"))
{net_out}"""


def bwrap_args(tmpdir: str, bin_dir: str) -> list[str]:
    """Linux sandbox for Obscura (bubblewrap): a fresh mount namespace that sees only system libraries,
    certificates and DNS config read-only, its own binaries read-only and its temp dir read-write. No
    home folder, no other user files. New user, PID, IPC and UTS namespaces; the network is shared so it
    can browse (the private-network block still applies, and its CDP port needs the per-launch token)."""
    a = [sandbox_tool() or "bwrap", "--die-with-parent", "--new-session", "--unshare-all", "--share-net",
         "--ro-bind", "/usr", "/usr", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp"]
    for d in ("/bin", "/sbin", "/lib", "/lib64", "/lib32"):
        if os.path.islink(d):
            a += ["--symlink", os.readlink(d), d]
        elif os.path.isdir(d):
            a += ["--ro-bind", d, d]
    for d in ("/etc/ssl", "/etc/ca-certificates", "/etc/pki", "/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf",
              "/etc/host.conf", "/etc/gai.conf", "/etc/fonts", "/etc/localtime", "/run/systemd/resolve"):
        a += ["--ro-bind-try", d, d]
    return a + ["--ro-bind", bin_dir, bin_dir, "--bind", tmpdir, tmpdir, "--chdir", tmpdir]


@dataclass
class ObscuraProcess:
    """One sandboxed `obscura serve` on 127.0.0.1 with a per-launch bearer token."""
    binary: Path
    allow_private_network: bool = False
    localhost_only: bool = False
    stealth: bool = False
    proxy: str | None = None  # netguard URL: every connection is checked at connect time
    port: int = field(default_factory=_free_port)
    token: str = field(default_factory=lambda: secrets.token_hex(32))
    proc: subprocess.Popen | None = None
    tmp: str = ""

    @property
    def endpoint(self) -> str:
        return f"ws://127.0.0.1:{self.port}"

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def start(self, timeout: float = 15) -> None:
        verify_obscura(self.binary)
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="leanb-obscura-"))
        bin_dir = str(self.binary.parent.resolve())
        if IS_MAC:
            prof = Path(self.tmp) / "sandbox.sb"
            prof.write_text(sandbox_profile(self.tmp, bin_dir, self.localhost_only))
            jail = ["/usr/bin/sandbox-exec", "-f", str(prof)]
        else:
            if self.localhost_only:  # bubblewrap can't limit outbound traffic to localhost
                raise EngineError("localhost_only is only enforced on macOS")
            if not sandbox_tool():
                raise EngineError("bubblewrap (bwrap) is needed to sandbox Obscura on Linux")
            jail = bwrap_args(self.tmp, bin_dir)
        ready = Path(self.tmp) / "ready"
        # A tiny sh supervisor inside the sandbox kills Obscura when the Python process that started it
        # goes away (even after SIGKILL), so a crashed or killed client never leaves an orphaned engine.
        watchdog = ('"$@" & c=$!; trap \'kill $c 2>/dev/null; exit 0\' TERM INT HUP; '
                    'while kill -0 "$P" 2>/dev/null && kill -0 $c 2>/dev/null; do sleep 1; done; kill $c 2>/dev/null; wait $c')
        # On Linux, bwrap --die-with-parent plus its own PID namespace does the same job: when the client dies,
        # bwrap dies, and every process in the namespace goes with it.
        sup = ["/bin/sh", "-c", watchdog, "sh"] if IS_MAC else []
        args = [*jail, *sup, str(self.binary), "serve",
                "--host", "127.0.0.1", "--port", str(self.port), "--ready-file", str(ready), "--quiet"]
        if self.allow_private_network:
            args.append("--allow-private-network")
        if self.stealth:
            args.append("--stealth")
        if self.proxy:
            args += ["--proxy", self.proxy]
        env = {"PATH": "/usr/bin:/bin", "HOME": self.tmp, "TMPDIR": self.tmp, "OBSCURA_CDP_TOKEN": self.token,
               "P": str(os.getpid())}
        self.proc = subprocess.Popen(args, env=env, cwd=self.tmp, stdin=subprocess.DEVNULL,
                                     stdout=open(Path(self.tmp) / "obscura.log", "w"), stderr=subprocess.STDOUT)
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.proc.poll() is not None:
                raise EngineError(f"obscura exited early ({self.proc.returncode}): {self.log_tail()}")
            if ready.exists() and ready.read_text().strip():
                return
            time.sleep(0.05)
        self.stop()
        raise EngineError("obscura did not become ready in time")

    def log_tail(self, n: int = 1500) -> str:
        f = Path(self.tmp) / "obscura.log"
        return f.read_text()[-n:] if f.exists() else ""

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)


@dataclass
class Tab:
    """A page plus the engine currently serving it."""
    page: Page
    engine: str
    reason: str = ""

    @property
    def header(self) -> str:
        return f"engine: {self.engine}" + (f" ({self.reason})" if self.reason else "")


class BrowserManager:
    """Owns both engines and decides which one serves each page.

    Usage:
        async with BrowserManager() as bm:
            tab = await bm.open("https://example.com")
    """

    def __init__(self, *, prefer: str = "obscura", allow_private_network: bool = False,
                 localhost_only: bool = False, nav_timeout_ms: int = 20000,
                 viewport: dict | None = None, fallback_domains: list[str] | None = None,
                 init_scripts: list[str] | None = None, obscura_init_scripts: list[str] | None = None,
                 block: bool = True):
        self.prefer = prefer
        self.allow_private_network = allow_private_network
        self.localhost_only = localhost_only
        self.nav_timeout_ms = nav_timeout_ms
        self.viewport = viewport or {"width": 1280, "height": 800}
        self.fallback_domains = set(fallback_domains or [])
        self.init_scripts = list(init_scripts or [])
        self.obscura_init_scripts = list(obscura_init_scripts or [])
        self.block = block  # images/media/fonts + tracker hosts (Chromium only)
        self.blocked_count = 0
        self.domain_engine: dict[str, tuple[str, str]] = {}  # host -> (engine, reason), sticky per session
        self.events: list[str] = []
        self._pw: Playwright | None = None
        self._obscura: ObscuraProcess | None = None
        self._obscura_browser: Browser | None = None
        self._obscura_ctx: BrowserContext | None = None
        self._obscura_broken: str = ""
        self._chromium: Browser | None = None
        self._chromium_ctx: BrowserContext | None = None
        self.chromium_sandboxed: bool | None = None  # None until Chromium launches; False = runs without its OS sandbox
        self.chromium_sandbox_note = ""  # why the OS sandbox is off, when it is
        self._guard = None  # netguard.NetGuard: connect-time private-network check for Chromium

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def start(self):
        self._pw = await async_playwright().start()

    async def close(self):
        # Every close is time-boxed: a page stuck in a script must never hang shutdown.
        for c in (self._obscura_ctx, self._chromium_ctx, self._obscura_browser, self._chromium):
            if c:
                await _bounded(c.close(), 5)
        if self._obscura:
            self._obscura.stop()
        if self._pw:
            await _bounded(self._pw.stop(), 10)
        if self._guard:
            await self._guard.close()
            self._guard = None

    async def reset_obscura(self, reason: str):
        """Throw away a hung Obscura process (its script thread is stuck); the next page starts a fresh one."""
        self._note(f"restarting obscura: {reason}")
        for c in (self._obscura_ctx, self._obscura_browser):
            if c:
                await _bounded(c.close(), 2)
        if self._obscura:
            self._obscura.stop()
        self._obscura = self._obscura_browser = self._obscura_ctx = None

    async def _ensure_guard(self) -> str | None:
        """Start the connect-time private-network guard once (both engines use it). None when private network is
        allowed, when Obscura is limited to localhost anyway, or when the user's proxy can't be chained (socks)."""
        if self.allow_private_network or self.localhost_only:
            return None
        if self._guard:
            return self._guard.url
        from lean_browser.netguard import NetGuard, env_has_proxy, env_upstreams
        http_up = tunnel_up = None
        if env_has_proxy():
            try:
                http_up, tunnel_up = env_upstreams()
            except ValueError as e:
                if not getattr(self, "_proxy_noted", False):
                    self._proxy_noted = True
                    self._note(f"{e}; the connect-time private-network guard is off, request-level checks "
                               "still apply, redirect hops are not checked")
                return None
            if not getattr(self, "_proxy_noted", False):
                self._proxy_noted = True
                self._note("using your HTTP(S)_PROXY behind the private-network guard")
        self._guard = await NetGuard(lambda h: self._note(f"blocked private-network connection to {h}"),
                                     http_upstream=http_up, tunnel_upstream=tunnel_up).start()
        return self._guard.url

    # ---------- engines ----------
    def _note(self, msg: str):
        log.info(msg)
        self.events.append(msg)

    async def _obscura_context(self) -> BrowserContext:
        if self._obscura_ctx:
            return self._obscura_ctx
        if self._obscura_broken:
            raise EngineError(self._obscura_broken)
        binary = find_obscura()
        if not binary:
            self._obscura_broken = "obscura binary not found (run install.sh)"
            raise EngineError(self._obscura_broken)
        try:
            self._obscura = ObscuraProcess(binary, allow_private_network=self.allow_private_network,
                                           localhost_only=self.localhost_only, proxy=await self._ensure_guard())
            await asyncio.to_thread(self._obscura.start)
            self._obscura_browser = await self._pw.chromium.connect_over_cdp(
                self._obscura.endpoint, headers=self._obscura.headers, timeout=15000)
            self._obscura_ctx = await self._obscura_browser.new_context(viewport=self.viewport)
            for js in [WS_MARK_JS] + self.init_scripts + self.obscura_init_scripts:
                await self._obscura_ctx.add_init_script(js)
        except Exception as e:
            self._obscura_broken = f"obscura unavailable: {e}"
            if self._obscura:
                self._obscura.stop()
            raise EngineError(self._obscura_broken) from e
        return self._obscura_ctx

    async def _chromium_context(self) -> BrowserContext:
        if not self._chromium_ctx:
            args = ["--disable-extensions", "--disable-sync", "--disable-background-networking", "--no-first-run"]
            # Request routing only sees the first URL of a redirect chain, so every connection also goes through
            # a local proxy that checks the resolved address at connect time (redirect hops, DNS rebinding,
            # subresources, WebSockets). <-loopback> stops Chromium skipping the proxy for localhost.
            guard = await self._ensure_guard()
            if guard:
                args += [f"--proxy-server={guard}", "--proxy-bypass-list=<-loopback>"]
            # Chromium's own OS sandbox (seatbelt on macOS, user namespaces on Linux) when it starts; containers and
            # hosts that restrict unprivileged user namespaces can't run it, so fall back and say why.
            # LEANB_CHROMIUM_SANDBOX=0 forces it off.
            self.chromium_sandboxed = None
            if os.environ.get("LEANB_CHROMIUM_SANDBOX", "").strip().lower() in ("0", "false", "no", "off"):
                why = "turned off by LEANB_CHROMIUM_SANDBOX=0"
            else:
                why = ""
                try:
                    self._chromium = await self._pw.chromium.launch(headless=True, args=args, chromium_sandbox=True)
                    self.chromium_sandboxed, self.chromium_sandbox_note = True, ""
                except Exception as e:  # noqa: BLE001 - any launch failure: retry without the sandbox
                    first = next((l.strip() for l in str(e).splitlines() if l.strip()), type(e).__name__)
                    why = f"sandboxed launch failed: {type(e).__name__}: {first[:200]}"
            if not self.chromium_sandboxed:
                self._chromium = await self._pw.chromium.launch(headless=True, args=args, chromium_sandbox=False)
                self.chromium_sandboxed = False
                self.chromium_sandbox_note = why
                self._note(f"chromium OS sandbox unavailable ({why}); running without it")
            self._chromium_ctx = await self._chromium.new_context(viewport=self.viewport)
            for js in self.init_scripts:
                await self._chromium_ctx.add_init_script(js)
            await self._chromium_ctx.route("**/*", self._route)
        return self._chromium_ctx

    async def _route(self, route):
        req = route.request
        url = req.url
        if not url.startswith(("http://", "https://", "ws://", "wss://")):
            return await route.continue_()
        host = urlparse(url).hostname or ""
        # Same SSRF policy as Obscura, so falling back never widens network access.
        if not self.allow_private_network and await asyncio.to_thread(is_private_host, host):
            self._note(f"blocked private-network request to {host}")
            return await route.abort("blockedbyclient")
        if self.block and req.resource_type != "document" and not _host_matches(host, CAPTCHA_HOSTS):
            if req.resource_type in BLOCK_TYPES or _host_matches(host, BLOCKLIST):
                self.blocked_count += 1
                return await route.abort("blockedbyclient")
        await route.continue_()

    async def _carry_state(self, src: BrowserContext | None, dst: BrowserContext):
        """Copy cookies (and same-origin localStorage) from one engine's context to the other."""
        if not src:
            return
        try:
            st = await src.storage_state()
        except Exception as e:
            self._note(f"could not read storage state for carry-over: {e}")
            return
        if st.get("cookies"):
            await dst.add_cookies(st["cookies"])
        origins = st.get("origins") or []
        if origins:
            script = "(() => { const o = %s; const e = o.find(x => x.origin === location.origin); " \
                     "if (e) for (const kv of e.localStorage) try { localStorage.setItem(kv.name, kv.value); } catch (_) {} })()"
            import json
            await dst.add_init_script(script % json.dumps(origins))

    # ---------- public API ----------
    async def open(self, url: str) -> Tab:
        host = urlparse(url).hostname or ""
        if host in self.fallback_domains:
            self.domain_engine.setdefault(host, ("chromium", "fallback_domains"))
        engine, reason = self.domain_engine.get(host, (self.prefer, ""))
        if engine == "obscura":
            try:
                ctx = await self._obscura_context()
            except EngineError as e:
                return await self._open_chromium(url, reason=str(e), carry_from=None)
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="load", timeout=self.nav_timeout_ms)
            except Exception as e:
                await page.close()
                return await self._open_chromium(url, reason=f"navigation failed on obscura: {type(e).__name__}",
                                                 carry_from=ctx, host=host)
            try:
                needs = await asyncio.wait_for(page.evaluate(ROUTING_PROBE), 5)
            except Exception as e:
                needs = [f"probe failed: {type(e).__name__}"]
            if needs:
                await _bounded(page.close(), 3)
                return await self._open_chromium(url, reason="routed: " + ", ".join(needs), carry_from=ctx, host=host)
            return Tab(page, "obscura", reason)
        return await self._open_chromium(url, reason=reason, carry_from=self._obscura_ctx)

    async def _open_chromium(self, url: str, *, reason: str, carry_from: BrowserContext | None,
                             host: str | None = None) -> Tab:
        ctx = await self._chromium_context()
        await self._carry_state(carry_from, ctx)
        if host and not reason.startswith("routed"):
            self.domain_engine[host] = ("chromium", reason)  # failures stick for the session
        if reason:
            self._note(f"{url} -> chromium ({reason})")
        page = await ctx.new_page()
        await page.goto(url, wait_until="load", timeout=self.nav_timeout_ms)
        return Tab(page, "chromium", reason)

    async def navigate(self, tab: Tab, url: str) -> Tab:
        """Navigate an existing tab, keeping its history when the engine stays the same."""
        host = urlparse(url).hostname or ""
        if host in self.fallback_domains:
            self.domain_engine.setdefault(host, ("chromium", "fallback_domains"))
        want, reason = self.domain_engine.get(host, (self.prefer, ""))
        if want == "obscura" and self._obscura_broken:
            want = "chromium"
        if tab.engine == "chromium" and want == "chromium":
            await tab.page.goto(url, wait_until="load", timeout=self.nav_timeout_ms)
            return Tab(tab.page, "chromium", reason)
        if tab.engine == "obscura" and want == "obscura":
            try:
                await tab.page.goto(url, wait_until="load", timeout=self.nav_timeout_ms)
            except Exception as e:
                ctx = tab.page.context
                await tab.page.close()
                return await self._open_chromium(url, reason=f"navigation failed on obscura: {type(e).__name__}",
                                                 carry_from=ctx, host=host)
            try:
                needs = await asyncio.wait_for(tab.page.evaluate(ROUTING_PROBE), 5)
            except Exception as e:
                needs = [f"probe failed: {type(e).__name__}"]
            if needs:
                ctx = tab.page.context
                await _bounded(tab.page.close(), 3)
                return await self._open_chromium(url, reason="routed: " + ", ".join(needs), carry_from=ctx, host=host)
            return Tab(tab.page, "obscura", "")
        # engine changes: a new page in the other engine (history does not carry over)
        old = tab.page
        new = await self.open(url)
        try:
            await old.close()
        except Exception:
            pass
        return new

    async def switch_to_chromium(self, tab: Tab, reason: str) -> Tab:
        """Move a live Obscura tab to Chromium (e.g. snapshot too slow, popup needed). State that
        lives only in the page (unsaved form input) is lost, so callers do this before acting."""
        if tab.engine == "chromium":
            return tab
        url = tab.page.url
        src = tab.page.context
        # Cookies first (the context may be wedged afterwards), then drop the page; a hung engine is reset.
        carry = None
        try:
            carry = await asyncio.wait_for(src.storage_state(), 3)
        except Exception:
            pass
        await _bounded(tab.page.close(), 3)
        if "unresponsive" in reason or "too slow" in reason:
            await self.reset_obscura(reason)
        host = urlparse(url).hostname or ""
        self.domain_engine[host] = ("chromium", reason)
        ctx = await self._chromium_context()
        if carry and carry.get("cookies"):
            await _bounded(ctx.add_cookies(carry["cookies"]), 3)
        return await self._open_chromium(url, reason=reason, carry_from=None)

    def obscura_rss_mb(self) -> float | None:
        if not (self._obscura and self._obscura.proc):
            return None
        out = subprocess.run(["ps", "-axo", "pid=,ppid=,rss="], capture_output=True, text=True).stdout
        kids, rss = {}, {}
        for line in out.splitlines():
            p, pp, r = map(int, line.split())
            kids.setdefault(pp, []).append(p)
            rss[p] = r
        total, stack = 0, [self._obscura.proc.pid]
        while stack:
            p = stack.pop()
            total += rss.get(p, 0)
            stack += kids.get(p, [])
        return round(total / 1024, 1)
