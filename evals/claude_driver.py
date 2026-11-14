"""Eval driver that uses the Claude Code CLI (`claude -p`) as the agent instead of the API.

No API key needed: it runs on the user's Claude subscription login. The agent gets ONLY the
browser MCP server under test (built-in tools disabled, our own system prompt), so the two MCP
modes compete on equal terms:

  lean            lean_browser's 6 tools  (leanb mcp)
  playwright-mcp  Microsoft's Playwright MCP 0.0.83 (aria snapshots with refs)
  agent-browser   Vercel's agent-browser 0.41.0 (`agent-browser mcp`, default "core" tool profile)

Success is still verified by the fixture server. Claude Code always uses prompt caching, so
token numbers are reported both as total processed tokens and as cost-weighted list-price USD.

Usage:
  python -m evals.claude_driver --quick                 # 6 tasks x 2 modes x 1 run
  python -m evals.claude_driver --tasks login,booking --modes lean
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from evals.fixtures.server import serve
from evals.runner import CONFIG, PWMCP_CLI, RESUME, SYSTEM, RunResult, _chromium_executable, _free_port, _state
from evals.tasks import BY_ID, QUICK, TASKS

ROOT = Path(__file__).resolve().parent.parent
CLAUDE = os.environ.get("CLAUDE_BIN", str(Path.home() / ".local/bin/claude"))
MODES = ["playwright-mcp", "agent-browser", "lean"]
AGENT_BROWSER = ROOT / ".vendor/agent-browser/node_modules/agent-browser/bin/agent-browser-darwin-arm64"
MODEL = {"claude-sonnet-5-5": "sonnet"}.get(CONFIG["model"], CONFIG["model"])

DRIVER_SYSTEM = SYSTEM.replace("call the answer tool with the requested information, or 'done' for action-only goals",
                               "reply with a final line 'FINAL: <the requested information, or done>'")


def mcp_config(mode: str, tmp: Path, trace_dir: Path | None = None) -> tuple[Path, str]:
    if mode == "lean":
        cfg = tmp / "lean.toml"
        cfg.write_text(f'allow_private_network = true\nallowed_upload_dirs = ["{tmp.resolve()}"]\n')
        server = {"command": str(ROOT / ".venv/bin/leanb"), "args": ["--config", str(cfg), "mcp"]}
        if trace_dir:  # every lean run leaves a trace next to the results (leanb trace list --dir ...)
            server["env"] = {"LEANB_TRACE": "1", "LEANB_TRACE_DIR": str(trace_dir)}
        name = "lean"
    elif mode == "agent-browser":
        # Same Chrome for Testing build as the other modes; a fresh named session per run.
        server = {"command": str(AGENT_BROWSER), "args": ["mcp"],
                  "env": {"AGENT_BROWSER_EXECUTABLE_PATH": _chromium_executable(),
                          "AGENT_BROWSER_SESSION_NAME": f"leanb-eval-{tmp.name}-{time.time_ns()}"}}
        name = "agentbrowser"
    else:
        server = {"command": "node", "args": [str(PWMCP_CLI), "--headless", "--isolated", "--executable-path",
                                              _chromium_executable(), "--viewport-size", "1280,800"]}
        name = "playwright"
    f = tmp / f"{mode}.mcp.json"
    f.write_text(json.dumps({"mcpServers": {name: server}}))
    return f, name


def run_one(base: str, task, mode: str, run: int, tmp: Path, log_dir: Path) -> RunResult:
    urllib.request.urlopen(f"{base}/api/reset").read()
    cfg, server = mcp_config(mode, tmp, log_dir.parent / "traces")
    # Both servers may only upload from the run's working folder (Playwright MCP restricts file access
    # to its cwd by default; lean uses allowed_upload_dirs), so the resume is copied there for both.
    resume = tmp.resolve() / "resume.pdf"
    shutil.copy(RESUME, resume)
    prompt = (f"Goal: {task.goal}\n\nStart page: {base}{task.start} (open it first).\n"
              f"files: resume = {resume}\n\nWhen the goal is complete, end with the line: FINAL: <answer or done>")
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}  # use the subscription login
    cmd = [CLAUDE, "-p", prompt, "--output-format", "json", "--model", MODEL, "--tools", "",
           "--strict-mcp-config", "--mcp-config", str(cfg), "--allowedTools", f"mcp__{server}",
           "--system-prompt", DRIVER_SYSTEM, "--max-turns", str(CONFIG["max_steps"]), "--no-session-persistence"]
    res = RunResult(task.id, mode, run, True, False, "", 0)
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=900, cwd=tmp)
        out = json.loads(p.stdout or "{}")
    except subprocess.TimeoutExpired:
        out = {"subtype": "timeout"}
    except json.JSONDecodeError:
        out = {"subtype": "bad_output", "raw": (p.stdout + p.stderr)[-2000:]}
    (log_dir / f"{task.id}.{mode}.{run}.json").write_text(json.dumps(out, indent=2))
    if mode == "agent-browser":  # agent-browser keeps a browser daemon per session; stop it
        sess = json.loads(cfg.read_text())["mcpServers"][server]["env"]
        subprocess.run([str(AGENT_BROWSER), "close"], env={**env, **sess}, capture_output=True, timeout=30)
    u = out.get("usage") or {}
    res.input_tokens = u.get("input_tokens", 0)
    res.output_tokens = u.get("output_tokens", 0)
    res.cache_read_tokens = u.get("cache_read_input_tokens", 0)
    res.cache_write_tokens = u.get("cache_creation_input_tokens", 0)
    res.steps = out.get("num_turns", 0)
    res.stop = out.get("subtype", "")
    text = out.get("result") or ""
    res.answer = text.rsplit("FINAL:", 1)[-1].strip() if "FINAL:" in text else text[-300:]
    res.success, res.reason = task.verify(_state(base), res.answer)
    res.wall_s = round(time.time() - t0, 1)
    res.errors = [f"cost_usd={out.get('total_cost_usd')}"]
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--tasks")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    modes = a.modes.split(",")
    tasks = [BY_ID[t] for t in (QUICK if a.quick else (a.tasks.split(",") if a.tasks else [t.id for t in TASKS]))]
    out_dir = ROOT / "evals/results" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-claude-cli")
    log_dir = out_dir / "transcripts"
    log_dir.mkdir(parents=True)
    (out_dir / "meta.json").write_text(json.dumps({
        "config": {**CONFIG, "model": f"{CONFIG['model']} via claude -p"}, "modes": modes,
        "tasks": [t.id for t in tasks], "runs": a.runs, "cached": True, "driver": "claude-cli"}, indent=2))
    port = _free_port()
    srv = serve(port)
    base = f"http://127.0.0.1:{port}"
    print(f"{len(tasks)} tasks x {len(modes)} modes x {a.runs} run(s) via claude -p ({MODEL}); results in {out_dir}", flush=True)
    with tempfile.TemporaryDirectory(prefix="leanb-claude-") as td, open(out_dir / "runs.jsonl", "w") as runs_f:
        for r in range(a.runs):
            for task in tasks:
                for mode in modes:
                    res = run_one(base, task, mode, r + 1, Path(td), log_dir)
                    runs_f.write(json.dumps({**asdict(res), "total_tokens": res.total_tokens,
                                             "weighted_input": res.weighted_input()}) + "\n")
                    runs_f.flush()
                    print(f"[{'PASS' if res.success else 'FAIL'}] {mode:<15} {task.id:<11} turns={res.steps:<3} "
                          f"tokens={res.total_tokens:<8} {res.errors[0]:<22} {res.wall_s}s "
                          f"{'' if res.success else res.reason[:70]}", flush=True)
    srv.shutdown()
    from evals.report import write_report
    print(f"\nReport: {write_report(out_dir)}")


if __name__ == "__main__":
    main()
