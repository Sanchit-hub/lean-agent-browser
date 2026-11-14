"""Two last Obscura checks: multipart submit by click (banner dismissed), and upload with --allow-file-access."""
import asyncio
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent))
import compat  # noqa: E402
from compat import HERE, Engine, free_port, http_json, run_check, wait_port  # noqa: E402


class FileEngine(Engine):
    """Obscura with --allow-file-access. The sandbox still blocks $HOME reads, so only files
    copied into the sandbox temp dir can be uploaded."""
    def start(self):
        orig = compat.OBSCURA
        super_start = Engine.start
        # inject flag by wrapping Popen args
        real_popen = subprocess.Popen
        def popen(args, **kw):
            if args and args[0] == "sandbox-exec":
                args = args + ["--allow-file-access"]
            return real_popen(args, **kw)
        subprocess.Popen = popen
        try:
            super_start(self)
        finally:
            subprocess.Popen = real_popen


async def main():
    R = []
    srv_port = free_port()
    srv = subprocess.Popen([sys.executable, "-I", str(HERE / "fixtures/server.py"), str(srv_port)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_port(srv_port)
    base = f"http://127.0.0.1:{srv_port}"
    eng = FileEngine("obscura", "fixtures")
    eng.start()
    inside = Path(eng.tmp) / "uploads"
    inside.mkdir()
    shutil.copy(HERE / "fixtures/resume.pdf", inside / "resume.pdf")
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(eng.endpoint, headers=eng.headers())
            ctx = await browser.new_context()
            page = await ctx.new_page()
            reset = lambda: urllib.request.urlopen(f"{base}/api/reset").read()

            async def multipart_click():
                reset()
                await page.goto(f"{base}/form.html")
                await page.click("#cookie-reject")
                await page.fill("#name", "A")
                await page.click("#submit", timeout=5000)
                await page.wait_for_timeout(1500)
                return f"server got {len(http_json(base + '/api/submissions'))}; title {await page.title()!r}"
            await run_check("multipart submit by click (banner dismissed)", multipart_click, R)

            async def multipart_click_banner():
                reset()
                await page.goto(f"{base}/form.html")
                await page.fill("#name", "A")
                try:
                    await page.click("#submit", timeout=3000)
                    return "clicked"
                except Exception as e:
                    return "blocked: " + str(e).splitlines()[-1][:150]
            await run_check("click submit while banner present (actionability)", multipart_click_banner, R)

            async def upload_inside():
                reset()
                await page.goto(f"{base}/form.html")
                await page.click("#cookie-reject")
                cdp = await ctx.new_cdp_session(page)
                doc = await cdp.send("DOM.getDocument")
                q = await cdp.send("DOM.querySelector", {"nodeId": doc["root"]["nodeId"], "selector": "#resume"})
                await cdp.send("DOM.setFileInputFiles", {"nodeId": q["nodeId"], "files": [str((inside / "resume.pdf").resolve())]})
                n = await page.evaluate("document.getElementById('resume').files.length")
                await page.fill("#name", "A")
                await page.evaluate("document.getElementById('apply').requestSubmit()")
                await page.wait_for_timeout(1500)
                subs = http_json(base + "/api/submissions")
                return f"files.length={n}; server record={subs[-1] if subs else None}"
            await run_check("upload (file inside sandbox dir) + submit", upload_inside, R)

            async def upload_home_blocked():
                await page.goto(f"{base}/form.html")
                cdp = await ctx.new_cdp_session(page)
                doc = await cdp.send("DOM.getDocument")
                q = await cdp.send("DOM.querySelector", {"nodeId": doc["root"]["nodeId"], "selector": "#resume"})
                secret = str(Path.home() / ".zshrc")
                try:
                    await cdp.send("DOM.setFileInputFiles", {"nodeId": q["nodeId"], "files": [secret]})
                    size = await page.evaluate("document.getElementById('resume').files[0] && document.getElementById('resume').files[0].size")
                    return f"accepted path, size={size} (size 0/None means sandbox blocked the read)"
                except Exception as e:
                    return "rejected: " + str(e)[:150]
            await run_check("upload of ~/.zshrc must be blocked by sandbox", upload_home_blocked, R)

            await browser.close()
    finally:
        eng.stop()
        srv.terminate()


asyncio.run(main())
