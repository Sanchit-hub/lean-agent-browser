"""Tool layer: schema budget, LeanBrowser.call, extract, screenshot, MCP stdio round-trip, CLI,
and the lean eval loop with a scripted (offline) client."""
import asyncio
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest
import tiktoken

from evals import runner
from evals.fixtures.server import serve
from evals.tasks import BY_ID
from lean_browser.tools import TOOLS, Config, LeanBrowser
from tests.test_fixtures import _free_port
from tests.test_runner import FakeClient

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "evals/fixtures/site"
ENV = dict(os.environ)  # lean_browser (imported via conftest) already set PLAYWRIGHT_BROWSERS_PATH


@pytest.fixture(scope="module")
def base():
    port = _free_port()
    srv = serve(port)
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


def state(base):
    return json.loads(urllib.request.urlopen(base + "/api/state").read())


def test_tool_schema_budget():
    # Proxy count (tiktoken o200k). Measured 2026-11-15 with claude -p: 663 proxy tokens = ~1,550 real
    # Claude tokens of tool definitions per request (Playwright MCP ~7,100; agent-browser ~31,600).
    # Budget raised from 700 to 750 on purpose (maintainer decision, 2026-11-18) for the optional `key` on act and
    # fill_form (cross-session duplicate guard): proxy 699 -> 724. Measured with claude -p (sonnet, 3 runs, the
    # input-token difference against no MCP server): ~1,654 -> ~1,722 real tokens, +68 per request. The headroom
    # to 750 is for one more small, justified field, not for longer descriptions.
    n = len(tiktoken.get_encoding("o200k_base").encode(json.dumps(TOOLS)))
    assert len(TOOLS) == 7
    assert n <= 750, f"tool schemas ≈ {n} proxy tokens (budget 750 ≈ 1.75k real Claude tokens)"


@pytest.fixture
async def lb(base):
    urllib.request.urlopen(base + "/api/reset").read()
    async with LeanBrowser(Config(allow_private_network=True, allowed_upload_dirs=[str(SITE)])) as b:
        yield b


async def test_call_flow_and_untrusted_wrapper(lb, base):
    out = (await lb.call("open", {"url": base + "/login.html"}))[0]
    assert out.startswith('<page untrusted="true">') and out.endswith("</page>")
    out2 = (await lb.call("fill_form", {"fields": {"9": "demo", "10": "demo-pass-123"}, "submit": True}))[0]
    assert "Welcome back, demo" in out2
    assert state(base)["submissions"][-1]["fields"]["ok"] is True


async def test_errors_are_strings_not_exceptions(lb, base):
    assert (await lb.call("act", {"action": "click", "id": 5}))[0].startswith("Error: no page open")
    await lb.call("open", {"url": base + "/login.html"})
    assert (await lb.call("act", {"action": "click", "id": 999}))[0].startswith("Error: id 999 not found")
    assert (await lb.call("act", {"action": "teleport"}))[0].startswith("Error:")
    assert (await lb.call("nope", {}))[0].startswith("Error: unknown tool")


async def test_allowed_domains(base):
    async with LeanBrowser(Config(allow_private_network=True, allowed_domains=["example.com"])) as b:
        assert (await b.call("open", {"url": base + "/login.html"}))[0] == "Error: 127.0.0.1 is not in allowed_domains"


async def test_extract_table_list_form(lb, base):
    await lb.call("open", {"url": base + "/orders.html"})
    t = json.loads((await lb.call("extract", {"kind": "table"}))[0].split("\n", 1)[1].rsplit("\n", 1)[0])
    assert t["headers"] == ["Order", "Customer", "Amount", "Status"] and len(t["rows"]) == 10
    assert t["rows"][0]["Order"] == "ORD-1000"
    await lb.call("open", {"url": base + "/search.html?q=rust"})
    l = json.loads((await lb.call("extract", {}))[0].split("\n", 1)[1].rsplit("\n", 1)[0])
    assert l["kind"] == "list" and len(l["items"]) == 10 and l["items"][0]["links"][0]["text"].startswith("Rust guide")
    await lb.call("open", {"url": base + "/signup.html"})
    f = json.loads((await lb.call("extract", {"kind": "form"}))[0].split("\n", 1)[1].rsplit("\n", 1)[0])
    names = [x["name"] for x in f["fields"]]
    assert "Email" in names and all("id" in x for x in f["fields"])


async def test_screenshot_element_and_viewport(lb, base):
    await lb.call("open", {"url": base + "/login.html"})
    full = (await lb.call("screenshot", {}))[0]
    crop = (await lb.call("screenshot", {"id": 11}))[0]
    assert isinstance(full, bytes) and full[:4] == b"\x89PNG"
    assert isinstance(crop, bytes) and len(crop) < len(full)


async def test_mcp_stdio_round_trip(base):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    params = StdioServerParameters(command=str(ROOT / ".venv/bin/leanb"), args=["--allow-private-network", "mcp"], env=ENV)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as cs:
            await cs.initialize()
            tools = await cs.list_tools()
            assert sorted(t.name for t in tools.tools) == ["act", "extract", "fill_form", "memory", "open", "screenshot", "snapshot"]
            res = await cs.call_tool("open", {"url": base + "/login.html"})
            assert "textbox \"Username\"" in res.content[0].text and not res.is_error
            res = await cs.call_tool("act", {"action": "click", "id": 4242})
            assert res.is_error and "not found" in res.content[0].text
            res = await cs.call_tool("screenshot", {})
            assert res.content[0].type == "image"


