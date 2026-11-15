"""Engine compatibility matrix: run the spike's failure cases directly against each pinned Obscura
version (no routing, no fallback) and print a markdown table.

    .venv/bin/python scripts/obscura_matrix.py 0.2.6 0.2.7
"""
import asyncio
import importlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from evals.fixtures.server import serve  # noqa: E402
from tests.test_fixtures import _free_port  # noqa: E402

RESUME = str(ROOT / "evals/fixtures/site/resume.pdf")


def state(base):
    return json.loads(urllib.request.urlopen(base + "/api/state").read())


async def checks(version: str, base: str) -> dict:
    os.environ["LEANB_OBSCURA_VERSION"] = version
    import lean_browser.engine as eng
    importlib.reload(eng)
    from playwright.async_api import async_playwright
    proc = eng.ObscuraProcess(eng.find_obscura(), allow_private_network=True)
    proc.start()
    R = {}

    async def run(name, fn, t=12):
        try:
            R[name] = await asyncio.wait_for(fn(), t)
        except Exception as e:
            R[name] = f"FAIL ({type(e).__name__})"

    try:
        async with async_playwright() as pw:
            b = await pw.chromium.connect_over_cdp(proc.endpoint, headers=proc.headers)
            ctx = await b.new_context()
            p = await ctx.new_page()

            async def upload():
                urllib.request.urlopen(base + "/api/reset").read()
                await p.goto(base + "/apply.html")
                await p.set_input_files("input[type=file]", RESUME)
                await p.fill("input[name=name]", "A")
                await p.evaluate("document.querySelector('form').requestSubmit()")
                await p.wait_for_timeout(1200)
                s = state(base)["submissions"]
                return "ok" if s and s[-1]["has_file"] else f"FAIL (file not sent; {s[-1]['ctype'] if s else 'no submission'})"
            await run("file upload in multipart form", upload)

            async def shadow():
                await p.goto(base + "/widgets.html")
                await p.click("my-card >> #shadow-btn", timeout=4000)
                return "ok"
            await run("Playwright locator inside shadow DOM", shadow)

            async def frame():
                await p.goto(base + "/checkout.html")
                await p.frame_locator("iframe").locator("input[name=holder]").fill("X", timeout=4000)
                return "ok"
            await run("Playwright frame_locator (same-origin iframe)", frame)

            async def editable():
                await p.goto(base + "/comment.html")
                await p.click("#ed")
                await p.keyboard.type("hi")
                t = await p.text_content("#ed")
                return "ok" if "hi" in (t or "") else "FAIL (typing ignored)"
            await run("typing into contenteditable", editable)

            async def popup():
                await p.goto(base + "/widgets.html")
                async with ctx.expect_page(timeout=4000):
                    await p.click("#popup-btn")
                return "ok"
            await run("window.open popup", popup)

            async def tables():
                await p.goto(base + "/orders.html")
                n = await p.evaluate("document.querySelector('table').rows.length")
                return "ok" if n == 11 else f"FAIL ({n})"
            await run("table.rows / cells", tables)

            async def props():
                await p.goto(base + "/apply.html")
                r = await p.evaluate("[document.querySelector('input[name=name]').required, document.querySelector('img').alt]")
                return "ok" if r == [True, "Office"] else f"FAIL ({r})"
            await run("el.required / img.alt", props)

            async def dialog():
                await p.goto(base + "/todo.html")
                seen = []
                p.once("dialog", lambda d: (seen.append(d.message), asyncio.ensure_future(d.dismiss())))
                await p.click("#clear")
                await p.wait_for_timeout(500)
                return "ok" if seen else "FAIL (no dialog event)"
            await run("CDP dialog events", dialog)

            async def styles():
                await p.goto(base + "/big.html")
                ms = await p.evaluate("""() => { const all = [...document.querySelectorAll('*')]; const t0 = performance.now();
                    all.forEach(e => { const c = getComputedStyle(e); c.display; c.visibility; c.opacity; c.contentVisibility; });
                    return Math.round(performance.now() - t0); }""")
                return f"{ms} ms"
            await run("4 computed-style props on 6k elements", styles, 60)

            async def halley():
                t0 = time.time()
                await p.goto("https://en.wikipedia.org/wiki/Halley%27s_Comet", timeout=20000)
                await p.wait_for_timeout(1500)
                await asyncio.wait_for(p.evaluate("1+1"), 5)
                return f"ok ({time.time() - t0:.1f}s)"
            await run("Wikipedia Halley page stays responsive", halley, 40)
    finally:
        proc.stop()
    return R


async def main(versions):
    port = _free_port()
    srv = serve(port)
    base = f"http://127.0.0.1:{port}"
    results = {v: await checks(v, base) for v in versions}
    srv.shutdown()
    rows = list(next(iter(results.values())))
    print("| Check | " + " | ".join(f"Obscura {v}" for v in versions) + " |")
    print("|---|" + "---|" * len(versions))
    for r in rows:
        print(f"| {r} | " + " | ".join(str(results[v].get(r)) for v in versions) + " |")


asyncio.run(main(sys.argv[1:] or ["0.2.6", "0.2.7"]))
