"""Obscura vs Chromium compatibility + token + memory spike.

Security measures:
- Obscura runs under macOS sandbox-exec: no writes outside a temp dir, no reads of $HOME
  (except its own binary folder), inbound only on localhost, and in fixture mode outbound
  only to localhost.
- Both CDP servers bind to 127.0.0.1. Obscura requires a random bearer token.
- Chromium is Playwright's bundled build with a throwaway profile, never the user's Chrome.
- All fixture pages are served from 127.0.0.1. Public pages (optional) are read-only GETs.

Usage: python compat.py fixtures | public
"""
import asyncio
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import tiktoken
from playwright.async_api import async_playwright

HERE = Path(__file__).parent
LEAN = HERE.parent
OBSCURA = LEAN / ".vendor/obscura-v0.2.6/bin/obscura"
SNAPSHOT_JS = (HERE / "snapshot.js").read_text()
ENC = tiktoken.get_encoding("o200k_base")
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)


def tok(s: str) -> int:
    return len(ENC.encode(s))


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def tree_rss_mb(pid: int) -> float:
    """Sum RSS of pid and all descendants."""
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,rss="], capture_output=True, text=True).stdout
    kids: dict[int, list[int]] = {}
    rss: dict[int, int] = {}
    for line in out.splitlines():
        p, pp, r = map(int, line.split())
        kids.setdefault(pp, []).append(p)
        rss[p] = r
    total, stack = 0, [pid]
    while stack:
        p = stack.pop()
        total += rss.get(p, 0)
        stack += kids.get(p, [])
    return round(total / 1024, 1)


def sandbox_profile(tmpdir: str, localhost_only: bool) -> str:
    home = str(Path.home())
    bin_dir = str(OBSCURA.parent)
    net_out = (
        '(deny network-outbound)\n'
        '(allow network-outbound (remote ip "localhost:*"))\n'
        '(allow network-outbound (remote unix-socket))\n'
        if localhost_only else ''
    )
    return f"""(version 1)
(allow default)
(deny file-write*)
(allow file-write* (subpath "{tmpdir}") (subpath "/private/var/folders") (subpath "/dev"))
(deny file-read* (subpath "{home}"))
(allow file-read* (subpath "{bin_dir}") (subpath "{tmpdir}"))
(deny network-inbound)
(allow network-inbound (local ip "localhost:*"))
{net_out}"""


def wait_port(port: int, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            socket.create_connection(("127.0.0.1", port), 0.5).close()
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"port {port} never opened")


class Engine:
    def __init__(self, kind: str, mode: str, chromium_path: str | None = None):
        self.kind, self.mode = kind, mode
        self.port = free_port()
        self.tmp = tempfile.mkdtemp(prefix=f"lab-{kind}-")
        self.token = None
        self.chromium_path = chromium_path

    def start(self):
        if self.kind == "obscura":
            self.token = secrets.token_hex(32)
            prof = Path(self.tmp) / "sandbox.sb"
            prof.write_text(sandbox_profile(os.path.realpath(self.tmp), self.mode == "fixtures"))
            env = {"PATH": "/usr/bin:/bin", "TMPDIR": self.tmp, "HOME": self.tmp,
                   "OBSCURA_CDP_TOKEN": self.token}
            args = ["sandbox-exec", "-f", str(prof), str(OBSCURA), "serve", "--port", str(self.port)]
            if self.mode == "fixtures":
                args.append("--allow-private-network")
            self.proc = subprocess.Popen(args, env=env, cwd=self.tmp,
                                         stdout=open(Path(self.tmp) / "out.log", "w"), stderr=subprocess.STDOUT)
            self.endpoint = f"ws://127.0.0.1:{self.port}"
        else:
            args = [self.chromium_path, "--headless=new", f"--remote-debugging-port={self.port}",
                    "--remote-debugging-address=127.0.0.1", f"--user-data-dir={self.tmp}/profile",
                    "--no-first-run", "--no-default-browser-check", "--disable-extensions",
                    "--disable-sync", "--disable-background-networking", "about:blank"]
            self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.endpoint = f"http://127.0.0.1:{self.port}"
        wait_port(self.port)
        time.sleep(0.5)

    def headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        log = Path(self.tmp) / "out.log"
        self.log = log.read_text()[-3000:] if log.exists() else ""
        shutil.rmtree(self.tmp, ignore_errors=True)


async def run_check(name, fn, results, timeout=15):
    t0 = time.time()
    try:
        detail = await asyncio.wait_for(fn(), timeout)
        results.append({"check": name, "ok": True, "detail": str(detail)[:200], "ms": int((time.time() - t0) * 1000)})
    except Exception as e:
        msg = f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}"[:240]
        results.append({"check": name, "ok": False, "detail": msg, "ms": int((time.time() - t0) * 1000)})
    r = results[-1]
    print(f"[{'PASS' if r['ok'] else 'FAIL'}] {name} ({r['ms']}ms) {r['detail'][:160]}", file=sys.stderr, flush=True)


