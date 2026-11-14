"""Measure lean snapshot vs Playwright aria snapshot on public pages (read-only GETs).
Token counts are a proxy (tiktoken o200k) because no Anthropic credentials are configured;
ratios are reliable, absolute numbers are approximate."""
import asyncio
import sys
from pathlib import Path

import tiktoken

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lean_browser.engine import BrowserManager  # noqa: E402
from lean_browser.snapshot import Snapshotter  # noqa: E402

URLS = ["https://github.com/h4ckf0r0day/obscura", "https://en.wikipedia.org/wiki/Web_scraping",
        "https://news.ycombinator.com/"]
enc = tiktoken.get_encoding("o200k_base")
tok = lambda s: len(enc.encode(s))


async def main():
    for prefer in ("obscura", "chromium"):
        async with BrowserManager(prefer=prefer) as bm:
            for u in URLS:
                try:
                    tab = await bm.open(u)
                    await tab.page.wait_for_timeout(800)
                    sn = Snapshotter(timeout_s=10)
                    s = await sn.take(tab.page, engine=tab.header)
                    out = sn.render(s)
                    full = sn.render(s, budget=100000, skip_unchanged=False)
                    r = await sn.take(tab.page, mode="read")
                    aria = await tab.page.locator("body").aria_snapshot()
                    print(f"{prefer:9} {tab.engine:9} {u[:45]:45} ms={s.ms:<5} prof={s.data.get('prof')} "
                          f"lean={tok(out)} lean_unbudgeted={tok(full)} read={tok(sn.render(r, budget=100000))} aria={tok(aria)}")
                    if u.endswith("obscura") and prefer == "obscura":
                        print(out[:1500])
                except Exception as e:
                    print(prefer, u, "ERROR", type(e).__name__, str(e)[:150])


asyncio.run(main())
