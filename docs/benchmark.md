# Benchmark methodology

How the numbers in the README are produced, what they cover, and what they don't. Anyone with a
Claude subscription can rerun them on a Mac.

## What is measured

| Metric | How |
|---|---|
| Success | The fixture server records every submission. A run counts only if the server state matches the task (for read tasks, the final answer must contain the right value). The agent's own claim is never used. |
| Tokens | Total tokens Claude processed for the task (input + cache + output), from `claude -p` usage. Tool-definition tokens are reported separately. |
| Turns, time | Model turns and wall-clock seconds per task; median and p95. |
| Failure category | `task_not_completed`, `wrong_answer`, `tool_error`, `timeout`, `step_limit`, `other` (`evals/report.py::failure_category`). |

## Setup held equal across tools

- Same task definitions, start pages and verifiers (`evals/tasks.py`, `evals/fixtures/`).
- Same agent: Claude Sonnet 5.5 through `claude -p`, built-in tools disabled (`--tools ""`), only the
  browser MCP server under test loaded (`--strict-mcp-config`), the same system prompt for every tool.
- Same machine and fixture server; each run starts from `/api/reset`.
- Integration mode: all three tools are compared **as MCP servers**. Vercel agent-browser is designed
  mainly as a CLI; we used its MCP `core` tool profile, which is labeled in every table.

## What exists today (2026-11-15)

| Suite | Tasks | Runs per task | Tools compared |
|---|---|---|---|
| Fixture (local, server-verified) | 20 (18 measured in the README table, plus `order-once` and `honest-failure` added in v0.3) | 3 for Lean and Playwright MCP, 1 for agent-browser | Lean, Playwright MCP 0.0.83, agent-browser 0.41.0 |
| Live (public pages, answer-verified) | 5 | 1 | Lean, Playwright MCP |

Fixture and live results are always reported separately.

**This is below the plan's target** of 100+ diverse tasks with 3–5 runs each. The sample is small, all
tasks were written by us, and agent-browser has only one run. So the results support "Lean used fewer
tokens on these tasks". They don't support "Lean is better than every browser agent".

## Rerun it

```bash
./install.sh --with-eval                                   # also installs both baselines (Node.js 20+)
.venv/bin/python -m evals.claude_driver --runs 3           # full fixture suite, Lean + Playwright MCP
.venv/bin/python -m evals.claude_driver --modes agent-browser --runs 3
.venv/bin/python -m evals.claude_driver --suite live       # live suite
```

Each run writes `evals/results/<timestamp>-claude-cli[-live]/`:

- `runs.jsonl`: one line per task run (task, mode, success, reason, tokens, turns, time, tool errors). This is the raw, task-level data.
- `summary.json`: per-mode success, median and p95 tokens and time, and failure categories.
- `report.md`: the tables.
- `transcripts/`: full agent transcripts.
- `traces/`: Lean's own call traces.

Only a full run (all fixture tasks, 3+ runs) replaces `evals/report.md`.

## Rules for claims

- Quote success with its denominator (`54/54`, not "100%").
- Quote the run count next to each tool; with 3 runs, p95 is close to the maximum.
- Don't compare a fixture number with a live number.
- Re-measure tool-definition tokens with `claude -p` after any schema change. tiktoken undercounts
  Claude tokens by about 2.3×.
