"""Fixture site for the eval harness.

Binds to 127.0.0.1 only. Every task page posts to /api/submit/<task> (or a task-specific
endpoint), and the server records it, so success is verified server-side, never by what the
agent claims.

Run standalone:  python -I evals/fixtures/server.py 8765
"""
from __future__ import annotations

import html
import json
import random
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SITE = Path(__file__).parent / "site"
LOCK = threading.Lock()

# ---------- deterministic generated data ----------
_rng = random.Random(42)
TOPICS = ["rust", "python", "go", "browser", "agents", "databases"]
SEARCH_DOCS = []
for i in range(60):
    t = TOPICS[i % len(TOPICS)]
    SEARCH_DOCS.append({
        "id": i + 1,
        "title": f"{t.capitalize()} guide #{i + 1}: " + _rng.choice(
            ["getting started", "performance tips", "common mistakes", "deep dive", "testing", "tooling"]),
        "topic": t,
        "score": round(_rng.uniform(0.1, 0.99), 3),
        "snippet": f"A practical article about {t} with examples and benchmarks. " * 2,
    })
ORDERS = [{"id": f"ORD-{1000 + i}", "customer": _rng.choice(["Asha", "Ravi", "Meera", "Kabir", "Isha", "Arjun"]),
           "amount": f"₹{_rng.randint(200, 9999):,}", "status": _rng.choice(["paid", "shipped", "refunded"])}
          for i in range(50)]
FEED = [{"n": i + 1, "title": f"Post {i + 1}: " + _rng.choice(
    ["monsoon photos", "new café in Indiranagar", "metro line update", "weekend trek", "startup demo day",
     "cricket highlights", "book club notes", "street food map"])} for i in range(80)]

ARTICLE_PARAS = []
for i in range(40):
    ARTICLE_PARAS.append(
        f"Section {i + 1}. The river valley's history spans centuries of trade, farming and migration. "
        f"Local records describe markets, festivals and the slow growth of nearby towns. "
        f"Engineers surveyed the area repeatedly, debating routes and materials. ")
ARTICLE_PARAS[27] = ("Section 28. After years of delays caused by floods and funding disputes, "
                     "the Halden suspension bridge was finally completed in 1931, "
                     "connecting the two banks for the first time.")


def page(title: str, body: str, head: str = "") -> bytes:
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
            f"<link rel='stylesheet' href='/style.css'>{head}</head><body>{NAV}{body}{FOOTER}</body></html>").encode()


NAV = ("<header><nav><a href='/'>Home</a> <a href='/search.html'>Search</a> <a href='/orders.html'>Orders</a> "
       "<a href='/feed.html'>Feed</a> <a href='/docs.html'>Docs</a> <a href='/about.html'>About</a> "
       "<a href='/careers.html'>Careers</a> <a href='/contact.html'>Contact</a></nav></header>")
FOOTER = ("<footer><a href='/privacy'>Privacy</a> <a href='/terms'>Terms</a> <a href='/press'>Press</a> "
          "<a href='/status'>Status</a> <a href='/security'>Security</a></footer>")


def render_search(q: str) -> bytes:
    hits = sorted([d for d in SEARCH_DOCS if q and q.lower() in d["topic"]], key=lambda d: -d["score"])
    rows = "".join(
        f"<li class='result'><a href='/doc/{d['id']}'>{html.escape(d['title'])}</a>"
        f"<span class='score'> relevance {d['score']}</span><p>{d['snippet']}</p></li>" for d in hits)
    body = (f"<main><h1>Search</h1><form action='/search.html'><input name='q' aria-label='Search query' "
            f"value='{html.escape(q)}'><button>Search</button></form>"
            f"{f'<p>{len(hits)} results for “{html.escape(q)}”, sorted by relevance</p><ol>{rows}</ol>' if q else ''}</main>")
    return page("Search", body)


def render_orders(p: int) -> bytes:
    per = 10
    pages = (len(ORDERS) + per - 1) // per
    p = max(1, min(p, pages))
    rows = "".join(f"<tr><td>{o['id']}</td><td>{o['customer']}</td><td>{o['amount']}</td><td>{o['status']}</td></tr>"
                   for o in ORDERS[(p - 1) * per:p * per])
    links = " ".join(f"<a href='/orders.html?page={i}'>{i}</a>" if i != p else f"<b>{i}</b>" for i in range(1, pages + 1))
    nxt = f"<a href='/orders.html?page={p + 1}'>Next</a>" if p < pages else ""
    body = (f"<main><h1>Orders</h1><table><thead><tr><th>Order</th><th>Customer</th><th>Amount</th><th>Status</th>"
            f"</tr></thead><tbody>{rows}</tbody></table><nav aria-label='Pagination'>Page {links} {nxt}</nav></main>")
    return page(f"Orders — page {p}", body)


