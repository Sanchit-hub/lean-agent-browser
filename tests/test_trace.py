"""Tracing (opt-in JSONL, redaction, permissions, CLI) and the bench wrapper."""
import json
import os
import stat
import subprocess
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.fixtures.server import serve
from lean_browser import Config, LeanBrowser, trace
from lean_browser import cli
from tests.test_fixtures import _free_port

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def base():
    port = _free_port()
    srv = serve(port)
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


async def test_trace_records_calls_redacts_passwords_and_is_private(base, tmp_path, monkeypatch):
    monkeypatch.setenv("LEANB_TRACE_DIR", str(tmp_path / "t"))
    urllib.request.urlopen(base + "/api/reset").read()
    async with LeanBrowser(Config(allow_private_network=True, trace=True)) as b:
        await b.open(base + "/login.html")
        await b.fill_form({9: "demo", 10: "demo-pass-123"}, submit=True)
        await b.call("act", {"action": "click", "id": 4242})
        path = b.tracer.path
    recs = [json.loads(l) for l in path.read_text().splitlines()]
    assert [r["tool"] for r in recs] == ["open", "fill_form", "act"]
    assert recs[1]["args"]["fields"] == {"9": "demo", "10": "••••"}
    assert "demo-pass-123" not in path.read_text()
    assert recs[1]["status"] == "verified" and recs[2]["error"] is True
    assert recs[0]["engine"] in ("obscura", "chromium") and recs[0]["url"].endswith("/login.html")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    shown = trace.show_run("latest", path.parent)
    assert "3 calls" in shown and "verified" in shown and "ERROR" in shown and "id 4242 not found" in shown
    assert path.stem in trace.list_runs(path.parent)


async def test_trace_off_by_default(base, tmp_path, monkeypatch):
    monkeypatch.setenv("LEANB_TRACE_DIR", str(tmp_path / "t"))
    monkeypatch.delenv("LEANB_TRACE", raising=False)
    async with LeanBrowser(Config(allow_private_network=True)) as b:
        await b.open(base + "/login.html")
        assert b.tracer is None
    assert not (tmp_path / "t").exists()


def test_trace_cli(base, tmp_path):
    env = {**os.environ, "LEANB_TRACE_DIR": str(tmp_path / "t")}
    leanb = str(ROOT / ".venv/bin/leanb")
    out = subprocess.run([leanb, "--trace", "--allow-private-network", "open", base + "/login.html"],
                         capture_output=True, text=True, env=env, timeout=60)
    assert out.returncode == 0, out.stderr
    shown = subprocess.run([leanb, "trace", "show", "latest", "--dir", str(tmp_path / "t")],
                           capture_output=True, text=True, timeout=30).stdout
    assert "1 calls" in shown and "open" in shown


def test_bench_builds_driver_command(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "call", lambda args, cwd: calls.append((args, cwd)) or 0)
    a = SimpleNamespace(agent="claude-cli", quick=True, runs=3, modes=None, tasks=None)
    assert cli.cmd_bench(a) == 0
    args, cwd = calls[0]
    assert args[1:] == ["-m", "evals.claude_driver", "--quick", "--modes", "playwright-mcp,lean"] and Path(cwd) == ROOT
    a = SimpleNamespace(agent="api", quick=False, runs=5, modes="lean", tasks="login")
    cli.cmd_bench(a)
    assert calls[1][0][1:] == ["-m", "evals.runner", "--runs", "5", "--modes", "lean", "--tasks", "login", "-y"]


async def _record_login_trace(base, tmp_path, monkeypatch):
    monkeypatch.setenv("LEANB_TRACE_DIR", str(tmp_path / "t"))
    urllib.request.urlopen(base + "/api/reset").read()
    async with LeanBrowser(Config(allow_private_network=True, trace=True)) as b:
        await b.open(base + "/signup.html")
        await b.act("fill", 9, "asha")
        await b.call("act", {"action": "click", "id": 4242})
        await b.extract("form", fields=["username"])
        return b.tracer.path


async def test_replay_same_outcomes_and_finds_divergence(base, tmp_path, monkeypatch):
    path = await _record_login_trace(base, tmp_path, monkeypatch)
    out = await trace.replay(path.stem, path.parent)
    assert "no divergence" in out and sum(l.endswith(" same") for l in out.splitlines()) == 4
    # Tamper with the recorded outcome of call #2: replay must point at it as the first divergence.
    recs = [json.loads(l) for l in path.read_text().splitlines()]
    recs[1]["status"] = None
    recs[1]["result"] = "status: unverified (no visible change)"
    path.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    out = await trace.replay(path.stem, path.parent)
    assert "first divergence at call #2" in out


