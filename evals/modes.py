"""Baseline observation/action modes for the eval agent.

Every mode shares the same session plumbing (active tab tracking, auto-accepted dialogs,
answer tool) and differs only in what the agent sees and how it addresses elements:

- screenshot: sees a viewport PNG after every action, acts by pixel coordinates
- html:       sees full page HTML after every action, acts by CSS selector
- aria:       sees Playwright's aria snapshot after every action, acts by role + name

The lean modes (5, 6) and Playwright MCP (4) plug into the same interface later.
"""
from __future__ import annotations

import base64
from typing import Any

from playwright.async_api import BrowserContext, Page

Block = dict[str, Any]

GOTO = {"name": "goto", "description": "Open a URL (absolute, or a path on the current site).",
        "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"],
                         "additionalProperties": False}}
PRESS = {"name": "press", "description": "Press a key on the focused element, e.g. Enter, Tab, Escape.",
         "input_schema": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"],
                          "additionalProperties": False}}
SCROLL = {"name": "scroll", "description": "Scroll the page.",
          "input_schema": {"type": "object", "properties": {"direction": {"type": "string", "enum": ["down", "up"]}},
                           "required": ["direction"], "additionalProperties": False}}
ANSWER = {"name": "answer", "description": "Finish the task. Give the requested information, or 'done' if the task "
          "was an action.", "input_schema": {"type": "object", "properties": {"text": {"type": "string"}},
                                             "required": ["text"], "additionalProperties": False}}


def _obj(props: dict, req: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": req, "additionalProperties": False}


S = {"type": "string"}


class Session:
    """Tracks the active tab and dialogs for one task run."""

    def __init__(self, ctx: BrowserContext, page: Page, base: str):
        self.ctx, self.page, self.base = ctx, page, base
        self.notes: list[str] = []
        ctx.on("page", self._on_page)
        self._wire(page)

    def _wire(self, page: Page):
        page.on("dialog", self._on_dialog)

    def _on_page(self, page: Page):
        self.page = page
        self._wire(page)
        self.notes.append("A new tab opened and is now active.")

    async def _on_dialog(self, d):
        self.notes.append(f"A browser dialog said {d.message!r} and was accepted.")
        await d.accept()

    def take_notes(self) -> str:
        n, self.notes = " ".join(self.notes), []
        return n

    async def settle(self):
        try:
            await self.page.wait_for_load_state("load", timeout=5000)
        except Exception:
            pass
        await self.page.wait_for_timeout(400)

    def url(self, u: str) -> str:
        return u if u.startswith("http") else self.base + ("" if u.startswith("/") else "/") + u


class Mode:
    name = "base"
    tools: list[dict] = []

    async def observe(self, s: Session) -> list[Block]:
        raise NotImplementedError

    async def act(self, s: Session, name: str, args: dict) -> str:
        p = s.page
        if name == "goto":
            await p.goto(s.url(args["url"]))
        elif name == "press":
            await p.keyboard.press(args["key"])
        elif name == "scroll":
            await p.mouse.wheel(0, 700 if args["direction"] == "down" else -700)
        else:
            return await self.act_specific(s, name, args)
        return "ok"

    async def act_specific(self, s: Session, name: str, args: dict) -> str:
        raise ValueError(f"unknown tool {name}")


class ScreenshotMode(Mode):
    name = "screenshot"
    tools = [
        {"name": "click", "description": "Click at viewport pixel coordinates.",
         "input_schema": _obj({"x": {"type": "integer"}, "y": {"type": "integer"}}, ["x", "y"])},
        {"name": "type", "description": "Type text into the focused element.", "input_schema": _obj({"text": S}, ["text"])},
        {"name": "upload", "description": "Click a file input at coordinates and attach a local file.",
         "input_schema": _obj({"x": {"type": "integer"}, "y": {"type": "integer"}, "path": S}, ["x", "y", "path"])},
        GOTO, PRESS, SCROLL, ANSWER,
    ]

    async def observe(self, s):
        png = await s.page.screenshot()
        return [{"type": "text", "text": f"url: {s.page.url}"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                             "data": base64.b64encode(png).decode()}}]

    async def act_specific(self, s, name, a):
        p = s.page
        if name == "click":
            await p.mouse.click(a["x"], a["y"])
        elif name == "type":
            await p.keyboard.type(a["text"])
        elif name == "upload":
            async with p.expect_file_chooser(timeout=5000) as fc:
                await p.mouse.click(a["x"], a["y"])
            await (await fc.value).set_files(a["path"])
        else:
            raise ValueError(f"unknown tool {name}")
        return "ok"


