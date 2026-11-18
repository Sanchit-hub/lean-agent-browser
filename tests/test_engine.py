"""Engine layer: hardened Obscura launch, feature routing, fallback, and state carry-over.
Runs against the local fixture site. Obscura tests are skipped if the binary is not installed."""
import asyncio
import shutil
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from evals.fixtures.server import serve
from lean_browser import engine as eng
from lean_browser.engine import BrowserManager, EngineError, ObscuraProcess, find_obscura
from tests.test_fixtures import _free_port

needs_obscura = pytest.mark.skipif(find_obscura() is None, reason="obscura not installed")


@pytest.fixture(scope="module")
def base():
    port = _free_port()
    srv = serve(port)
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


@needs_obscura
def test_obscura_binds_localhost_with_token_and_sandbox():
    p = ObscuraProcess(find_obscura())
    p.start()
    try:
        import subprocess
        # p.proc is the sandbox wrapper; look up whoever listens on the port instead.
        if eng.IS_MAC:
            out = subprocess.run(["lsof", "-nP", f"-iTCP:{p.port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout
            assert f"127.0.0.1:{p.port}" in out and "*:" not in out, out
        else:
            out = subprocess.run(["ss", "-ltnH", f"sport = :{p.port}"], capture_output=True, text=True).stdout
            local = [l.split()[3] for l in out.splitlines() if l.strip()]  # State Recv-Q Send-Q Local Peer
            assert local and all(a == f"127.0.0.1:{p.port}" for a in local), out
        # no token -> refused
        import urllib.error
        import urllib.request
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"http://127.0.0.1:{p.port}/json/version", timeout=3)
        assert e.value.code in (401, 403)
        req = urllib.request.Request(f"http://127.0.0.1:{p.port}/json/version", headers=p.headers)
        assert urllib.request.urlopen(req, timeout=3).status == 200
        assert p.tmp and Path(p.tmp).exists()
    finally:
        p.stop()
    assert p.proc.poll() is not None
    assert not Path(p.tmp).exists(), "temp dir not cleaned up"


@needs_obscura
def test_tampered_binary_is_refused(tmp_path):
    src = find_obscura().parent
    for name in ("obscura", "obscura-worker"):
        shutil.copy(src / name, tmp_path / name)
    with open(tmp_path / "obscura", "ab") as f:
        f.write(b"\0")
    with pytest.raises(EngineError, match="hash mismatch"):
        eng.verify_obscura(tmp_path / "obscura")


@needs_obscura
async def test_simple_page_stays_on_obscura(base):
    async with BrowserManager(allow_private_network=True) as bm:
        tab = await bm.open(base + "/login.html")
        assert tab.engine == "obscura", bm.events
        assert await tab.page.title() == "Log in"
        rss = bm.obscura_rss_mb()
        assert rss and rss < 400


@needs_obscura
@pytest.mark.parametrize("path,why", [
    ("/apply.html", "file-upload"),
    ("/comment.html", "contenteditable"),
    ("/xframe.html", "cross-origin-iframe"),
    ("/live.html", "websocket"),  # Obscura's WebSocket is a stub that fakes onopen
])
async def test_feature_routing_to_chromium(base, path, why):
    async with BrowserManager(allow_private_network=True) as bm:
        tab = await bm.open(base + path)
        assert tab.engine == "chromium"
        assert why in tab.reason
        # routing is per page, not per domain: a simple page on the same host stays on obscura
        tab2 = await bm.open(base + "/login.html")
        assert tab2.engine == "obscura"


@needs_obscura
async def test_state_carries_over_on_switch(base):
    async with BrowserManager(allow_private_network=True) as bm:
        t1 = await bm.open(base + "/cookie-set.html")
        assert t1.engine == "obscura"
        t2 = await bm.open(base + "/apply.html")  # routed to chromium
        assert t2.engine == "chromium"
        cookies = await t2.page.context.cookies()
        assert any(c["name"] == "carry" and c["value"] == "yes-from-obscura" for c in cookies)


@needs_obscura
async def test_switch_to_chromium_sticks_for_domain(base):
    async with BrowserManager(allow_private_network=True) as bm:
        t = await bm.open(base + "/login.html")
        t2 = await bm.switch_to_chromium(t, "snapshot too slow")
        assert t2.engine == "chromium" and t2.page.url.endswith("/login.html")
        t3 = await bm.open(base + "/signup.html")
        assert t3.engine == "chromium" and "snapshot too slow" in t3.reason


async def test_missing_obscura_falls_back(base, monkeypatch):
    monkeypatch.setattr(eng, "find_obscura", lambda: None)
    async with BrowserManager(allow_private_network=True) as bm:
        tab = await bm.open(base + "/login.html")
        assert tab.engine == "chromium" and "not found" in tab.reason


async def test_private_network_blocked_on_both_engines(base):
    # Without opt-in, Obscura's SSRF guard refuses localhost, and the Chromium fallback must refuse it
    # too, so a fallback never widens network access.
    async with BrowserManager() as bm:
        with pytest.raises(Exception, match="ERR_BLOCKED_BY_CLIENT"):
            await bm.open(base + "/login.html")
        assert any("blocked private-network" in e for e in bm.events), bm.events


@pytest.mark.parametrize("host,private", [
    ("127.0.0.1", True), ("localhost", True), ("10.1.2.3", True), ("192.168.1.1", True),
    ("169.254.169.254", True), ("::1", True), ("0.0.0.0", True), ("api.localhost", True),
    ("::ffff:127.0.0.1", True), ("::ffff:10.0.0.1", True), ("fd00::1", True),
    ("8.8.8.8", False), ("1.1.1.1", False),
])
def test_is_private_host(host, private):
    assert eng.is_private_host(host) is private


async def test_fallback_domains(base):
    async with BrowserManager(allow_private_network=True, fallback_domains=["127.0.0.1"]) as bm:
        tab = await bm.open(base + "/login.html")
        assert tab.engine == "chromium" and tab.reason == "fallback_domains"


async def test_chromium_blocks_images_unless_disabled(base):
    for block, want_loaded in ((True, False), (False, True)):
        async with BrowserManager(allow_private_network=True, prefer="chromium", block=block) as bm:
            tab = await bm.open(base + "/apply.html")
            await tab.page.wait_for_timeout(300)
            w = await tab.page.evaluate("document.querySelector('img').naturalWidth")
            assert (w > 0) is want_loaded, (block, w)
            assert (bm.blocked_count > 0) is block


def test_blocklist_and_captcha_exemption():
    assert eng._host_matches("www.google-analytics.com", eng.BLOCKLIST)
    assert eng._host_matches("connect.facebook.net", eng.BLOCKLIST)
    assert not eng._host_matches("github.com", eng.BLOCKLIST)
    assert eng._host_matches("www.google.com", eng.CAPTCHA_HOSTS)
    assert eng._host_matches("challenges.cloudflare.com", eng.CAPTCHA_HOSTS)


def test_doctor_cli():
    import os
    import subprocess
    root = Path(__file__).resolve().parent.parent
    out = subprocess.run([str(root / ".venv/bin/leanb"), "doctor"], capture_output=True, text=True, timeout=120,
                         env=dict(os.environ))
    assert out.returncode == 0, out.stdout + out.stderr
    assert "all good" in out.stdout


def test_install_script_syntax():
    import subprocess
    root = Path(__file__).resolve().parent.parent
    assert subprocess.run(["bash", "-n", str(root / "install.sh")]).returncode == 0
    text = (root / "install.sh").read_text()
    assert "leanb\" install" in text  # Obscura download and hash checks live in one place: lean_browser/installer.py
    assert "--ignore-scripts" in text
    # every supported platform has a pinned archive digest and pinned binary hashes for the default version
    for plat in ("aarch64-macos", "x86_64-linux", "aarch64-linux"):
        assert len(eng.OBSCURA_RELEASE_SHA256[eng.DEFAULT_OBSCURA_VERSION][plat]) == 64
        assert set(eng.OBSCURA_HASHES[eng.DEFAULT_OBSCURA_VERSION][plat]) == {"obscura", "obscura-worker"}


@needs_obscura
def test_obscura_dies_with_its_client(tmp_path):
    """Kill -9 the Python process that started Obscura: the sandboxed watchdog must stop Obscura too."""
    import os
    import signal
    import subprocess
    import sys
    import time
    code = ("import time; from lean_browser.engine import ObscuraProcess, find_obscura; "
            "p = ObscuraProcess(find_obscura()); p.start(); print(p.port, flush=True); time.sleep(60)")
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    port = int(child.stdout.readline().strip())

    def listening():
        import socket
        with socket.socket() as c:
            c.settimeout(1)
            return c.connect_ex(("127.0.0.1", port)) == 0
    assert listening(), "obscura not started"
    os.kill(child.pid, signal.SIGKILL)
    child.wait()
    deadline = time.time() + 6
    while time.time() < deadline:
        if not listening():
            return
        time.sleep(0.2)
    pytest.fail("obscura outlived its client")


async def test_unresponsive_page_moves_to_chromium(base, monkeypatch):
    """Simulate a page whose script thread is stuck: settle raises, and the tab moves to Chromium."""
    from lean_browser import settle as settle_mod
    from lean_browser.session import Session
    from lean_browser.settle import SETTLE_INIT_JS
    calls = {"n": 0}
    real = settle_mod.settle

    async def flaky(page, *a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise settle_mod.PageUnresponsive("stuck")
        return await real(page, *a, **kw)
    import lean_browser.session as sess_mod
    monkeypatch.setattr(sess_mod, "settle", flaky)
    async with BrowserManager(allow_private_network=True, init_scripts=[SETTLE_INIT_JS]) as bm:
        s = Session(bm)
        out = await s.open(base + "/login.html")
        if find_obscura():
            assert "engine: chromium (page unresponsive on obscura)" in out
        assert 'textbox "Username"' in out


@pytest.mark.skipif(eng.IS_MAC or not eng.sandbox_tool(), reason="Linux bubblewrap sandbox")
def test_linux_sandbox_hides_home_and_allows_only_its_temp_dir(tmp_path):
    import os
    import subprocess
    home = Path.home()
    jail = eng.bwrap_args(str(tmp_path), "/usr/bin")
    run = lambda cmd: subprocess.run([*jail, "/bin/sh", "-c", cmd], capture_output=True, text=True, timeout=30)
    assert run(f"ls {home}").returncode != 0  # the home folder doesn't exist inside the sandbox
    assert run(f"echo x > {tmp_path}/ok && cat {tmp_path}/ok").stdout.strip() == "x"
    assert run("echo x > /usr/evil").returncode != 0  # system folders are read-only
    assert os.getuid() == 0 or run("id -u").stdout.strip() != "0"


@pytest.mark.parametrize("engine", ["chromium"] + (["obscura"] if eng.find_obscura() and eng.sandbox_tool() else []))
async def test_redirect_to_private_address_is_blocked(monkeypatch, engine):
    """A public page that redirects to localhost (or 169.254.169.254) must not load. Request routing never sees
    redirect hops, so the connect-time guard (netguard) has to catch it."""
    import http.server
    import threading

    from lean_browser import netguard

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/redir":
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{port}/secret")
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<title>INTERNAL</title><h1>internal admin</h1>")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    real = netguard.resolve_public

    async def fake(host, p):  # "public.example" plays a public site that happens to live on this machine
        return "127.0.0.1" if host == "public.example" else await real(host, p)

    monkeypatch.setattr(netguard, "resolve_public", fake)
    try:
        async with BrowserManager(prefer=engine) as bm:
            try:
                tab = await bm.open(f"http://public.example:{port}/redir")
                text = await tab.page.content()
            except Exception as e:  # a refused navigation is fine too
                text = str(e)
            assert "internal admin" not in text, text
            assert any("blocked private-network connection to 127.0.0.1" in e for e in bm.events), bm.events
        # the same site without the redirect still loads through the guard
        async with BrowserManager(prefer=engine) as bm:
            tab = await bm.open(f"http://public.example:{port}/page")
            assert "internal admin" in await tab.page.content()
            assert tab.engine == engine, (tab.engine, tab.reason)
    finally:
        srv.shutdown()


async def test_netguard_refuses_private_targets():
    from lean_browser.netguard import resolve_public
    for host in ("127.0.0.1", "localhost", "10.0.0.5", "169.254.169.254", "::1", "0.0.0.0"):
        with pytest.raises(PermissionError):
            await resolve_public(host, 80)
    assert await resolve_public("8.8.8.8", 53) == "8.8.8.8"


@needs_obscura
async def test_engine_crash_mid_session_is_explained_and_recoverable(base):
    import os
    import re
    import signal
    import subprocess

    from lean_browser.tools import Config, LeanBrowser
    async with LeanBrowser(Config(allow_private_network=True)) as lb:
        out = (await lb.call("open", {"url": base + "/login.html"}))[0]
        assert "engine: obscura" in out
        pids = subprocess.run(["pgrep", "-f", f"port {lb.bm._obscura.port}"], capture_output=True, text=True).stdout.split()
        assert pids
        for pid in pids:
            try:
                os.kill(int(pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
        await asyncio.sleep(0.5)
        uid = int(re.search(r'(\d+): textbox "Username"', out).group(1))
        err = (await lb.call("act", {"action": "fill", "id": uid, "value": "demo"}))[0]
        assert err.startswith("Error: the obscura engine for this page closed or crashed"), err
        again = (await lb.call("open", {"url": base + "/order.html"}))[0]
        assert "engine: chromium (navigation failed on obscura" in again and "Place order" in again, again[:300]


async def test_chromium_tries_its_os_sandbox_and_reports_it(monkeypatch):
    """The first launch asks for Chromium's OS sandbox; the result is exposed whether or not the host allows it."""
    from playwright.async_api import BrowserType
    monkeypatch.delenv("LEANB_CHROMIUM_SANDBOX", raising=False)
    calls, real = [], BrowserType.launch

    async def spy(self, **kw):
        calls.append(kw.get("chromium_sandbox"))
        return await real(self, **kw)
    monkeypatch.setattr(BrowserType, "launch", spy)
    async with BrowserManager(prefer="chromium") as bm:
        tab = await bm.open("data:text/html,<title>t</title>")
        assert tab.engine == "chromium"
        assert calls[0] is True
        assert bm.chromium_sandboxed in (True, False)
        if bm.chromium_sandboxed:
            assert calls == [True] and not bm.chromium_sandbox_note
        else:  # e.g. Linux CI without unprivileged user namespaces
            assert calls == [True, False] and bm.chromium_sandbox_note
            assert any("OS sandbox unavailable" in e for e in bm.events), bm.events
        if eng.IS_MAC:
            assert bm.chromium_sandboxed, bm.chromium_sandbox_note


async def test_chromium_falls_back_without_os_sandbox(monkeypatch):
    from playwright.async_api import BrowserType

    from lean_browser import doctor
    monkeypatch.delenv("LEANB_CHROMIUM_SANDBOX", raising=False)
    calls, real = [], BrowserType.launch

    async def no_sandbox_here(self, **kw):
        calls.append(kw.get("chromium_sandbox"))
        if kw.get("chromium_sandbox"):
            raise RuntimeError("Browser closed.\nNo usable sandbox!")
        return await real(self, **kw)
    monkeypatch.setattr(BrowserType, "launch", no_sandbox_here)
    async with BrowserManager(prefer="chromium") as bm:
        tab = await bm.open("data:text/html,<title>fallback</title>")
        assert await tab.page.title() == "fallback"
        assert calls == [True, False]
        assert bm.chromium_sandboxed is False
        assert "RuntimeError: Browser closed." in bm.chromium_sandbox_note
        assert any("chromium OS sandbox unavailable" in e for e in bm.events), bm.events
        c = doctor.check_chromium_sandbox({"sandboxed": bm.chromium_sandboxed, "why": bm.chromium_sandbox_note})
        assert c.status == doctor.WARN and "Browser closed" in c.detail and "user namespaces" in c.fix

    # The escape hatch skips the sandboxed attempt entirely.
    calls.clear()
    monkeypatch.setenv("LEANB_CHROMIUM_SANDBOX", "0")
    async with BrowserManager(prefer="chromium") as bm:
        await bm.open("data:text/html,<title>off</title>")
        assert calls == [False] and bm.chromium_sandboxed is False
        assert "LEANB_CHROMIUM_SANDBOX" in bm.chromium_sandbox_note
        c = doctor.check_chromium_sandbox({"sandboxed": False, "why": bm.chromium_sandbox_note})
        assert c.status == doctor.WARN and "Unset LEANB_CHROMIUM_SANDBOX" in c.fix
    assert doctor.check_chromium_sandbox({"sandboxed": True, "why": ""}).status == doctor.PASS


@needs_obscura
async def test_websocket_on_obscura_fails_honestly_and_moves_the_domain(base):
    """Obscura's own WebSocket fakes a successful open. Lean makes it fail honestly there, tells the caller after
    an action that opened one, and opens that host in Chromium from then on."""
    from lean_browser.session import OBSCURA_DIALOG_SHIM, Session
    from lean_browser.settle import SETTLE_INIT_JS
    async with BrowserManager(allow_private_network=True, init_scripts=[SETTLE_INIT_JS],
                              obscura_init_scripts=[OBSCURA_DIALOG_SHIM]) as bm:
        s = Session(bm)
        out = await s.open(base + "/live-button.html")
        assert "engine: obscura" in out
        import re
        btn = int(re.search(r'(\d+): button "Start chat"', out).group(1))
        res = await s.act("click", btn)
        assert "Chat connected" not in res, res
        assert "can't connect" in res and "WebSocket" in res, res
        out = await s.open(base + "/live-button.html")
        assert "engine: chromium" in out and "websocket" in out, out[:300]