async def test_replay_skips_redacted_and_live_actions(base, tmp_path):
    d = tmp_path / "t"
    d.mkdir()
    recs = [
        {"seq": 1, "tool": "open", "args": {"url": base + "/login.html"}, "url": base + "/login.html", "error": False,
         "status": None, "result": "page: Log in | url: /login.html", "image": False},
        {"seq": 2, "tool": "fill_form", "args": {"fields": {"9": "demo", "10": "••••"}}, "url": base + "/login.html",
         "error": False, "status": "verified", "result": "status: verified", "image": False},
    ]
    (d / "r1.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    out = await trace.replay("r1", d)
    assert "skipped (redacted value)" in out
    live = [{**recs[0], "args": {"url": "https://example.com/"}, "url": "https://example.com/", "result": "page: Example Domain | url: /"},
            {"seq": 2, "tool": "act", "args": {"action": "click", "id": 1}, "url": "https://example.com/", "error": False,
             "status": "verified", "result": "status: verified", "image": False}]
    (d / "r2.jsonl").write_text("\n".join(json.dumps(r) for r in live) + "\n")
    out = await trace.replay("r2", d)
    assert "skipped (action on a live site)" in out and "read-only calls only" in out


def test_export_and_delete(tmp_path):
    d = tmp_path / "t"
    d.mkdir()
    (d / "a.jsonl").write_text(json.dumps({"seq": 1, "tool": "open", "args": {}, "url": "u"}) + "\n")
    (d / "b.jsonl").write_text("")
    msg = trace.export_run("a", tmp_path / "out.jsonl", d)
    assert "review it before sharing" in msg and stat.S_IMODE((tmp_path / "out.jsonl").stat().st_mode) == 0o600
    assert trace.delete_runs("a", d) == f"deleted 1 trace(s) from {d}"
    assert trace.delete_runs("all", d) == f"deleted 1 trace(s) from {d}"


def test_redact_url_and_sensitive_fields():
    assert trace.redact_url("https://x.com/cb?code=abc123&state=xyz&page=2#access_token=t0k") == \
        "https://x.com/cb?code=REDACTED&state=REDACTED&page=2#access_token=REDACTED"
    assert trace.redact_url("https://x.com/a/b") == "https://x.com/a/b"
    idx = {1: {"role": "textbox", "name": "Card number"}, 2: {"role": "textbox", "name": "Name"},
           3: {"role": "textbox", "name": "Code", "fp": {"nm": "otp"}}}
    a = trace.redact_args("fill_form", {"fields": {"1": "4111111111111111", "2": "Asha", "3": "123456"}}, idx)
    assert a["fields"] == {"1": "••••", "2": "Asha", "3": "••••"}
    assert trace.redact_args("open", {"url": "https://x.com/?token=s3cret"}, {})["url"] == "https://x.com/?token=REDACTED"


async def test_trace_records_outcome_category_and_no_page_text(base, tmp_path, monkeypatch):
    monkeypatch.setenv("LEANB_TRACE_DIR", str(tmp_path / "t"))
    monkeypatch.delenv("LEANB_TRACE_PAGE_TEXT", raising=False)
    urllib.request.urlopen(base + "/api/reset").read()
    async with LeanBrowser(Config(allow_private_network=True, trace=True)) as b:
        out = await b.open(base + "/order.html?session=abc")
        place = int(out.split(': button "Place order"')[0].rsplit("\n", 1)[1])
        await b.act("click", place)
        await b.call("act", {"action": "click", "id": place})  # duplicate -> blocked
        await b.call("act", {"action": "click", "id": 4242})
        path = b.tracer.path
    recs = [json.loads(l) for l in path.read_text().splitlines()]
    assert recs[0]["args"]["url"].endswith("/order.html?session=REDACTED") and "abc" not in path.read_text()
    assert recs[0]["result"].startswith("page: Checkout") and "Masala chai" not in recs[0]["result"]
    assert recs[1]["outcome"]["status"] == "verified" and recs[1]["outcome"]["retry_safety"] == "unsafe"
    assert recs[1]["step"] == f"{recs[1]['run']}#2"
    assert recs[2]["category"] == "blocked" and recs[2]["outcome"]["executed"] is False
    assert recs[3]["category"] == "stale"
    assert "ERROR:blocked" in trace.show_run("latest", path.parent)


async def test_replay_reproduces_a_blocked_submission(base, tmp_path, monkeypatch):
    """A failure recorded on a local fixture replays to the same outcome (regression reproduction)."""
    monkeypatch.setenv("LEANB_TRACE_DIR", str(tmp_path / "t"))
    urllib.request.urlopen(base + "/api/reset").read()
    async with LeanBrowser(Config(allow_private_network=True, trace=True)) as b:
        out = await b.open(base + "/signup.html")
        email = int(out.split(': textbox "Email"')[0].rsplit("\n", 1)[1])
        btn = int(out.split(': button "Create account"')[0].rsplit("\n", 1)[1])
        await b.act("fill", email, "not-an-email")
        assert (await b.act("click", btn)).startswith("status: blocked")
        path = b.tracer.path
    out = await trace.replay(path.stem, path.parent)
    assert "no divergence" in out and "blocked" in out
