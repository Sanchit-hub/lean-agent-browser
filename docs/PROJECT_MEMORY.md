# Project memory: Lean Agent Browser

A living record of what this project is, what has been decided, and what is on this Mac.
Update it whenever something important changes. Last updated: 2026-11-15 (night).

## What we're building
A token-lean browser for AI agents. Pages come back as compact text with numeric ids, and actions
return a verified status plus only the changes. Obscura (a Rust headless browser) is the default engine,
with Chromium as the fallback. It is exposed as an MCP server, a CLI (`leanb`) and a Python API
(`from lean_browser import LeanBrowser`).

**Positioning:** fewer tokens, fewer tool calls, verifiable actions, so a lower cost per successful task.

## Key results (details in `evals/CHANGELOG.md`)
- **Fixture suite** (18 tasks, Claude Sonnet 5.5 via `claude -p`):

  | Mode | Success | Median tokens per task |
  |---|---|---|
  | **Lean** | **54/54** | **11.6k** |
  | Playwright MCP | 54/54 | 48.6k |
  | Vercel agent-browser (1 run) | 17/18 | 146k |

- **Tool-definition cost per request** (measured with `claude -p`): lean ~1.55k tokens, Playwright MCP
  ~7.1k, agent-browser ~31.6k.
- **Snapshot speed on Obscura:** GitHub repo page ~90 ms, after switching to `checkVisibility()`.
- **Live suite** (5 public pages, 1 run each): Playwright MCP 5/5 with 134.6k tokens, lean 5/5 with
  49.4k tokens. Lean's Halley task first hung; that was fixed, see below.

## Decisions (and why)
- **macOS (Apple Silicon) only** for now. This was the user's choice.
- **Commits carry the user's name only:** the GitHub noreply email, and no Claude co-author trailer.
- **Work autonomously:** commit and push after each step, and pick details yourself.
- **Obscura is pinned to 0.2.6 and hash-checked on every launch.** The binary is only ad-hoc signed,
  so it always runs under `sandbox-exec`.
- **Pages with file inputs, rich-text editors or cross-origin iframes go to Chromium.** Obscura drops
  files without any error, ignores typing in editors, and can't read cross-origin frames.
- **The private-network block applies on both engines**, so a fallback never widens access.
- **Evals run through `claude -p`**, on the subscription, because the API account has no credits.
- **License:** Apache-2.0.

## What is installed where on this Mac
| Path | What it is |
|---|---|
| `~/Desktop/lean/` | The repo (GitHub: Sanchit-hub/lean-agent-browser, private) |
| `~/Desktop/lean/.venv/` | Python env (`pip install -e ".[dev]"`) |
| `~/.lean-browser/bin/obscura`, `obscura-worker` | Obscura 0.2.6. Release SHA256 `19faa248…bd0`; binary hashes are in `engine.py` |
| `~/.lean-browser/pw-browsers/` | Playwright Chromium (Chrome for Testing) |
| `~/.lean-browser/traces/` | Traces from `leanb --trace` (dir 700, files 600) |
| `~/Desktop/lean/.vendor/` | Spike copy of Obscura, Playwright MCP 0.0.83, agent-browser 0.41.0 (eval baselines) |
| `~/Desktop/lean/evals/results/` | Raw eval runs (gitignored) |
| `~/Desktop/lean/.env` | Gitignored, chmod 600. **Holds an API key that was pasted in chat: revoke it and delete the line.** |
| `~/.claude/projects/-Users-sanchitthareja-Desktop-lean/memory/` | Claude's memory notes for this project |

## Obscura quirks we work around
- No CDP dialog events: an init-script shim handles alert, confirm and prompt.
- Multipart forms drop the file (routed to Chromium).
- `el.required`, `img.alt`, `table.rows` and `row.cells` are missing.
- Reading several computed-style properties from one style object is very slow, so the walker uses
  `checkVisibility()`.
- Any DOM write invalidates style for the whole page, so `data-lab-id` writes are batched at the end
  of the walk.
- An inline `<a><svg>` reports a 0×0 rect.
- `page.route` doesn't block subresources.
- Some pages (Wikipedia's Halley's Comet article) leave Obscura's script thread stuck after load.
  Fix: settle probes are time-boxed, the page moves to Chromium (`page unresponsive on obscura`), and
  the hung process restarts.
- Obscura runs under a sandboxed sh watchdog that stops it when the Python client dies, even on
  `kill -9`, so no orphaned engines are left behind.

## How to resume
```bash
cd ~/Desktop/lean && .venv/bin/leanb doctor && .venv/bin/python -m pytest -q
.venv/bin/python -m evals.claude_driver --suite live --modes lean     # the pending live run for lean
```

**Next:**
- automatic choice of when to use a screenshot
- Stagehand and Browser Use in their own benchmark category (they need their own LLM keys)
- publish to PyPI and make the repo public, both only when the user decides
