"""Connect-time network guard: a tiny local HTTP/CONNECT proxy that refuses private destinations.

Why: Playwright's request routing only sees the first URL of a redirect chain, so a public page that
redirects to http://127.0.0.1/ or http://169.254.169.254/ got past the old per-request check on Chromium.
A hostname check alone also loses to DNS rebinding. This proxy resolves the host itself, refuses the
connection if ANY resolved address is private (loopback, RFC1918, link-local, unique-local, reserved),
and then connects to the exact address it checked. Every hop of a redirect, every subresource and every
WebSocket goes through it.

It listens on 127.0.0.1 only, on a random port, and lives as long as its BrowserManager.

Behind the user's own proxy (HTTP_PROXY / HTTPS_PROXY / ALL_PROXY, http:// or https:// proxies), the guard
still checks every destination and then chains to that proxy instead of connecting itself. Hosts in NO_PROXY
connect directly, still checked. The upstream proxy resolves the name itself, so DNS rebinding is only
covered for direct connections (documented in docs/RELIABILITY.md).
"""
from __future__ import annotations

import asyncio
import base64
import ipaddress
import logging
import os
import socket
import ssl
from dataclasses import dataclass
from typing import Callable
from urllib.parse import unquote, urlsplit
from urllib.request import proxy_bypass_environment

log = logging.getLogger("lean_browser.netguard")


def _bad_ip(ip: str) -> bool:
    a = ipaddress.ip_address(ip.split("%")[0])
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    return a.is_private or a.is_loopback or a.is_link_local or a.is_unspecified or a.is_reserved or a.is_multicast


async def resolve_public(host: str, port: int) -> str:
    """The address to connect to, or raise PermissionError if the host is (or resolves to) a private address."""
    h = host.strip("[]")
    if h.lower() == "localhost" or h.lower().endswith(".localhost"):
        raise PermissionError(f"{host} is a private-network address")
    infos = await asyncio.get_running_loop().getaddrinfo(h, port, type=socket.SOCK_STREAM)
    addrs = [i[4][0] for i in infos]
    if not addrs:
        raise OSError(f"cannot resolve {host}")
    if any(_bad_ip(a) for a in addrs):
        raise PermissionError(f"{host} resolves to a private-network address")
    return addrs[0]


@dataclass
class Upstream:
    """The user's own proxy. auth is the ready Proxy-Authorization value, if the URL carried user:password."""
    host: str
    port: int
    tls: bool = False
    auth: str | None = None

    @classmethod
    def parse(cls, url: str) -> "Upstream":
        u = urlsplit(url if "://" in url else "http://" + url)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ValueError(f"unsupported proxy {u.scheme}://: only http:// and https:// proxies can be chained")
        auth = None
        if u.username is not None:
            raw = f"{unquote(u.username)}:{unquote(u.password or '')}".encode()
            auth = "Basic " + base64.b64encode(raw).decode()
        return cls(u.hostname, u.port or (443 if u.scheme == "https" else 80), u.scheme == "https", auth)


def env_upstreams(env: dict | None = None) -> tuple[Upstream | None, Upstream | None]:
    """(proxy for plain http, proxy for tunnels: https / wss) from the environment, like curl reads them.
    Raises ValueError for a proxy that can't be chained (socks)."""
    env = os.environ if env is None else env

    def get(*names):
        for n in names:
            v = env.get(n) or env.get(n.lower())
            if v:
                return Upstream.parse(v)
        return None
    return get("HTTP_PROXY", "ALL_PROXY"), get("HTTPS_PROXY", "ALL_PROXY")


