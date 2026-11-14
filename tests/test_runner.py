"""Runner plumbing without the API: a fake client replays scripted tool calls, so the loop,
tool execution, observations, token accounting and the report are all exercised offline."""
import json
from types import SimpleNamespace

import pytest
from playwright.async_api import async_playwright

from evals import runner
from evals.fixtures.server import serve
from evals.report import write_report
from evals.tasks import BY_ID
from tests.test_fixtures import _free_port


class FakeClient:
    """Returns a scripted sequence of tool calls and records what the agent was shown."""

    def __init__(self, script):
        self.script = list(script)
        self.seen = []
        self.messages = self

    async def create(self, **kw):
        self.seen.append(kw)
        name, args = self.script.pop(0)
        block = SimpleNamespace(type="tool_use", id=f"t{len(self.seen)}", name=name, input=args)
        return SimpleNamespace(content=[block], stop_reason="tool_use",
                               usage=SimpleNamespace(input_tokens=100, output_tokens=10,
                                                     cache_read_input_tokens=0, cache_creation_input_tokens=0))


@pytest.fixture(scope="module")
def base():
    port = _free_port()
    srv = serve(port)
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


@pytest.mark.parametrize("mode,script", [
    ("html", [("fill", {"selector": "input[name=username]", "value": "demo"}),
              ("fill", {"selector": "input[name=password]", "value": "demo-pass-123"}),
              ("click", {"selector": "main button[type=submit]"}),
              ("answer", {"text": "done"})]),
    ("aria", [("fill", {"name": "Username", "value": "demo"}),
              ("fill", {"name": "Password", "value": "demo-pass-123"}),
              ("click", {"role": "button", "name": "Log in"}),
              ("answer", {"text": "done"})]),
])
async def test_loop_solves_login(mode, script, base):
    client = FakeClient(script)
    logged = []
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        res = await runner.run_task(client, b, base, BY_ID["login"], mode, 1, False, logged.append)
        await b.close()
    assert res.success, res.reason
    assert res.steps == 4 and res.input_tokens == 400 and res.output_tokens == 40
    assert len(logged) == 4
    # every tool result after an action carries the new page observation
    msgs = client.seen[-1]["messages"]  # live list; the final assistant turn was appended after the call
    last_user = [m for m in msgs if m["role"] == "user"][-1]["content"][-1]["content"]
    assert any(b.get("type") == "text" and "url:" in b.get("text", "") for b in last_user)


async def test_tool_error_is_returned_not_raised(base):
    client = FakeClient([("click", {"selector": "#does-not-exist"}), ("answer", {"text": "done"})])
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        res = await runner.run_task(client, b, base, BY_ID["login"], "html", 1, False, lambda r: None)
        await b.close()
    assert not res.success and res.errors and "click" in res.errors[0]


async def test_screenshot_mode_sends_image(base):
    client = FakeClient([("answer", {"text": "done"})])
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        await runner.run_task(client, b, base, BY_ID["article"], "screenshot", 1, False, lambda r: None)
        await b.close()
    first = client.seen[0]["messages"][0]["content"]
    assert any(x["type"] == "image" for x in first)


def test_report(tmp_path):
    d = tmp_path / "results" / "run1"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"config": {"model": "m", "effort": "medium"}, "tasks": ["login"], "runs": 1,
                                             "schema_tokens": {"html": 300}}))
    rec = {"task": "login", "mode": "html", "run": 1, "cached": False, "success": True, "reason": "", "steps": 3,
           "input_tokens": 900, "output_tokens": 30, "cache_read_tokens": 0, "cache_write_tokens": 0, "wall_s": 2.0,
           "stop": "answer", "answer": "done", "errors": [], "total_tokens": 930, "weighted_input": 900}
    (d / "runs.jsonl").write_text(json.dumps(rec) + "\n")
    out = write_report(d)
    text = out.read_text()
    assert "| html | 1/1 (100%) | 930 |" in text


def test_dotenv_loader(tmp_path, monkeypatch):
    import os
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    f = tmp_path / ".env"
    f.write_text("# comment\nANTHROPIC_API_KEY=\nsk-ant-api03-TESTVALUE\n")
    f.chmod(0o600)
    runner._load_dotenv(f)
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-api03-TESTVALUE"   # key pasted on the next line
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    f.write_text('ANTHROPIC_API_KEY="sk-ant-api03-OTHER"\n')
    runner._load_dotenv(f)
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-api03-OTHER"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    f.chmod(0o644)
    with pytest.raises(SystemExit, match="chmod 600"):
        runner._load_dotenv(f)