def http_json(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())


async def fixture_checks(eng: Engine, pw, base: str):
    R: list[dict] = []
    tokens: dict = {}
    browser = await pw.chromium.connect_over_cdp(eng.endpoint, timeout=15000, **({"headers": eng.headers()} if eng.headers() else {}))
    ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
    page = await ctx.new_page()
    urllib.request.urlopen(f"{base}/api/reset", timeout=5).read()

    async def goto():
        await page.goto(f"{base}/form.html", wait_until="load")
        return await page.title()
    await run_check("navigate + title", goto, R)

    await run_check("evaluate", lambda: page.evaluate("1+1"), R)

    async def layout():
        r = await page.evaluate("JSON.stringify(document.getElementById('submit').getBoundingClientRect())")
        d = await page.evaluate("getComputedStyle(document.querySelector('.sr-hidden')).display")
        rr = json.loads(r)
        assert rr["width"] > 0 and rr["height"] > 0, f"zero rect {rr}"
        assert d == "none", d
        return f"rect {int(rr['width'])}x{int(rr['height'])}, display={d}"
    await run_check("layout: rect + computed style", layout, R)

    async def lean():
        s = await page.evaluate(SNAPSHOT_JS)
        tokens["form_lean_text"] = s
        assert "Submit application" in s
        assert "IGNORE ALL" not in s and "SYSTEM:" not in s, "hidden injection leaked"
        return f"{tok(s)} tok"
    await run_check("lean snapshot.js (hidden text dropped)", lean, R)

    async def aria():
        s = await page.locator("body").aria_snapshot()
        tokens["form_aria_text"] = s
        return f"{tok(s)} tok"
    await run_check("Playwright aria_snapshot", aria, R)

    async def html():
        s = await page.content()
        tokens["form_html_text"] = s
        return f"{tok(s)} tok"
    await run_check("page.content() HTML", html, R)

    async def axtree():
        cdp = await ctx.new_cdp_session(page)
        r = await cdp.send("Accessibility.getFullAXTree")
        s = json.dumps(r["nodes"])
        tokens["form_axtree_text"] = s
        return f"{len(r['nodes'])} nodes, {tok(s)} tok"
    await run_check("CDP Accessibility.getFullAXTree", axtree, R)

    async def markdown():
        cdp = await ctx.new_cdp_session(page)
        r = await cdp.send("LP.getMarkdown")
        s = r.get("markdown") or json.dumps(r)
        tokens["form_lp_markdown"] = s
        return f"{tok(s)} tok"
    await run_check("CDP LP.getMarkdown (Obscura-only)", markdown, R)

    async def shot():
        b = await page.screenshot()
        import struct
        w, h = struct.unpack(">II", b[16:24])
        tokens["form_screenshot_px"] = [w, h]
        return f"{w}x{h}, {len(b)} bytes"
    await run_check("viewport screenshot", shot, R, timeout=30)

    async def shot_el():
        b = await page.locator("#submit").screenshot()
        return f"{len(b)} bytes"
    await run_check("element screenshot (clip)", shot_el, R, timeout=30)

    async def cookie():
        await page.click("#cookie-reject")
        return await page.evaluate("!!document.getElementById('cookie')")
    await run_check("click (cookie banner reject)", cookie, R)

    async def fill():
        await page.fill("#name", "Asha Verma")
        v = await page.input_value("#name")
        assert v == "Asha Verma", v
        return v
    await run_check("locator.fill (Input.insertText)", fill, R)

    async def typing():
        await page.click("#email")
        await page.keyboard.type("asha@x")
        await page.wait_for_timeout(500)
        err = await page.text_content("#email-err")
        assert err == "Enter a valid email", repr(err)
        await page.keyboard.type(".com")
        await page.wait_for_timeout(500)
        err2 = await page.text_content("#email-err")
        assert err2 == "", repr(err2)
        return "debounced validation shown then cleared"
    await run_check("keyboard.type + debounced input events", typing, R)

    async def pw_field():
        await page.fill("#password", "test-only-pass")
        s = await page.evaluate(SNAPSHOT_JS)
        assert "test-only-pass" not in s
        return "masked" if "••••" in s else "no value shown"
    await run_check("password masked in snapshot", pw_field, R)

    async def select():
        await page.select_option("#role", "ML Intern")
        return await page.input_value("#role")
    await run_check("select_option", select, R)

    async def check():
        await page.check("#relocate")
        return await page.is_checked("#relocate")
    await run_check("check checkbox", check, R)

    async def radio():
        await page.check("input[value=remote]")
        return await page.is_checked("input[value=remote]")
    await run_check("radio", radio, R)

    async def upload():
        await page.set_input_files("#resume", str(HERE / "fixtures/resume.pdf"))
        return await page.evaluate("document.getElementById('resume').files[0].name")
    await run_check("set_input_files (upload)", upload, R)

    async def lean_after():
        s = await page.evaluate(SNAPSHOT_JS)
        tokens["form_lean_filled"] = s
        return f"{tok(s)} tok"
    await run_check("lean snapshot after fill (values inline)", lean_after, R)

    async def submit():
        await page.click("#submit")
        await page.wait_for_selector("text=Application received", timeout=8000)
        subs = http_json(f"{base}/api/submissions")
        assert subs, "server got nothing"
        last = subs[-1]
        f = last.get("fields", {})
        assert f.get("name") == "Asha Verma", f
        assert f.get("role") == "ML Intern", f
        assert f.get("mode") == "remote", f
        assert last.get("has_file"), "file missing"
        return f"server got name/role/mode/file ({last['ctype']})"
    await run_check("submit form, verified by server", submit, R)

    async def back():
        await page.go_back()
        return await page.title()
    await run_check("go_back", back, R)

    # SPA
    async def spa():
        await page.goto(f"{base}/spa.html")
        s1 = await page.evaluate(SNAPSHOT_JS)
        tokens["spa_lean_text"] = s1
        assert "(custom)" in s1 or "clickable" in s1, s1
        await page.click("text=Choose city")
        await page.click("[role=option] >> text=Mumbai")
        txt = await page.text_content("[role=combobox]")
        assert txt.strip() == "Mumbai", txt
        return "custom combobox via delegated handler ok"
    await run_check("SPA: delegated click + custom combobox", spa, R)

    async def spa_ids():
        btn_id1 = await page.evaluate(SNAPSHOT_JS + ";document.querySelector('[data-act=inc]').dataset.labId")
        await page.click("[data-act=inc]")
        btn_id2 = await page.evaluate(SNAPSHOT_JS + ";document.querySelector('[data-act=inc]').dataset.labId")
        return f"id before={btn_id1} after re-render={btn_id2} -> {'STABLE' if btn_id1 == btn_id2 else 'CHANGED (needs fingerprint matching)'}"
    await run_check("SPA: ID stability across re-render (naive)", spa_ids, R)

    async def spa_route():
        await page.click("nav >> text=Items")
        assert page.url.endswith("#/items"), page.url
        await page.wait_for_selector("li", timeout=5000)
        n = await page.locator("li").count()
        return f"pushState ok, {n} items after delayed fetch"
    await run_check("SPA: pushState route + delayed fetch", spa_route, R)

    async def mutation():
        return await page.evaluate("""new Promise(res => {
            const o = new MutationObserver(m => { o.disconnect(); res(m.length); });
            o.observe(document.body, {childList: true, subtree: true});
            document.body.appendChild(document.createElement('div'));
            setTimeout(() => res('timeout'), 2000);
        })""")
    await run_check("MutationObserver", mutation, R)

    # widgets
    async def dialog():
        await page.goto(f"{base}/widgets.html")
        page.once("dialog", lambda d: asyncio.ensure_future(d.accept()))
        await page.click("#confirm-btn")
        await page.wait_for_timeout(300)
        out = await page.text_content("#out")
        assert out == "confirmed", repr(out)
        return out
    await run_check("native confirm() dialog", dialog, R)

    async def popup():
        async with ctx.expect_page(timeout=8000) as pi:
            await page.click("#popup-btn")
        p2 = await pi.value
        await p2.wait_for_load_state()
        t = await p2.title()
        await p2.close()
        return t
    await run_check("popup / new tab", popup, R)

    async def editable():
        await page.click("#editor")
        await page.keyboard.press("End")
        await page.keyboard.type(" hello")
        t = await page.text_content("#editor")
        assert "hello" in t, t
        return t
    await run_check("contenteditable typing", editable, R)

    async def shadow():
        await page.click("my-card >> #shadow-btn")
        t = await page.evaluate("document.querySelector('my-card').shadowRoot.getElementById('shadow-out').textContent")
        assert t == "shadow clicked", t
        return t
    await run_check("shadow DOM click", shadow, R)

    async def iframe():
        fl = page.frame_locator("#frame")
        await fl.locator("#holder").fill("Test Holder")
        v = await fl.locator("#holder").input_value()
        assert v == "Test Holder", v
        return v
    await run_check("iframe fill", iframe, R)

    async def lean_widgets():
        s = await page.evaluate(SNAPSHOT_JS)
        tokens["widgets_lean_text"] = s
        assert "Shadow button" in s, "shadow element missing"
        assert "[frame]" in s, "iframe element missing"
        return f"{tok(s)} tok, shadow+iframe present"
    await run_check("lean snapshot sees shadow DOM + iframe", lean_widgets, R)

    async def storage():
        st = await ctx.storage_state()
        return f"{len(st.get('cookies', []))} cookies"
    await run_check("storage_state", storage, R)

    async def init_script():
        c2 = await browser.new_context()
        await c2.add_init_script("window.__labInit = 42")
        p = await c2.new_page()
        await p.goto(f"{base}/widgets.html")
        v = await p.evaluate("window.__labInit")
        await c2.close()
        assert v == 42, v
        return v
    await run_check("add_init_script", init_script, R)

    async def block():
        c3 = await browser.new_context()
        hits = []
        async def handler(route):
            hits.append(route.request.url)
            await route.abort()
        await c3.route("**/*.png", handler)
        p = await c3.new_page()
        await p.goto(f"{base}/form.html")
        await p.wait_for_timeout(500)
        nw = await p.evaluate("document.querySelector('img.hero').naturalWidth")
        await c3.close()
        assert hits, "route handler never called"
        assert nw == 0, f"image still loaded ({nw})"
        return f"blocked {len(hits)} image(s)"
    await run_check("request blocking (page.route)", block, R)

    async def memory():
        pages = []
        for path in ["form.html", "spa.html", "widgets.html"]:
            p = await ctx.new_page()
            await p.goto(f"{base}/{path}")
            pages.append(p)
        await asyncio.sleep(1)
        mb = tree_rss_mb(eng.proc.pid)
        for p in pages:
            await p.close()
        return mb
    await run_check("memory (RSS, 4 tabs open)", memory, R)

    await browser.close()
    return R, tokens


