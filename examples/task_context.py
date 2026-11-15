"""Task-aware context: ask for exactly the fields a task needs, get sourced records, decide in your code.

The browser does not interpret the goal. It returns one record per product with the requested fields,
where it found them, and which ones are missing. The comparison logic stays with the caller.

    .venv/bin/python examples/task_context.py      (uses the local fixture site, run from the repo)
"""
import asyncio
import json
import re
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from evals.fixtures.server import serve  # noqa: E402
from lean_browser import Config, LeanBrowser  # noqa: E402

GOAL = "Compare the three cheapest RTX 4060 laptops with at least 16 GB RAM"


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


async def main():
    port = free_port(); srv = serve(port)
    async with LeanBrowser(Config(allow_private_network=True)) as browser:
        await browser.open(f"http://127.0.0.1:{port}/laptops.html")
        ctx = await browser.context(GOAL, ["product_name", "price", "gpu", "ram", "availability"], max_tokens=1200)
        print(f"{ctx['returned']}/{ctx['total']} records, ~{ctx['estimate']['tokens']} tokens ({ctx['estimate']['method']})")

        def num(x):
            return int(re.sub(r"\D", "", x)) if x else None
        ok, skipped = [], []
        for r in ctx["records"]:
            if r.get("_missing"):
                skipped.append(f"{r['product_name']}: missing {', '.join(r['_missing'])}")
                continue
            if r["gpu"] == "RTX 4060" and num(r["ram"]) >= 16 and "out of stock" not in r["availability"].lower():
                ok.append(r)
        shortlist = sorted(ok, key=lambda r: num(r["price"]))[:3]
        print("\nShortlist:")
        for r in shortlist:
            print(f"  {r['product_name']:<10} {r['price']:>10}  {r['ram']:>6}  {r['availability']:<12} "
                  f"(source: {ctx['source']['url']} item {r['_ref']['item']}, link id {r['_ref']['ids'][0]})")
        print("\nNot comparable (reported, not guessed):\n  " + "\n  ".join(skipped))
    srv.shutdown()


asyncio.run(main())
