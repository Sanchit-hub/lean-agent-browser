"""Connect-time guard (lean_browser/netguard.py): chaining to the user's own proxy, and DNS rebinding."""
import asyncio
import base64
import http.server
import socket
import threading

import pytest

from lean_browser import engine as _eng
from lean_browser import netguard
from lean_browser.netguard import NetGuard, Upstream, env_upstreams


@pytest.fixture
def origin():
    """A plain HTTP server on 127.0.0.1 that counts the requests it gets."""
    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            if self.path == "/redir":
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{port}/secret")
                self.end_headers()
                return
            body = b"<title>ORIGIN</title><h1>hello from origin</h1>" if self.path != "/secret" else \
                b"<title>INTERNAL</title><h1>internal admin</h1>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield port, hits
    srv.shutdown()


class RecordingProxy:
    """Stands in for a corporate proxy: forwards anywhere (it is the user's own), records what it was asked."""

    def __init__(self):
        self.seen: list[tuple[str, str, str | None]] = []  # (method, target, proxy-authorization)
        self.server = None
        self.port = 0

    async def start(self):
        self.server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def close(self):
        self.server.close()

    async def _client(self, r, w):
        head = (await r.readuntil(b"\r\n\r\n")).decode("latin-1")
        lines = head.split("\r\n")
        method, target, _ = lines[0].split(" ", 2)
        auth = next((l.split(":", 1)[1].strip() for l in lines[1:] if l.lower().startswith("proxy-authorization:")), None)
        self.seen.append((method, target, auth))
        if method == "CONNECT":
            host, _, port = target.rpartition(":")
        else:
            rest = target.split("://", 1)[1]
            hostport, _, path = rest.partition("/")
            host, _, port = hostport.partition(":")
            port = port or "80"
        # Every name in these tests is served by the local origin.
        ur, uw = await asyncio.open_connection("127.0.0.1", int(port))
        if method == "CONNECT":
            w.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        else:
            uw.write((f"{method} /{path} HTTP/1.1\r\n" + "\r\n".join(lines[1:])).encode("latin-1"))
        await asyncio.gather(netguard._pipe(r, uw), netguard._pipe(ur, w), return_exceptions=True)


async def http_get(proxy_port: int, url: str) -> tuple[int, str]:
    """GET url through the proxy at proxy_port, as a browser would (absolute URL in the request line)."""
    r, w = await asyncio.open_connection("127.0.0.1", proxy_port)
    host = url.split("://", 1)[1].split("/", 1)[0]
    w.write(f"GET {url} HTTP/1.1\r\nHost: {host}\r\n\r\n".encode())
    await w.drain()
    data = await asyncio.wait_for(r.read(), 10)
    w.close()
    text = data.decode("latin-1")
    return int(text.split(" ", 2)[1]), text


