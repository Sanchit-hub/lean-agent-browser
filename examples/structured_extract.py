"""Pull a table out of a page as JSON, with no LLM involved.

    .venv/bin/python examples/structured_extract.py
"""
import asyncio
import json

from lean_browser import LeanBrowser


async def main():
    async with LeanBrowser() as browser:
        await browser.open("https://en.wikipedia.org/wiki/List_of_largest_cities", mode="read", block=True)
        table = await browser.extract("table")
        print(f"{table['total_rows']} rows; header row: {table['headers']}")
        for row in table["rows"][:3]:
            print(json.dumps(row, ensure_ascii=False))


asyncio.run(main())
