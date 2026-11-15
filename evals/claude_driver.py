"""Eval driver that uses the Claude Code CLI (`claude -p`) as the agent instead of the API.

No API key needed: it runs on the user's Claude subscription login. The agent gets ONLY the
browser MCP server under test (built-in tools disabled, our own system prompt), so the two MCP
modes compete on equal terms:

  lean            lean_browser's 7 tools  (leanb mcp)
  playwright-mcp  Microsoft's Playwright MCP 0.0.83 (aria snapshots with refs)
  agent-browser   Vercel's agent-browser 0.41.0 (`agent-browser mcp`, default "core" tool profile)

Success is still verified by the fixture server. Claude Code always uses prompt caching, so
token numbers are reported both as total processed tokens and as cost-weighted list-price USD.

Usage:
  python -m evals.claude_driver --quick                 # 6 tasks x 2 modes x 1 run
  python -m evals.claude_driver --tasks login,booking --modes lean
  python -m evals.claude_driver --runs 3 --jobs 4       # all 100 tasks, 4 agents at a time

With --jobs N, each worker gets its own fixture server (own recorded state) and working folder, so
parallel runs can't see each other's submissions. Wall-clock times are measured per run, but they are
noisier under parallel load; tokens and success are unaffected.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.request
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from evals.fixtures.server import serve
from evals.runner import CONFIG, PWMCP_CLI, RESUME, SYSTEM, RunResult, _chromium_executable, _free_port, _state
from evals.live_tasks import LIVE_TASKS
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
    start = task.start if task.start.startswith("http") else base + task.start
    prompt = (f"Goal: {task.goal}\n\nStart page: {start} (open it first).\n"
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
    ap.add_argument("--jobs", type=int, default=1, help="agents run in parallel, each with its own fixture server")
    ap.add_argument("--tags", help="only tasks with one of these tags, e.g. bench or safety,form")
    ap.add_argument("--suite", choices=["fixtures", "live"], default="fixtures",
                    help="live = public pages, answer-verified, reported separately")
    a = ap.parse_args()
    modes = a.modes.split(",")
    if a.suite == "live":
        pool = {t.id: t for t in LIVE_TASKS}
        tasks = [pool[t] for t in a.tasks.split(",")] if a.tasks else list(LIVE_TASKS)
    else:
        tasks = [BY_ID[t] for t in (QUICK if a.quick else (a.tasks.split(",") if a.tasks else [t.id for t in TASKS]))]
        if a.tags:
            want = set(a.tags.split(","))
            tasks = [t for t in tasks if want & set(t.tags)]
    out_dir = ROOT / "evals/results" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-claude-cli" + ("-live" if a.suite == "live" else ""))
    log_dir = out_dir / "transcripts"
    log_dir.mkdir(parents=True)
    (out_dir / "meta.json").write_text(json.dumps({
        "config": {**CONFIG, "model": f"{CONFIG['model']} via claude -p"}, "modes": modes,
        "tasks": [t.id for t in tasks], "runs": a.runs, "cached": True, "driver": "claude-cli", "suite": a.suite}, indent=2))
    # Refuse to run with a missing MCP server: claude -p would silently run without browsing tools and the
    # agent would answer from memory, which produces invalid results (this happened once on 2026-11-15).
    need = {"lean": ROOT / ".venv/bin/leanb", "playwright-mcp": PWMCP_CLI, "agent-browser": AGENT_BROWSER}
    missing = [f"{m}: {need[m]}" for m in modes if m in need and not need[m].exists()]
    if missing:
        raise SystemExit("missing MCP server(s), run ./install.sh --with-eval:\n  " + "\n  ".join(missing))
    print(f"{len(tasks)} tasks x {len(modes)} modes x {a.runs} run(s) via claude -p ({MODEL}), {a.jobs} job(s); "
          f"results in {out_dir}", flush=True)
    jobs = [(r + 1, task, mode) for r in range(a.runs) for task in tasks for mode in modes]
    local = threading.local()
    servers, lock = [], threading.Lock()
    root_tmp = tempfile.TemporaryDirectory(prefix="leanb-claude-")

    def work(job):
        if not hasattr(local, "base"):  # one fixture server and working folder per worker thread
            port = _free_port()
            srv = serve(port)
            with lock:
                servers.append(srv)
            local.base = f"http://127.0.0.1:{port}"
            local.tmp = Path(tempfile.mkdtemp(dir=root_tmp.name))
        run, task, mode = job
        return run_one(local.base, task, mode, run, local.tmp, log_dir)

    with open(out_dir / "runs.jsonl", "w") as runs_f, ThreadPoolExecutor(max(1, a.jobs)) as ex:
        for res in ex.map(work, jobs):
            runs_f.write(json.dumps({**asdict(res), "total_tokens": res.total_tokens,
                                     "weighted_input": res.weighted_input()}) + "\n")
            runs_f.flush()
            print(f"[{'PASS' if res.success else 'FAIL'}] {res.mode:<15} {res.task:<18} turns={res.steps:<3} "
                  f"tokens={res.total_tokens:<8} {res.errors[0]:<22} {res.wall_s}s "
                  f"{'' if res.success else res.reason[:70]}", flush=True)
    for srv in servers:
        srv.shutdown()
    root_tmp.cleanup()
    from evals.report import write_report
    print(f"\nReport: {write_report(out_dir)}")


if __name__ == "__main__":
    main()