class HtmlMode(Mode):
    name = "html"
    tools = [
        {"name": "click", "description": "Click the element matching a CSS selector.",
         "input_schema": _obj({"selector": S}, ["selector"])},
        {"name": "fill", "description": "Fill an input matching a CSS selector.",
         "input_schema": _obj({"selector": S, "value": S}, ["selector", "value"])},
        {"name": "select", "description": "Choose an option (by label) in a <select>.",
         "input_schema": _obj({"selector": S, "value": S}, ["selector", "value"])},
        {"name": "check", "description": "Check a checkbox or radio button.", "input_schema": _obj({"selector": S}, ["selector"])},
        {"name": "upload", "description": "Attach a local file to a file input.",
         "input_schema": _obj({"selector": S, "path": S}, ["selector", "path"])},
        GOTO, PRESS, SCROLL, ANSWER,
    ]

    async def observe(self, s):
        return [{"type": "text", "text": f"url: {s.page.url}\n{await s.page.content()}"}]

    async def act_specific(self, s, name, a):
        p, sel = s.page, a.get("selector")
        loc = p.locator(sel).first
        if name == "click":
            await loc.click(timeout=5000)
        elif name == "fill":
            await loc.fill(a["value"], timeout=5000)
        elif name == "select":
            await loc.select_option(label=a["value"], timeout=5000)
        elif name == "check":
            await loc.check(timeout=5000)
        elif name == "upload":
            await loc.set_input_files(a["path"], timeout=5000)
        else:
            raise ValueError(f"unknown tool {name}")
        return "ok"


ROLE = {"type": "string", "description": "ARIA role, e.g. button, link, textbox, combobox, checkbox, radio"}


class AriaMode(Mode):
    name = "aria"
    tools = [
        {"name": "click", "description": "Click the element with this ARIA role and accessible name.",
         "input_schema": _obj({"role": ROLE, "name": S}, ["role", "name"])},
        {"name": "fill", "description": "Fill the textbox with this accessible name.",
         "input_schema": _obj({"name": S, "value": S}, ["name", "value"])},
        {"name": "select", "description": "Choose an option (by label) in the combobox/select with this name.",
         "input_schema": _obj({"name": S, "value": S}, ["name", "value"])},
        {"name": "check", "description": "Check the checkbox or radio with this accessible name.",
         "input_schema": _obj({"role": ROLE, "name": S}, ["role", "name"])},
        {"name": "upload", "description": "Attach a local file to the file input with this label.",
         "input_schema": _obj({"name": S, "path": S}, ["name", "path"])},
        GOTO, PRESS, SCROLL, ANSWER,
    ]

    async def observe(self, s):
        snap = await s.page.locator("body").aria_snapshot()
        return [{"type": "text", "text": f"url: {s.page.url}\n{snap}"}]

    async def act_specific(self, s, name, a):
        p = s.page
        if name == "click":
            await p.get_by_role(a["role"], name=a["name"]).first.click(timeout=5000)
        elif name == "fill":
            await p.get_by_role("textbox", name=a["name"]).first.fill(a["value"], timeout=5000)
        elif name == "select":
            await p.get_by_role("combobox", name=a["name"]).first.select_option(label=a["value"], timeout=5000)
        elif name == "check":
            await p.get_by_role(a["role"], name=a["name"]).first.check(timeout=5000)
        elif name == "upload":
            await p.get_by_label(a["name"]).first.set_input_files(a["path"], timeout=5000)
        else:
            raise ValueError(f"unknown tool {name}")
        return "ok"


MODES: dict[str, type[Mode]] = {m.name: m for m in [ScreenshotMode, HtmlMode, AriaMode]}
