# Roadmap

**Direction:** a context-efficient, reliable browser interaction layer for AI agents. The product
promise is a lower total cost per *successful* task, backed by two things: less context and fewer
failed actions. Every claim needs a reproducible benchmark.

**Principles:**
- deterministic before intelligent
- never hide uncertainty
- verify outcomes
- keep the agent in control (primitives, not an opaque autonomous loop)
- measure complete tasks
- keep the engine replaceable
- safe by default

**Platform:** macOS (Apple Silicon) only for now.

## Done

- Obscura-first engine with Chromium fallback and feature-based routing. Obscura is pinned,
  hash-verified and sandboxed.
- Compact snapshots: stable ids, collapse/expand/find, budgets, `read` and `full` modes.
- Action diffs after a settle wait, `fill_form`, deterministic `extract`, tabs, dialogs, upload allowlist.
- MCP server, CLI (`open`, `shell`, `doctor`), Python API, `install.sh`, macOS CI.
- A real-agent eval against Playwright MCP: both 54/54, lean uses 4.5× fewer tokens. See `evals/CHANGELOG.md`.

## Next, in order

### 1. Verified actions and safe recovery
Every action returns a structured status: `verified`, `unverified`, `ambiguous`, `blocked` or
`timed_out`, plus evidence (URL changed, new heading, field value, error text).
- **Stale ids:** refresh the snapshot, re-resolve only when the role, name and surroundings still
  match, and retry at most once.
- **Irreversible actions** (submit, delete, pay, send) are never retried silently.
- **Metrics:** recovery rate, false-success rate, task completion.

### 2. Scoped context with provenance (deterministic first)
- `snapshot(within=id)`, plus `extract(fields=[...])` scoped to a table, list, form or region.
- Every extracted fact carries its source element id and URL.
- Track what the agent has already seen, so later calls return only new or changed facts.
- Goal-based relevance comes later and is opt-in only. It needs fuzzy matching or an LLM, which works
  against "deterministic first", and it must never silently drop evidence.

### 3. Trace and reproducible benchmark
- A JSONL trace of every call: input, target resolution, context sent, changes, verification, timing.
- `leanb trace show <run>`.
- `leanb bench --suite core --runs N`, with Markdown and JSON output and failures included.
- Add Vercel Agent Browser as a second baseline. It is also a tool, so it runs with the same agent and
  the comparison is fair.
- Report Stagehand and Browser Use separately. Both run their own LLM calls or agent loop, so they are
  not apples-to-apples.
- Add some third-party or live-site tasks next to our own fixtures, labelled as live, where results vary.

### Later
- **Visual and DOM fusion:** targeted screenshots only when DOM evidence is ambiguous (canvas, charts,
  spatial UIs).
- **Task and session memory** with explicit scopes, expiry and provenance.
- **Adaptive budget strategies:** `minimal`, `balanced`, `complete`.
- **Packaging:** `pip install` plus `leanb install` for the engines.

## Not now

- A new rendering engine.
- A generic autonomous agent loop.
- A hosted cloud.
- A dashboard before the CLI and API are excellent.
- Anti-bot claims.
- An LLM call per click.
- Linux/Docker support.

## Before any public comparison

Re-check competitor features against their current docs. Never claim to be "the first token-efficient
browser" or "the first with diffs".