def test_cli_open(base):
    out = subprocess.run([str(ROOT / ".venv/bin/leanb"), "--allow-private-network", "open", base + "/login.html"],
                         capture_output=True, text=True, env=ENV, timeout=60)
    assert out.returncode == 0, out.stderr
    assert 'textbox "Username"*' in out.stdout


def test_cli_shell(base):
    script = "fill 9=demo 10=demo-pass-123 --submit\nquit\n"
    out = subprocess.run([str(ROOT / ".venv/bin/leanb"), "--allow-private-network", "shell", base + "/login.html"],
                         input=script, capture_output=True, text=True, env=ENV, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "Welcome back, demo" in out.stdout


@pytest.mark.parametrize("mode", ["lean", "lean-escalate"])
async def test_lean_eval_loop_offline(base, mode):
    script = [("fill_form", {"fields": {"9": "demo", "10": "demo-pass-123"}, "submit": True}), ("answer", {"text": "done"})]
    client = FakeClient(script)
    res = await runner.run_lean_task(client, base, BY_ID["login"], mode, 1, False, lambda r: None)
    assert res.success, res.reason
    assert res.steps == 2 and res.input_tokens == 200
    first = client.seen[0]
    assert {t["name"] for t in first["tools"]} == {"open", "snapshot", "act", "fill_form", "extract", "memory", "screenshot", "answer"}
    assert "open() result:" in first["messages"][0]["content"]


async def test_lean_escalate_appends_full_snapshot(base):
    client = FakeClient([("act", {"action": "press", "id": 9, "value": "Shift"}), ("answer", {"text": "done"})])
    await runner.run_lean_task(client, base, BY_ID["login"], "lean-escalate", 1, False, lambda r: None)
    msgs = client.seen[-1]["messages"]  # live list: also holds the later answer turn
    results = [m["content"][0]["content"] for m in msgs if m["role"] == "user" and isinstance(m["content"], list)
               and isinstance(m["content"][0].get("content"), list)]
    assert any("[auto-escalated] snapshot(mode=full)" in b.get("text", "") for b in results[0])


PWMCP = ROOT / ".vendor/playwright-mcp/node_modules/@playwright/mcp/cli.js"


@pytest.mark.skipif(not PWMCP.exists(), reason="playwright-mcp not installed")
async def test_playwright_mcp_baseline_offline(base):
    tools = await runner.pwmcp_tools()
    names = {t["name"] for t in tools}
    assert {"browser_navigate", "browser_snapshot", "browser_click", "browser_type"} <= names
    client = FakeClient([("answer", {"text": "It was completed in 1931."})])
    res = await runner.run_pwmcp_task(client, base, BY_ID["article"], "playwright-mcp", 1, False, lambda r: None)
    assert res.success, res.reason
    first = client.seen[0]["messages"][0]["content"]
    assert "browser_navigate result:" in first and "Halden" in first



async def test_memory_keeps_facts_with_provenance_across_navigation(lb, base):
    assert (await lb.call("memory", {"action": "list"}))[0] == '<page untrusted="true">\nmemory is empty\n</page>' \
        or (await lb.call("memory", {"action": "list"}))[0] == "memory is empty"
    await lb.open(base + "/orders.html")
    await lb.remember("cheapest_order", "ORD-1012 for ₹254")
    await lb.open(base + "/login.html")
    m = await lb.recall("cheapest_order")
    assert m["value"] == "ORD-1012 for ₹254" and m["source"]["url"].endswith("/orders.html")
    assert m["source"]["title"].startswith("Orders")
    listed = (await lb.call("memory", {"action": "list"}))[0]
    assert "cheapest_order = ORD-1012" in listed and "/orders.html" in listed
    assert (await lb.call("memory", {"action": "get", "key": "nope"}))[0].startswith("Error: no memory 'nope'")
    assert "deleted" in (await lb.call("memory", {"action": "delete", "key": "cheapest_order"}))[0]
    assert (await lb.recall()) == {}


async def test_private_network_error_says_how_to_allow_it():
    from lean_browser.tools import Config, LeanBrowser
    async with LeanBrowser(Config(allow_private_network=False)) as lb:
        out = await lb.call("open", {"url": "http://localhost:8123/"})
    assert out[0].startswith("Error: blocked: localhost is a private-network address"), out
    assert "allow_private_network = true" in out[0]


async def test_concurrent_python_calls_do_not_mix_pages(base):
    """asyncio.gather on one LeanBrowser used to interleave navigations: both calls got the last page and
    Obscura's navigation failed. Calls are serialized now, and each gets its own page."""
    from lean_browser.tools import Config, LeanBrowser
    async with LeanBrowser(Config(allow_private_network=True)) as lb:
        a, b = await asyncio.gather(lb.call("open", {"url": base + "/signup.html"}), lb.call("open", {"url": base + "/todo.html"}))
    assert "/signup.html | " in a[0] and "/todo.html | " in b[0], (a[0][:200], b[0][:200])
    assert "navigation failed" not in a[0] + b[0]
