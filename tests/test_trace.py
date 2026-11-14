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