def render_article() -> bytes:
    body = "<main><article><h1>The Halden Valley: a history</h1>" + "".join(f"<p>{x}</p>" for x in ARTICLE_PARAS) + "</article></main>"
    return page("The Halden Valley", body)


LAPTOPS = [
    # name, price, gpu, ram, availability   (None = field missing on the card)
    ("Aero 14", 92990, "RTX 4060", "16 GB", "In stock"), ("Bolt 15", 78490, "RTX 4060", "16 GB", "In stock"),
    ("Core 16", 71990, "RTX 4050", "16 GB", "In stock"), ("Dash 15", 84990, "RTX 4060", "8 GB", "In stock"),
    ("Edge 14", 99990, "RTX 4070", "16 GB", "Out of stock"), ("Flux 15", 81490, "RTX 4060", "32 GB", "In stock"),
    ("Grid 15", 69990, None, "16 GB", "In stock"), ("Halo 16", 88990, "RTX 4060", "16 GB", "Only 2 left"),
    ("Ion 15", 74990, "RTX 4060", None, "In stock"), ("Jet 14", 105990, "RTX 4070", "32 GB", "In stock"),
    ("Kite 15", 79990, "RTX 4060", "16 GB", "Out of stock"), ("Lynx 16", 86490, "RTX 4060", "24 GB", "In stock"),
]


def render_laptops() -> bytes:
    cards = []
    for name, price, gpu, ram, avail in LAPTOPS:
        specs = "".join(f"<li>{k}: {v}</li>" for k, v in (("GPU", gpu), ("RAM", ram)) if v)
        cards.append(f"<div class='card'><h3><a href='/laptop/{name.split()[0].lower()}'>{name}</a></h3>"
                     f"<p class='price'>Price: ₹{price:,}</p><ul>{specs}</ul><p class='availability'>{avail}</p></div>")
    body = "<main><h1>Gaming laptops</h1><section class='grid'>" + "".join(cards) + "</section></main>"
    return page("Gaming laptops", body)