def env_has_proxy(env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    return any(env.get(k) or env.get(k.lower()) for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"))


class NetGuard:
    def __init__(self, on_block: Callable[[str], None] | None = None, http_upstream: Upstream | None = None,
                 tunnel_upstream: Upstream | None = None, no_proxy: Callable[[str], bool] | None = None):
        self.on_block = on_block or (lambda host: None)
        self.http_upstream, self.tunnel_upstream = http_upstream, tunnel_upstream
        self.no_proxy = no_proxy or (lambda host: bool(proxy_bypass_environment(host)))
        self.server: asyncio.base_events.Server | None = None
        self.port = 0
        self.blocked: list[str] = []

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def start(self) -> "NetGuard":
        self.server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def close(self):
        if self.server:
            self.server.close()
            try:
                await asyncio.wait_for(self.server.wait_closed(), 2)
            except (asyncio.TimeoutError, Exception):
                pass
            self.server = None

    def _block(self, host: str):
        self.blocked.append(host)
        self.on_block(host)

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 30)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, ConnectionError):
            writer.close()
            return
        lines = head.decode("latin-1").split("\r\n")
        try:
            method, target, version = lines[0].split(" ", 2)
        except ValueError:
            writer.close()
            return
        try:
            if method.upper() == "CONNECT":
                host, _, port = target.rpartition(":")
                await self._tunnel(reader, writer, host, int(port))
            else:
                await self._forward(reader, writer, method, target, version, lines[1:])
        except Exception as e:  # noqa: BLE001 - one bad connection must not stop the proxy
            log.debug("netguard: %s %s: %s", method, target, e)
            try:
                writer.close()
            except Exception:
                pass

    async def _refuse(self, writer, status: bytes):
        writer.write(status)
        await writer.drain()
        writer.close()

    def _upstream(self, host: str, tunnel: bool) -> Upstream | None:
        up = self.tunnel_upstream if tunnel else self.http_upstream
        return None if up is None or self.no_proxy(host.strip("[]")) else up

    async def _connect_upstream(self, up: Upstream):
        ctx = ssl.create_default_context() if up.tls else None
        return await asyncio.wait_for(asyncio.open_connection(up.host, up.port, ssl=ctx,
                                                              server_hostname=up.host if ctx else None), 20)

    async def _open(self, writer, host: str, port: int):
        try:
            ip = await resolve_public(host, port)
        except PermissionError:
            self._block(host.strip("[]"))
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\n"
                         b"Blocked by Lean Agent Browser: private-network address")
            await writer.drain()
            writer.close()
            return None
        except OSError:
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            await writer.drain()
            writer.close()
            return None
        return await asyncio.wait_for(asyncio.open_connection(ip, port), 20)

    async def _check(self, writer, host: str, port: int) -> bool:
        """The destination check alone (used before chaining to an upstream proxy)."""
        try:
            await resolve_public(host, port)
        except PermissionError:
            self._block(host.strip("[]"))
            await self._refuse(writer, b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\n"
                                       b"Blocked by Lean Agent Browser: private-network address")
            return False
        except OSError:
            # The upstream proxy may resolve names this machine can't (split DNS); let it try.
            return True
        return True

    async def _tunnel(self, reader, writer, host: str, port: int):
        up = self._upstream(host, tunnel=True)
        if up:
            if not await self._check(writer, host, port):
                return
            ur, uw = await self._connect_upstream(up)
            target = f"{host}:{port}"
            req = f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n"
            if up.auth:
                req += f"Proxy-Authorization: {up.auth}\r\n"
            uw.write((req + "\r\n").encode("latin-1"))
            await uw.drain()
            head = await asyncio.wait_for(ur.readuntil(b"\r\n\r\n"), 30)
            if head.split(b" ", 2)[1:2] != [b"200"]:
                writer.write(head)  # the browser sees the upstream proxy's own answer (407, 403, ...)
                await writer.drain()
                writer.close()
                uw.close()
                return
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            await _pipe_both(reader, writer, ur, uw)
            return
        conn = await self._open(writer, host, port)
        if not conn:
            return
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        await _pipe_both(reader, writer, *conn)

    async def _forward(self, reader, writer, method: str, target: str, version: str, headers: list[str]):
        u = urlsplit(target)
        if u.scheme != "http" or not u.hostname:
            writer.write(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
            await writer.drain()
            writer.close()
            return
        up = self._upstream(u.hostname, tunnel=False)
        if up:
            if not await self._check(writer, u.hostname, u.port or 80):
                return
            ur, uw = await self._connect_upstream(up)
            path = target  # a proxy takes the absolute URL
            if up.auth:
                headers = [h for h in headers if not h.lower().startswith("proxy-authorization:")]
                headers = headers + [f"Proxy-Authorization: {up.auth}"]
        else:
            conn = await self._open(writer, u.hostname, u.port or 80)
            if not conn:
                return
            ur, uw = conn
            path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        # One request per connection: the browser may reuse a proxy connection for another host, so force
        # Connection: close on both sides instead of piping a keep-alive stream to the wrong server.
        keep = [h for h in headers if h and not h.lower().startswith(("proxy-connection:", "connection:", "keep-alive:"))]
        uw.write((f"{method} {path} {version}\r\n" + "\r\n".join(keep) + "\r\nConnection: close\r\n\r\n").encode("latin-1"))
        await uw.drain()
        await _pipe_both(reader, writer, ur, uw)


async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter):
    try:
        while True:
            data = await src.read(65536)
            if not data:
                break
            dst.write(data)
            await dst.drain()
    except (ConnectionError, asyncio.CancelledError, OSError):
        pass
    finally:
        try:
            dst.close()
        except Exception:
            pass


async def _pipe_both(cr, cw, ur, uw):
    await asyncio.gather(_pipe(cr, uw), _pipe(ur, cw), return_exceptions=True)
