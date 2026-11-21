# Roadmap

**Positioning:** less browser context, more reliable actions, and a measurably lower cost per successful
agent task. Lean is an execution layer for AI agents. It is not a browser engine, and it is not an
autonomous agent.

**Principles:**
- deterministic before intelligent
- never hide uncertainty
- verify outcomes
- the agent stays in control
- measure complete tasks
- keep the engine replaceable
- safe by default

**Platforms:** macOS (Apple Silicon) and Linux (x86_64, arm64), both tested in CI since v0.4.0. Windows is
out of scope. Only CI-tested platforms are listed as supported.

## Implemented (verified in code and tests, v0.8.0, 2026-11-19)

Claim-by-claim status: `docs/PRODUCT_TRUTH.md`. Open engineering backlog: `docs/audits/cycle-002.md`.

| Area | What exists | Where |
|---|---|---|
| Engines | Obscura **0.2.7** default (0.2.6 rollback on macOS), hash-pinned per platform, sandboxed (`sandbox-exec` on macOS, bubblewrap on Linux), dies with its client; Chromium fallback with capability routing; hung pages move to Chromium | `engine.py`, `docs/engines.md` |
| Context | Compact snapshots (`minimal`, `actions`, `read`, `full`), stable ids, collapse/expand/find, budgets, `within=` scoping | `snapshot.js`, `snapshot.py` |
| Task-aware context | `extract(fields=…)` with per-item fields, missing and conflicting fields; `LeanBrowser.context(goal, include, max_tokens)` with provenance, omitted count and expand hint | `extract.js`, `tools.py`, `examples/task_context.py` |
| Actions (v0.3) | Evidence-backed status (`verified` / `unverified` / `blocked` / `ambiguous` / `timed_out` / `done`); page errors beat "something changed"; submit-like actions need a strong signal; `expect=` postconditions; `last_outcome` dict; error categories; `confirm_risky` | `session.py`, `tests/test_reliability.py` |
| Safety (v0.3, v0.8) | Retry-safety classes; unsafe actions never retried; duplicate guard (`value="repeat"`), and with an optional `key` across sessions and restarts (24 h, claimed atomically); `dry_run` previews that dispatch nothing | `session.py`, `action_keys.py` |
| Recovery | One bounded re-resolution, by role + name + a non-contradicting fingerprint (href, test id, field name, form, row text, landmark); `ambiguous` and contradiction errors click nothing; conditional actions check state, then retry once after a re-render | `session.py` |
| Verification (v0.6 to v0.8) | 70-case verification suite incl. 24 red-team pages, run on both engines; errors in plain text, error routes, error dialogs and soft 404s beat success signals; success, error and `expect=` negation words in English plus ten languages; field and toast checks wait only for timers the page set; matrix: 0 false verified in 1,400 runs | `session.py`, `evals/bench/verification.py`, `scripts/verification_matrix.py`, `docs/RELIABILITY.md` |
| Network and isolation (v0.6 to v0.8) | Connect-time private-network guard on both engines (redirects, DNS rebinding, WebSockets), chained behind the user's `HTTP(S)_PROXY`; Chromium in its OS sandbox where the host allows it (doctor WARN otherwise); Obscura WebSocket pages move to Chromium | `netguard.py`, `engine.py`, `tests/test_netguard.py` |
| Memory | Session-scoped notes with source URL, in-process only | `memory` tool |
| Traces | Opt-in JSONL: run/step ids, outcome, recovery, error category; passwords, card/OTP/token-like fields and sensitive URL parameters redacted; page text opt-in; `leanb trace list / show / replay / export / delete` | `trace.py` |
| Visual | `screenshot(annotate=true)` maps the image to ids | `session.py` |
| Distribution and onboarding (v0.5) | `pipx install` from a GitHub tag; `leanb setup` (engines, doctor, Claude Code registration through `claude mcp`, asks first, idempotent); `leanb doctor` with PASS/WARN/FAIL/NOT SUPPORTED, `--json` and an MCP round trip; `leanb uninstall`; `install.sh` for contributors; CI on macOS 15, Ubuntu 24.04 x86_64 and arm64 with a clean-install test (wheel contents, spaced path, setup, doctor, MCP, pipx); release workflow with trusted publishing (not run yet) | `onboarding.py`, `doctor.py`, `claude_code.py`, `installer.py`, `scripts/smoke_clean_install.sh`, `.github/workflows/` |
| Real-site canary | 10 public read-only pages on both engines, weekly and by hand on macOS and Linux | `scripts/canary.py`, `canary.yml` |
| Benchmarks | Fixture suite of **100 tasks** in 9 categories, server-verified, each with a scripted reference solution; live suite of 51 real-site tasks (sandboxes, Wikipedia, Hacker News, TodoMVC), reported separately; Lean vs Playwright MCP × 3 runs, agent-browser × 1; per-category success, tasks solved in every run, p95, failure categories; parallel runs (`--jobs`) | `evals/`, `evals/bench/`, `docs/benchmark.md` |

## Next (in order)

1. **First-time user test (blocks a wide release):** three people who have never worked on Lean get only the
   GitHub link and follow the README to a first Claude Code task, unaided (protocol in `docs/RELEASING.md`).
   Fix repeated friction, then repeat.
2. **PyPI (maintainer decision):** set up trusted publishing, run the release workflow to TestPyPI, then publish a
   GitHub Release; switch the README to `pipx install lean-agent-browser`.
3. **Benchmark next steps:**
   - tasks written by someone other than us, and a few real-site workflows with sandbox accounts
   - 3 runs for agent-browser (it has 1), and its CLI workflow as a separate row
   - false-success and false-recovery counters
4. **Recovery metrics:** a stale-reference fixture set that measures recovery rate and false recovery.
5. **Task context:**
   - `context()` across pagination (follow "next" while `new_only`)
   - the same structured records from a table view
6. **Visual and DOM fusion:** suggest an annotated screenshot automatically when the DOM evidence is ambiguous
   (canvas, unlabeled controls), and record why.
7. **Session memory scopes:** split page, session and task state, with inspect and reset.
8. **Launch prep (after the user test):**
   - record a 30–45 s demo (install, connect, task, verified result)
   - write a launch post with the methodology

## Not now

- a new rendering engine
- a generic autonomous agent loop
- a hosted cloud
- a dashboard
- anti-bot claims
- more MCP tools just to have more tools
- an LLM call per click
- cross-session memory without demand
- Windows

## Claims policy

- Never claim "first", "works on every website", or a win over a competitor's whole product.
- Every number links to its method in `evals/CHANGELOG.md`, with run counts and caveats.
