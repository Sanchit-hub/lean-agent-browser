"""Engine layer: hardened Obscura launch, feature routing, fallback, and state carry-over.
Runs against the local fixture site. Obscura tests are skipped if the binary is not installed."""
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
        # p.proc is the sandboxed sh watchdog; look up whoever listens on the port instead.
        out = subprocess.run(["lsof", "-nP", f"-iTCP:{p.port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout
        assert f"127.0.0.1:{p.port}" in out and "*:" not in out, out
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
    assert eng.DEFAULT_OBSCURA_VERSION in text and eng.OBSCURA_RELEASE_SHA256[eng.DEFAULT_OBSCURA_VERSION] in text
    assert "--ignore-scripts" in text


@needs_obscura
def test_obscura_dies_with_its_client(tmp_path):
    """Kill -9 the Python process that started Obscura: the sandboxed watchdog must stop Obscura too."""
    import os
    import signal
    import subprocess
    import sys
    import time
    code = ("import time; from lean_browser.engine import ObscuraProcess, find_obscura; "
            "p = ObscuraProcess(find_obscura()); p.start(); print(p.proc.pid, flush=True); time.sleep(60)")
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    sh_pid = int(child.stdout.readline())
    obscura = [int(l.split()[0]) for l in subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True, text=True)
               .stdout.splitlines() if l.split()[1] == str(sh_pid)]
    assert obscura, "obscura not started under the watchdog"
    os.kill(child.pid, signal.SIGKILL)
    child.wait()
    deadline = time.time() + 6
    while time.time() < deadline:
        try:
            os.kill(obscura[0], 0)
        except ProcessLookupError:
            return
        time.sleep(0.2)
    os.kill(obscura[0], signal.SIGKILL)
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
