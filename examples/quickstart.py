"""Quickstart: open a page, look at the compact snapshot, search it, and follow a link.

    .venv/bin/python examples/quickstart.py
"""
import asyncio
import re

from lean_browser import LeanBrowser


async def main():
    async with LeanBrowser() as browser:
        page = await browser.open("https://news.ycombinator.com/")
        print(page[:800], "\n...")

        # The front page table is collapsed into one line; find() searches inside it.
        hits = await browser.snapshot(find="comments")
        print("\nfind('comments'):\n" + "\n".join(hits.splitlines()[:3]))

        # Follow the "new" link by its id and print only the first lines of the result.
        new_id = int(re.search(r'(\d+): link "new"', page).group(1))
        print("\n" + "\n".join((await browser.act("click", new_id)).splitlines()[:4]))


asyncio.run(main())
