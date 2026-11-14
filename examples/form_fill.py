"""Fill and submit a whole form in one call, then read the server's echo.

Uses httpbin.org's public test form, which just echoes what it receives.

    .venv/bin/python examples/form_fill.py
"""
import asyncio
import json
import re

from lean_browser import LeanBrowser


def field(snapshot: str, pattern: str) -> int:
    return int(re.search(r"(\d+): " + pattern, snapshot).group(1))


async def main():
    async with LeanBrowser() as browser:
        form = await browser.open("https://httpbin.org/forms/post")
        print(form, "\n")
        result = await browser.fill_form({
            field(form, 'textbox "Customer name'): "Asha Verma",
            field(form, 'textbox "Telephone'): "9876543210",
            field(form, 'textbox "E-mail address'): "asha@example.com",
            field(form, 'radiogroup "Pizza Size'): "Medium",
            field(form, 'checkbox "Mushroom'): "on",
            field(form, 'textbox "Delivery instructions'): "Ring the bell twice",
        }, submit=True)
        print("after submit:", result.splitlines()[0])
        # httpbin answers with JSON; read mode returns the page text, so parse what the server received.
        echo = await browser.snapshot(mode="read", budget=3000)
        print("server received:", json.loads(echo.split("\n", 1)[1])["form"])


asyncio.run(main())
