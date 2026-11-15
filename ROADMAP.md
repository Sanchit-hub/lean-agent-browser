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

**Platform decision:** macOS (Apple Silicon) only, by the maintainer's choice. Linux and Windows
support (listed as P0 in the November 2026 review) is deliberately out of scope for now. Only
CI-tested platforms are listed as supported.

## Implemented (verified in code and tests, 2026-11-15)

| Area | What exists | Where |
|---|---|---|
| Engines | Obscura **0.2.7** default (0.2.6 rollback), hash-pinned, sandboxed, parent-death watchdog; Chromium fallback with capability routing; hung pages move to Chromium | `engine.py`, `docs/engines.md` |
| Context | Compact snapshots (`minimal`, `actions`, `read`, `full`), stable ids, collapse/expand/find, budgets, `within=` scoping | `snapshot.js`, `snapshot.py` |
| Task-aware context | `extract(fields=…)` with per-item fields, missing and conflicting fields; `LeanBrowser.context(goal, include, max_tokens)` with provenance, omitted count and expand hint | `extract.js`, `tools.py`, `examples/task_context.py` |
| Actions | Status per action (`verified` / `unverified` / `timed_out`), evidence, `fill_form` field verification, `confirm_risky` | `session.py` |
| Recovery | One bounded re-resolution, by role + name + a non-contradicting fingerprint (href, test id, field name, form, row text, landmark); `ambiguous` and contradiction errors click nothing | `session.py` |
| Memory | Session-scoped notes with source URL, in-process only | `memory` tool |
| Traces | Opt-in JSONL with password redaction; `leanb trace list / show / replay / export / delete` | `trace.py` |
| Visual | `screenshot(annotate=true)` maps the image to ids | `session.py` |
| Distribution | `install.sh`, `pip install` + `leanb install` + `leanb doctor`, macOS CI | `installer.py`, `.github/workflows/ci.yml` |
| Benchmarks | Fixture suite (18 tasks, server-verified) and live suite (5 tasks), comparing Playwright MCP and agent-browser; tool-definition tokens reported separately | `evals/`, `evals/CHANGELOG.md` |

## Next (in order)

1. **Benchmark fairness:**
   - 3 runs for agent-browser (it has 1 so far)
   - its CLI and skill workflow as a separate row
   - p95 latency, model calls and browser tool calls in `summary.json`
   - false-success and false-recovery counters
2. **Recovery metrics:**
   - a stale-reference fixture set that measures recovery rate and false recovery
   - recovery decisions as structured trace fields, instead of only the result text
3. **Task context:**
   - `context()` across pagination (follow "next" while `new_only`)
   - the same structured records from a table view
4. **Visual and DOM fusion:** suggest an annotated screenshot automatically when the DOM evidence is ambiguous
   (canvas, unlabeled controls), and record why.
5. **Session memory scopes:** split page, session and task state, with inspect and reset.
6. **Launch prep (maintainer decisions):**
   - make the repo public
   - publish to PyPI (`lean-agent-browser` is free)
   - record a 30–45 s demo
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
- Linux/Windows (see the platform decision above)

## Claims policy

- Never claim "first", "works on every website", or a win over a competitor's whole product.
- Every number links to its method in `evals/CHANGELOG.md`, with run counts and caveats.