async def public_checks(eng: Engine, pw, urls):
    out = {}
    browser = await pw.chromium.connect_over_cdp(eng.endpoint, timeout=15000, **({"headers": eng.headers()} if eng.headers() else {}))
    ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
    page = await ctx.new_page()
    for u in urls:
        rec = {}
        try:
            await page.goto(u, wait_until="load", timeout=30000)
            await page.wait_for_timeout(1000)
            for k, fn in [("lean", lambda: page.evaluate(SNAPSHOT_JS)),
                          ("aria", lambda: page.locator("body").aria_snapshot()),
                          ("html", page.content)]:
                try:
                    s = await asyncio.wait_for(fn(), 30)
                    rec[k] = tok(s)
                    if k == "lean":
                        rec["lean_sample"] = s[:600]
                except Exception as e:
                    rec[k] = f"ERR {type(e).__name__}: {str(e)[:120]}"
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {str(e)[:160]}"
        rec["rss_mb"] = tree_rss_mb(eng.proc.pid)
        out[u] = rec
    await browser.close()
    return out


async def main(mode: str):
    report = {"mode": mode}
    async with async_playwright() as pw:
        chromium_path = pw.chromium.executable_path
        if mode == "fixtures":
            srv_port = free_port()
            srv = subprocess.Popen([sys.executable, "-I", str(HERE / "fixtures/server.py"), str(srv_port)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            wait_port(srv_port)
            base = f"http://127.0.0.1:{srv_port}"
        try:
            for kind in ["obscura", "chromium"]:
                print(f"===== {kind}", file=sys.stderr, flush=True)
                eng = Engine(kind, mode, chromium_path)
                eng.start()
                print(f"started on {eng.endpoint}", file=sys.stderr, flush=True)
                idle = tree_rss_mb(eng.proc.pid)
                try:
                    if mode == "fixtures":
                        R, tokens = await fixture_checks(eng, pw, base)
                        report[kind] = {"idle_rss_mb": idle, "checks": R,
                                        "tokens": {k: (tok(v) if isinstance(v, str) else v) for k, v in tokens.items()}}
                        for k, v in tokens.items():
                            if isinstance(v, str):
                                (RESULTS / f"{kind}_{k}.txt").write_text(v)
                    else:
                        urls = ["https://github.com/h4ckf0r0day/obscura",
                                "https://en.wikipedia.org/wiki/Web_scraping",
                                "https://news.ycombinator.com/"]
                        report[kind] = {"idle_rss_mb": idle, "pages": await public_checks(eng, pw, urls)}
                except Exception as e:
                    report[kind] = {"fatal": f"{type(e).__name__}: {e}"}
                finally:
                    eng.stop()
                    report[kind]["log_tail"] = eng.log[-1500:]
        finally:
            if mode == "fixtures":
                srv.terminate()
    (RESULTS / f"report_{mode}.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2)[:20000])


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "fixtures"))
