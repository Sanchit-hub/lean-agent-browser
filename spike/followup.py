"""Isolate each Obscura failure from compat.py and try workarounds (Obscura only, sandboxed)."""
import asyncio
import json
import subprocess
import sys
import urllib.request

from playwright.async_api import async_playwright

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from compat import HERE, Engine, free_port, http_json, run_check, wait_port  # noqa: E402


async def main():
    R = []
    srv_port = free_port()
    srv = subprocess.Popen([sys.executable, "-I", str(HERE / "fixtures/server.py"), str(srv_port)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_port(srv_port)
    base = f"http://127.0.0.1:{srv_port}"
    eng = Engine("obscura", "fixtures")
    eng.start()
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(eng.endpoint, headers=eng.headers())
            ctx = await browser.new_context()
            page = await ctx.new_page()
            reset = lambda: urllib.request.urlopen(f"{base}/api/reset").read()

            async def sub_multipart_click():
                reset()
                await page.goto(f"{base}/form.html")
                await page.fill("#name", "A"); await page.fill("#email", "a@b.co")
                await page.click("#submit")
                await page.wait_for_timeout(1500)
                return f"server got {len(http_json(base + '/api/submissions'))} submission(s); title now {await page.title()!r}"
            await run_check("submit multipart form by clicking button (no file)", sub_multipart_click, R)

            async def sub_js_submit():
                reset()
                await page.goto(f"{base}/form.html")
                await page.fill("#name", "A")
                await page.evaluate("document.getElementById('apply').requestSubmit()")
                await page.wait_for_timeout(1500)
                return f"server got {len(http_json(base + '/api/submissions'))}; title {await page.title()!r}"
            await run_check("submit multipart via requestSubmit()", sub_js_submit, R)

            async def sub_urlencoded():
                reset()
                await page.goto(f"{base}/frame-inner.html")
                await page.fill("#holder", "B")
                await page.click("#pay")
                await page.wait_for_timeout(1500)
                subs = http_json(base + "/api/submissions")
                return f"server got {subs}; title {await page.title()!r}"
            await run_check("submit urlencoded form by click", sub_urlencoded, R)

            async def sub_enter():
                reset()
                await page.goto(f"{base}/frame-inner.html")
                await page.fill("#holder", "C")
                await page.press("#holder", "Enter")
                await page.wait_for_timeout(1500)
                return f"server got {len(http_json(base + '/api/submissions'))}"
            await run_check("submit by pressing Enter", sub_enter, R)

            async def upload_cdp():
                await page.goto(f"{base}/form.html")
                cdp = await ctx.new_cdp_session(page)
                doc = await cdp.send("DOM.getDocument")
                q = await cdp.send("DOM.querySelector", {"nodeId": doc["root"]["nodeId"], "selector": "#resume"})
                await cdp.send("DOM.setFileInputFiles", {"nodeId": q["nodeId"], "files": [str(HERE / "fixtures/resume.pdf")]})
                return await page.evaluate("document.getElementById('resume').files.length")
            await run_check("upload via CDP DOM.setFileInputFiles", upload_cdp, R)

            async def shadow_js():
                await page.goto(f"{base}/widgets.html")
                await page.evaluate("document.querySelector('my-card').shadowRoot.getElementById('shadow-btn').click()")
                return await page.evaluate("document.querySelector('my-card').shadowRoot.getElementById('shadow-out').textContent")
            await run_check("shadow DOM click via JS el.click()", shadow_js, R)

            async def shadow_mouse():
                await page.goto(f"{base}/widgets.html")
                r = await page.evaluate("JSON.stringify(document.querySelector('my-card').shadowRoot.getElementById('shadow-btn').getBoundingClientRect())")
                r = json.loads(r)
                await page.mouse.click(r["x"] + r["width"] / 2, r["y"] + r["height"] / 2)
                return await page.evaluate("document.querySelector('my-card').shadowRoot.getElementById('shadow-out').textContent")
            await run_check("shadow DOM click via mouse coordinates", shadow_mouse, R)

            async def shadow_data_id():
                await page.goto(f"{base}/widgets.html")
                await page.evaluate("document.querySelector('my-card').shadowRoot.getElementById('shadow-btn').dataset.labId='99'")
                await page.locator("[data-lab-id='99']").click(timeout=5000)
                return "ok"
            await run_check("shadow DOM click via Playwright css [data-lab-id]", shadow_data_id, R, timeout=8)

            async def frames():
                await page.goto(f"{base}/widgets.html")
                return [f.url for f in page.frames]
            await run_check("page.frames lists iframe", frames, R)

            async def iframe_js():
                await page.goto(f"{base}/widgets.html")
                await page.wait_for_timeout(300)
                await page.evaluate("""(() => { const d = document.getElementById('frame').contentDocument;
                    const i = d.getElementById('holder'); i.focus(); i.value = 'X';
                    i.dispatchEvent(new Event('input', {bubbles:true})); })()""")
                return await page.evaluate("document.getElementById('frame').contentDocument.getElementById('holder').value")
            await run_check("iframe fill via JS contentDocument", iframe_js, R)

            async def iframe_mouse_type():
                await page.goto(f"{base}/widgets.html")
                await page.wait_for_timeout(300)
                r = json.loads(await page.evaluate("""(() => { const f = document.getElementById('frame').getBoundingClientRect();
                    const i = document.getElementById('frame').contentDocument.getElementById('holder').getBoundingClientRect();
                    return JSON.stringify({x: f.x + i.x + i.width/2, y: f.y + i.y + i.height/2}); })()"""))
                await page.mouse.click(r["x"], r["y"])
                await page.keyboard.type("Y")
                return await page.evaluate("document.getElementById('frame').contentDocument.getElementById('holder').value")
            await run_check("iframe fill via mouse click + keyboard", iframe_mouse_type, R)

            async def ce_insert():
                await page.goto(f"{base}/widgets.html")
                await page.focus("#editor")
                await page.keyboard.insert_text(" hi")
                t1 = await page.text_content("#editor")
                await page.evaluate("document.getElementById('editor').focus(); document.execCommand('insertText', false, ' ex')")
                t2 = await page.text_content("#editor")
                await page.evaluate("const e=document.getElementById('editor'); e.textContent += ' js'; e.dispatchEvent(new InputEvent('input',{bubbles:true}))")
                t3 = await page.text_content("#editor")
                return f"insert_text→{t1!r} | execCommand→{t2!r} | textContent→{t3!r}"
            await run_check("contenteditable: insert_text / execCommand / textContent", ce_insert, R)

            async def popup_targets():
                await page.goto(f"{base}/widgets.html")
                before = len(ctx.pages)
                r = await page.evaluate("(() => { const w = window.open('/form.html', '_blank'); return w ? 'window object' : 'null'; })()")
                await page.wait_for_timeout(1500)
                cdp = await browser.new_browser_cdp_session()
                t = await cdp.send("Target.getTargets")
                return f"window.open returned {r}; ctx.pages {before}->{len(ctx.pages)}; targets={[x.get('url') for x in t.get('targetInfos', [])]}"
            await run_check("window.open → new target?", popup_targets, R)

            async def link_blank():
                await page.set_content(f'<a id="l" href="{base}/form.html" target="_blank">x</a>')
                await page.click("#l")
                await page.wait_for_timeout(1500)
                return f"ctx.pages={len(ctx.pages)}, current url={page.url}"
            await run_check("target=_blank link", link_blank, R)

            async def block_server_side():
                reset()
                c3 = await browser.new_context()
                await c3.route("**/*.png", lambda r: r.abort())
                p = await c3.new_page()
                await p.goto(f"{base}/form.html")
                await p.wait_for_timeout(800)
                nw = await p.evaluate("document.querySelector('img.hero').naturalWidth")
                cmp = await p.evaluate("document.querySelector('img.hero').complete")
                await c3.close()
                return f"naturalWidth={nw}, complete={cmp}"
            await run_check("route abort: image state", block_server_side, R)

            async def back_after_post():
                await page.goto(f"{base}/frame-inner.html")
                await page.goto(f"{base}/form.html")
                await page.go_back()
                return page.url
            await run_check("go_back after GET nav", back_after_post, R)

            await browser.close()
    finally:
        eng.stop()
        srv.terminate()
    print(eng.log[-1500:], file=sys.stderr)


asyncio.run(main())
