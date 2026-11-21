"""MCP contract tests: the live tool list must match the checked-in contract (tests/contract/mcp_tools.json),
invalid calls must come back as useful errors without killing the server, stdout must carry only JSON-RPC,
and two servers (two agents) must not share browser state.

Changing a tool on purpose: regenerate the contract file (see the snippet in the failure message), and note the
change in CHANGELOG.md.
"""
import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.test_reliability import base  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parent.parent
LEANB = str(ROOT / ".venv/bin/leanb")
CONTRACT = Path(__file__).parent / "contract" / "mcp_tools.json"
REGEN = ('.venv/bin/python -c "import json; from lean_browser.mcp_server import MCP_TOOLS; '
         "open('tests/contract/mcp_tools.json','w').write(json.dumps([{'name':t.name,'description':t.description,"
         "'input_schema':t.input_schema} for t in MCP_TOOLS],indent=1,sort_keys=True)+'\\n')\"")


def _session(args=("--allow-private-network", "mcp")):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    params = StdioServerParameters(command=LEANB, args=list(args), env=dict(os.environ))
    return stdio_client(params), ClientSession


async def test_live_tools_match_the_contract():
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    want = json.loads(CONTRACT.read_text())
    async with stdio_client(StdioServerParameters(command=LEANB, args=["mcp"])) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        live = [{"name": t.name, "description": t.description, "input_schema": getattr(t, "input_schema", None) or getattr(t, "inputSchema", None)}
                for t in (await s.list_tools()).tools]
    key = lambda d: d["name"]
    assert sorted(live, key=key) == sorted(want, key=key), f"MCP tools changed. If intended, regenerate:\n{REGEN}"


async def test_invalid_calls_are_useful_errors_and_the_server_survives(base):  # noqa: F811
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    params = StdioServerParameters(command=LEANB, args=["--allow-private-network", "mcp"])
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()

        async def err(name, args, *needles):
            res = await s.call_tool(name, args)
            text = " ".join(c.text for c in res.content if c.type == "text")
            assert res.is_error, (name, args, text)
            assert text.startswith("Error:") or "error" in text.lower(), text
            for n in needles:
                assert n.lower() in text.lower(), (name, args, text)
            return text

        await err("act", {"action": "click", "id": 1}, "no page")       # nothing open yet
        await err("snapshot", {}, "no page")
        await err("no_such_tool", {}, "unknown tool")
        await err("open", {}, "url")                                     # missing required argument
        ok = await s.call_tool("open", {"url": base + "/login.html"})
        assert not ok.is_error
        await err("act", {"action": "click", "id": 99999}, "not found")
        await err("act", {"action": "teleport", "id": 1})
        await err("act", {"action": "fill"}, "id")
        await err("act", {"action": "click", "id": 9, "expect": "gone:abc"}, "expect")
        await err("fill_form", {"fields": "{not json"})
        await err("extract", {"kind": "spreadsheet"})
        await err("memory", {"action": "get", "key": "never-set"})
        # still alive and still on the page (an unchanged page answers "unchanged", so search it instead)
        res = await s.call_tool("snapshot", {"find": "Username"})
        assert not res.is_error and "Username" in res.content[0].text, res.content[0].text