async def http_connect(proxy_port: int, target: str) -> int:
    r, w = await asyncio.open_connection("127.0.0.1", proxy_port)
    w.write(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
    await w.drain()
    head = await asyncio.wait_for(r.readuntil(b"\r\n\r\n"), 10)
    w.close()
    return int(head.split(b" ", 2)[1])


@pytest.fixture
def public_example(monkeypatch):
    """public.example plays a public site that happens to live on this machine."""
    real = netguard.resolve_public

    async def fake(host, p):
        return "127.0.0.1" if host == "public.example" else await real(host, p)
    monkeypatch.setattr(netguard, "resolve_public", fake)


def test_env_upstreams_parsing():
    http_up, tun_up = env_upstreams({"HTTP_PROXY": "http://corp:3128", "https_proxy": "https://u%40x:p%3As@sec:8443"})
    assert (http_up.host, http_up.port, http_up.tls, http_up.auth) == ("corp", 3128, False, None)
    assert (tun_up.host, tun_up.port, tun_up.tls) == ("sec", 8443, True)
    assert base64.b64decode(tun_up.auth.split()[1]) == b"u@x:p:s"
    http_up, tun_up = env_upstreams({"ALL_PROXY": "proxy.local:8080"})
    assert http_up == tun_up == Upstream("proxy.local", 8080)
    assert env_upstreams({}) == (None, None)
    with pytest.raises(ValueError, match="socks"):
        env_upstreams({"ALL_PROXY": "socks5://127.0.0.1:1080"})


async def test_guard_chains_to_upstream_and_still_blocks_private(origin, public_example):
    port, hits = origin
    up = await RecordingProxy().start()
    upstream = Upstream("127.0.0.1", up.port, auth="Basic dTpw")
    g = await NetGuard(http_upstream=upstream, tunnel_upstream=upstream, no_proxy=lambda h: False).start()
    try:
        status, body = await http_get(g.port, f"http://public.example:{port}/page")
        assert status == 200 and "hello from origin" in body
        assert ("GET", f"http://public.example:{port}/page", "Basic dTpw") in up.seen
        assert await http_connect(g.port, f"public.example:{port}") == 200
        assert ("CONNECT", f"public.example:{port}", "Basic dTpw") in up.seen

        # A private destination is refused by the guard; the upstream proxy never hears of it.
        n = len(up.seen)
        for target in (f"http://127.0.0.1:{port}/secret", f"http://169.254.169.254/latest/meta-data/",
                       f"http://localhost:{port}/secret"):
            status, body = await http_get(g.port, target)
            assert status == 403 and "private-network" in body
        assert await http_connect(g.port, "10.0.0.5:443") == 403
        assert len(up.seen) == n
        assert "/secret" not in hits
    finally:
        await g.close()
        await up.close()


async def test_guard_no_proxy_hosts_connect_directly(origin, public_example):
    port, hits = origin
    up = await RecordingProxy().start()
    upstream = Upstream("127.0.0.1", up.port)
    g = await NetGuard(http_upstream=upstream, tunnel_upstream=upstream,
                       no_proxy=lambda h: h == "public.example").start()
    try:
        status, _ = await http_get(g.port, f"http://public.example:{port}/direct")
        assert status == 200 and "/direct" in hits and up.seen == []
    finally:
        await g.close()
        await up.close()


async def test_upstream_refusal_is_passed_to_the_browser(public_example):
    async def refuse(r, w):
        await r.readuntil(b"\r\n\r\n")
        w.write(b"HTTP/1.1 407 Proxy Authentication Required\r\nContent-Length: 0\r\n\r\n")
        await w.drain()
        w.close()
    srv = await asyncio.start_server(refuse, "127.0.0.1", 0)
    upstream = Upstream("127.0.0.1", srv.sockets[0].getsockname()[1])
    g = await NetGuard(http_upstream=upstream, tunnel_upstream=upstream, no_proxy=lambda h: False).start()
    try:
        assert await http_connect(g.port, "public.example:443") == 407
    finally:
        await g.close()
        srv.close()


@pytest.mark.parametrize("engine", ["chromium"] + (["obscura"] if _eng.find_obscura() and _eng.sandbox_tool() else []))
async def test_browser_behind_user_proxy_keeps_redirect_protection(origin, public_example, monkeypatch, engine):
    """With HTTP_PROXY set, the guard used to switch off and redirect hops went unchecked. Now it chains."""
    from lean_browser.engine import BrowserManager
    port, hits = origin
    up = await RecordingProxy().start()
    for k in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy", "http_proxy"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{up.port}")
    try:
        async with BrowserManager(prefer=engine) as bm:
            tab = await bm.open(f"http://public.example:{port}/page")
            assert "hello from origin" in await tab.page.content()
            assert tab.engine == engine, (tab.engine, tab.reason)
            assert any(t == f"http://public.example:{port}/page" for _, t, _ in up.seen), up.seen
            assert any("behind the private-network guard" in e for e in bm.events), bm.events
            try:
                tab = await bm.open(f"http://public.example:{port}/redir")
                text = await tab.page.content()
            except Exception as e:  # a refused navigation is fine too
                text = str(e)
            assert "internal admin" not in text
            assert "/secret" not in hits
            assert any("blocked private-network connection to 127.0.0.1" in e for e in bm.events), bm.events
    finally:
        await up.close()


async def test_socks_proxy_turns_guard_off_with_a_note(monkeypatch):
    from lean_browser.engine import BrowserManager
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:1")
    bm = BrowserManager()
    assert await bm._ensure_guard() is None
    assert any("socks" in e and "guard is off" in e for e in bm.events), bm.events


async def test_dns_rebinding_is_refused(origin, monkeypatch):
    """rebind.example first answers with a 'public' address, then with the cloud metadata address. The guard
    resolves once per connection, checks that answer and connects to exactly that address, so the second
    connection is refused instead of reaching the private address."""
    port, hits = origin
    calls = []
    real_bad = netguard._bad_ip
    # Only for this test, 127.0.0.1 stands in for a public address (the origin lives there).
    monkeypatch.setattr(netguard, "_bad_ip", lambda ip: False if ip == "127.0.0.1" else real_bad(ip))
    real_gai = socket.getaddrinfo

    def gai(host, p, *a, **k):
        if host == "rebind.example":
            calls.append(host)
            ip = "127.0.0.1" if len(calls) == 1 else "169.254.169.254"
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, p))]
        return real_gai(host, p, *a, **k)
    monkeypatch.setattr(socket, "getaddrinfo", gai)

    g = await NetGuard(no_proxy=lambda h: True).start()
    try:
        status, body = await http_get(g.port, f"http://rebind.example:{port}/page")
        assert status == 200 and "hello from origin" in body
        assert len(calls) == 1  # one lookup per connection: the checked answer is the one used
        status, body = await http_get(g.port, f"http://rebind.example:{port}/secret")
        assert status == 403 and "private-network" in body
        assert g.blocked == ["rebind.example"]
        assert hits == ["/page"]
    finally:
        await g.close()
