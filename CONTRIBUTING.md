# Contributing

Thanks for helping. This page covers everything you need to make a change and get it merged.

## Set up (macOS, Apple Silicon)

```bash
./install.sh                     # .venv, pinned + checksummed Obscura, Chromium, self-check
.venv/bin/python -m pytest -q    # 181 passed, 1 skipped (2026-11-15), about 3 min; local fixture site, both engines
```

## Where things live

| Area | Files |
|---|---|
| Engines, routing, sandbox | `lean_browser/engine.py` |
| Page to compact text | `lean_browser/snapshot.js` (runs in the page), `lean_browser/snapshot.py` (render, budgets, find) |
| Actions, settle, diffs | `lean_browser/session.py`, `lean_browser/settle.py`, `lean_browser/diff.py` |
| Tools / MCP / CLI | `lean_browser/tools.py`, `lean_browser/mcp_server.py`, `lean_browser/cli.py` |
| Eval tasks and runners | `evals/` (tasks are checked by the fixture server in `evals/fixtures/`) |

`SPEC.md` explains the design. `spike/FINDINGS.md` explains why each Obscura workaround exists.

## Looking at snapshots while you work

```bash
.venv/bin/python scripts/snap.py login.html,orders.html obscura      # fixture pages
.venv/bin/leanb open https://example.com --mode read                 # any page
```

## Rules for changes

- **Test on both engines.** Snapshot and session tests already run on Obscura and Chromium. Add your
  case there.
- **Keep tool schemas small.** `tests/test_tools.py::test_tool_schema_budget` fails if the 6 tool
  definitions grow past the budget.
- **Obscura quirks** need a workaround in code plus a line in `SPEC.md` or `spike/FINDINGS.md`.
  Don't work around them silently.
- **Claims need numbers.** If a change affects tokens, success or speed, run the eval
  (`python -m evals.claude_driver --quick`) and paste the before and after.
- **Security:** never widen what Obscura's sandbox, the private-network block or the upload allowlist
  permit without an explicit option and a test.

## Pull requests

Keep each PR to one change. Explain what changed and why, and list how you tested it. CI runs the full
suite on macOS.