def test_stdout_carries_only_json_rpc(base):  # noqa: F811
    """Logs and engine notes must go to stderr: one stray print on stdout breaks every MCP client."""
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "open", "arguments": {"url": base + "/order.html"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "open", "arguments": {"url": "http://localhost:1/"}}},
    ]
    p = subprocess.Popen([LEANB, "--allow-private-network", "--trace", "mcp"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    lines = []
    try:
        for m in msgs:
            p.stdin.write(json.dumps(m) + "\n")
            p.stdin.flush()
            if "id" in m:
                lines.append(p.stdout.readline())
    finally:
        p.stdin.close()
        try:
            p.wait(timeout=20)
        except subprocess.TimeoutExpired:
            p.kill()
    rest = p.stdout.read()
    for ln in lines + [x for x in rest.splitlines() if x.strip()]:
        obj = json.loads(ln)  # raises on any non-JSON line
        assert obj.get("jsonrpc") == "2.0", ln
    assert json.loads(lines[2])["result"]["content"][0]["text"].count("Place order")


async def test_two_servers_do_not_share_state(base):  # noqa: F811
    """Two agents = two `leanb mcp` processes: cookies, memory and open pages stay separate."""
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    params = StdioServerParameters(command=LEANB, args=["--allow-private-network", "mcp"])
    async with stdio_client(params) as (r1, w1), ClientSession(r1, w1) as a, \
            stdio_client(params) as (r2, w2), ClientSession(r2, w2) as b:
        await asyncio.gather(a.initialize(), b.initialize())
        await a.call_tool("open", {"url": base + "/login.html"})
        login = await a.call_tool("fill_form", {"fields": {"9": "demo", "10": "demo-pass-123"}, "submit": True})
        assert "Welcome back, demo" in login.content[0].text, login.content[0].text[:300]
        await a.call_tool("memory", {"action": "set", "key": "secret", "value": "only-for-a"})
        res = await b.call_tool("memory", {"action": "get", "key": "secret"})
        assert res.is_error
        res = await b.call_tool("snapshot", {})
        assert res.is_error and "no page" in res.content[0].text.lower()
        out_a = (await a.call_tool("open", {"url": base + "/account"})).content[0].text
        out_b = (await b.call_tool("open", {"url": base + "/account"})).content[0].text
        assert "Welcome back, demo" in out_a and "Welcome back" not in out_b, (out_a[:200], out_b[:200])


def test_key_is_optional_for_existing_clients():
    """Clients written before `key` existed keep working: it is optional everywhere."""
    tools = {t["name"]: t for t in json.loads(CONTRACT.read_text())}
    for name in ("act", "fill_form"):
        schema = tools[name]["input_schema"]
        assert "key" in schema["properties"] and "key" not in schema.get("required", [])


async def test_one_key_across_two_servers_sends_once(base, tmp_path):  # noqa: F811
    """Two agents (two `leanb mcp` processes) submit the same order at the same moment with the same key: it is
    sent exactly once, and the other call is blocked. Without a key (old clients) both calls still work."""
    import urllib.request
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from tests.test_reliability import subs
    urllib.request.urlopen(base + "/api/reset").read()
    env = {**os.environ, "LEANB_STATE_DIR": str(tmp_path / "state")}
    params = StdioServerParameters(command=LEANB, args=["--allow-private-network", "mcp"], env=env)
    async with stdio_client(params) as (r1, w1), ClientSession(r1, w1) as a, \
            stdio_client(params) as (r2, w2), ClientSession(r2, w2) as b:
        await asyncio.gather(a.initialize(), b.initialize())
        pages = await asyncio.gather(a.call_tool("open", {"url": base + "/order.html"}),
                                     b.call_tool("open", {"url": base + "/order.html"}))
        import re
        ids = [re.search(r'(\d+): button "Place order"', p.content[0].text).group(1) for p in pages]
        res = await asyncio.gather(*(c.call_tool("act", {"action": "click", "id": int(i), "key": "order-77"})
                                     for c, i in zip((a, b), ids)))
        texts = [r.content[0].text for r in res]
        won = [bool(re.search(r"(?m)^status: verified", t)) and not t.startswith("Error") for t in texts]
        assert won.count(True) == 1, texts
        assert sum("duplicate: key" in t for t in texts) == 1, texts
        assert len(subs(base, "order")) == 1
        # an old client with no key: unchanged behaviour (the one whose keyed call was blocked, so its own
        # per-page guard has nothing to object to)
        c = (a, b)[won.index(False)]
        page = await c.call_tool("open", {"url": base + "/order.html"})
        i = re.search(r'(\d+): button "Place order"', page.content[0].text).group(1)
        last = (await c.call_tool("act", {"action": "click", "id": int(i)})).content[0].text
        assert re.search(r"(?m)^status: verified", last) and not last.startswith("Error"), last
        assert len(subs(base, "order")) == 2, (texts, page.content[0].text[:600], last, subs(base, "order"))


async def test_concurrent_calls_on_one_server_are_serialized(base):  # noqa: F811
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    params = StdioServerParameters(command=LEANB, args=["--allow-private-network", "mcp"])
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        pages = {"/login.html": 'textbox "Username"', "/order.html": "Place order", "/signup.html": "Create account",
                 "/todo.html": "/todo.html | "}
        results = await asyncio.gather(*(s.call_tool("open", {"url": base + p}) for p in pages))
        for (p, marker), res in zip(pages.items(), results):
            text = res.content[0].text
            assert not res.is_error and marker in text, (p, text[:300])  # each call got its own page, not a mix