def render_big() -> bytes:
    """A GitHub-sized page (~6k elements) for snapshot performance tests."""
    nav = "".join(f"<a href='/n{i}'>Nav {i}</a> " for i in range(60))
    rows = "".join(f"<tr><td>file_{i}.py</td><td><a href='/f/{i}'>open</a></td><td>commit message {i} with some words</td>"
                   f"<td><span class='age'>{i}d</span></td></tr>" for i in range(1200))
    cards = "".join(f"<div class='card'><h3>Card {i}</h3><p>Body text {i} " + "lorem ipsum " * 8 + f"</p><button>Star {i}</button></div>"
                    for i in range(300))
    body = (f"<nav>{nav}</nav><main><h1>Big repo</h1><table><tbody>{rows}</tbody></table>"
            f"<section class='cards'>{cards}</section></main>")
    return page("Big page", body)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    @property
    def state(self) -> dict:  # one state per server, so several servers can run evals in parallel
        return self.server.state

    def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8", headers: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _cookies(self) -> dict:
        out = {}
        for part in self.headers.get("Cookie", "").split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                out[k] = v
        return out

    # ---------- GET ----------
    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        path = u.path
        if path == "/api/state":
            with LOCK:
                return self._json(self.state)
        if path == "/api/reset":
            with LOCK:
                self.state.clear()
                self.state.update(submissions=[], hits=[])
            return self._json({"ok": True})
        if path == "/api/feed":
            off = int(q.get("offset", 0))
            return self._json(FEED[off:off + 10])
        if path.startswith("/api/exfil"):
            with LOCK:
                self.state["hits"].append({"path": self.path})
            return self._json({"ok": True})
        if path == "/search.html":
            return self._send(200, render_search(q.get("q", "")))
        if path == "/orders.html":
            return self._send(200, render_orders(int(q.get("page", 1) or 1)))
        if path == "/article.html":
            return self._send(200, render_article())
        if path == "/big.html":
            return self._send(200, render_big())
        if path == "/laptops.html":
            return self._send(200, render_laptops())
        if path == "/account":
            if self._cookies().get("session") == "demo-session":
                return self._send(200, page("Account", "<main><h1>Welcome back, demo</h1></main>"))
            return self._send(302, b"", headers={"Location": "/login.html"})
        from evals.bench import get_page
        hit = get_page(path, q)
        if isinstance(hit, tuple) and hit[0] == "redirect":
            return self._send(302, b"", headers={"Location": hit[1]})
        if hit is not None:
            return self._send(200, *hit) if isinstance(hit, tuple) else self._send(200, hit)
        if path in ("/", ""):
            path = "/index.html"
        f = (SITE / path.lstrip("/")).resolve()
        if SITE.resolve() not in f.parents or not f.is_file():
            return self._send(404, page("Not found", "<main><h1>Not found</h1></main>"))
        ctype = {".html": "text/html; charset=utf-8", ".js": "application/javascript", ".css": "text/css",
                 ".png": "image/png", ".pdf": "application/pdf"}.get(f.suffix, "application/octet-stream")
        data = f.read_bytes()
        if f.suffix == ".html":
            data = data.replace(b"<!--NAV-->", NAV.encode()).replace(b"<!--FOOTER-->", FOOTER.encode())
        return self._send(200, data, ctype)

    # ---------- POST ----------
    def _body(self) -> tuple[str, dict, bool]:
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        ctype = self.headers.get("Content-Type", "")
        fields: dict = {}
        has_file = False
        if ctype.startswith("application/x-www-form-urlencoded"):
            fields = {k: v[0] for k, v in parse_qs(raw.decode(), keep_blank_values=True).items()}
        elif ctype.startswith("multipart/form-data"):
            boundary = ctype.split("boundary=")[1]
            for part in raw.split(b"--" + boundary.encode())[1:]:
                head, _, val = part.partition(b"\r\n\r\n")
                h = head.decode("latin-1")
                if 'name="' not in h:
                    continue
                name = h.split('name="')[1].split('"')[0]
                val = val.rsplit(b"\r\n", 1)[0]
                if "filename=" in h:
                    fname = h.split('filename="')[1].split('"')[0]
                    if fname and val:
                        has_file = True
                        fields[name] = {"filename": fname, "size": len(val)}
                else:
                    fields[name] = val.decode("utf-8", "replace")
        elif ctype.startswith("application/json"):
            fields = json.loads(raw or b"{}")
        return ctype.split(";")[0], fields, has_file

    def _record(self, task: str, ctype: str, fields: dict, has_file: bool):
        with LOCK:
            self.state["submissions"].append({"task": task, "ctype": ctype, "fields": fields, "has_file": has_file,
                                         "cookies": self._cookies()})

    def do_POST(self):
        path = urlparse(self.path).path
        ctype, fields, has_file = self._body()
        if path == "/api/login":
            ok = fields.get("username") == "demo" and fields.get("password") == "demo-pass-123"
            self._record("login", ctype, {**fields, "password": "***" if fields.get("password") else ""} | {"ok": ok}, False)
            if ok:
                return self._send(303, b"", headers={"Location": "/account", "Set-Cookie": "session=demo-session; Path=/; HttpOnly"})
            return self._send(401, page("Login", "<main><h1>Login</h1><p role='alert'>Invalid username or password</p>"
                                                 "<a href='/login.html'>Try again</a></main>"))
        if path == "/api/signup":
            if fields.get("username", "").lower() == "asha":
                return self._send(409, page("Sign up", "<main><h1>Sign up</h1><p role='alert'>Username “asha” is already taken. "
                                                       "Please choose another.</p><a href='/signup.html'>Back to sign up</a></main>"))
            self._record("signup", ctype, {**fields, "password": len(fields.get("password", ""))}, False)
            return self._send(200, page("Welcome", "<main><h1>Account created</h1></main>"))
        from evals.bench import post_hook
        hooked = post_hook(path, fields, self.state)
        if hooked is not None:
            code, body, task = hooked
            if task:
                self._record(task, ctype, fields, has_file)
            return self._send(code, body) if isinstance(body, bytes) else self._json(body, code)
        if path.startswith("/api/submit/"):
            task = path.rsplit("/", 1)[1]
            delay = float(parse_qs(urlparse(self.path).query).get("delay", ["0"])[0])
            if delay:
                import time
                time.sleep(min(delay, 15))
            self._record(task, ctype, fields, has_file)
            if ctype == "application/json":
                return self._json({"ok": True, "message": "Saved"})
            return self._send(200, page("Thanks", "<main><h1>Thanks — submission received</h1></main>"))
        return self._send(404, b"not found", "text/plain")


def make_server(port: int) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.state = {"submissions": [], "hits": []}
    return srv


def serve(port: int) -> ThreadingHTTPServer:
    srv = make_server(port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"fixtures on http://127.0.0.1:{port}", flush=True)
    make_server(port).serve_forever()
