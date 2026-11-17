# Contributing

Thanks for helping. This page covers everything you need to make a change and get it merged.

## Set up (macOS on Apple Silicon, or Linux)

```bash
./install.sh                     # .venv, pinned + checksummed Obscura, Chromium, self-check
                                 # Linux: sudo apt install bubblewrap first
.venv/bin/python -m pytest -q    # 443 passed, 3 skipped (2026-11-18, macOS), about 7 min; local fixture site, both engines
./scripts/smoke_clean_install.sh # release check: wheel into a fresh venv, setup, doctor, MCP round trip, pipx
```

## Where things live

| Area | Files |
|---|---|
| Engines, routing, sandbox | `lean_browser/engine.py` |
| Page to compact text | `lean_browser/snapshot.js` (runs in the page), `lean_browser/snapshot.py` (render, budgets, find) |
| Actions, outcomes, recovery, dry-run | `lean_browser/session.py`, `lean_browser/settle.py`, `lean_browser/diff.py` |
| Tools / MCP / CLI | `lean_browser/tools.py`, `lean_browser/mcp_server.py`, `lean_browser/cli.py` |
| Setup, doctor, Claude Code registration | `lean_browser/onboarding.py`, `lean_browser/doctor.py`, `lean_browser/claude_code.py` (writes only through `claude mcp`) |
| Releases | `docs/RELEASING.md`, `.github/workflows/release.yml` |
| Eval tasks and runners | `evals/` (tasks are checked by the fixture server in `evals/fixtures/`); the 80 newer tasks live in `evals/bench/`, one module per category |

`SPEC.md` explains the design. `spike/FINDINGS.md` explains why each Obscura workaround exists.

## Looking at snapshots while you work

```bash
.venv/bin/python scripts/snap.py login.html,orders.html obscura      # fixture pages
.venv/bin/leanb open https://example.com --mode read                 # any page
```

## Rules for changes

- **Test on both engines.** Snapshot and session tests already run on Obscura and Chromium. Add your
  case there.
- **Keep tool schemas small.** `tests/test_tools.py::test_tool_schema_budget` fails if the 7 tool
  definitions grow past the budget.
- **Obscura quirks** need a workaround in code plus a line in `SPEC.md` or `spike/FINDINGS.md`.
  Don't work around them silently.
- **Claims need numbers.** If a change affects tokens, success or speed, run the eval
  (`python -m evals.claude_driver --quick`) and paste the before and after.
- **New benchmark tasks** go in `evals/bench/<category>.py` with `bench(...)`: a page, a goal, a server-side
  verifier and a scripted reference solution. `tests/test_fixtures.py` checks that the solution passes and
  that an empty run fails.
- **Outcomes stay honest.** Never let a change report `verified` without evidence, and never add an
  automatic retry of an `unsafe` action. `tests/test_reliability.py` guards both.
- **Security:** never widen what Obscura's sandbox, the private-network block or the upload allowlist
  permit without an explicit option and a test.

## Pull requests

Keep each PR to one change. Explain what changed and why, and list how you tested it. CI runs the full
suite on macOS 15 and on Ubuntu 24.04 (x86_64 and arm64).
