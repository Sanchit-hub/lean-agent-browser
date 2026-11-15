# Changelog

## 0.3.0 (2026-11-15): Reliability & Trust

The goal of this release: an agent can tell not only what it can click, but whether the action actually
worked. The audit is in [`docs/v0.3-gap-analysis.md`](docs/v0.3-gap-analysis.md).

**Verified outcomes**
- New statuses `blocked` (the page rejected it, or Lean refused it) and `ambiguous` (it may or may not
  have been sent), alongside `verified`, `unverified`, `timed_out` and `done`.
- Page errors come first: field errors, error alerts and HTTP 4xx/5xx. A rejected login or signup used
  to come back `verified (page changed)`; it now comes back `blocked`.
- Submit-like actions need a strong signal: navigation, a success message, a cleared form, or the
  target going away. A UI change alone stays `unverified`.
- `expect=` on `act` and `fill_form` takes text, `url:<part>` or `gone:<id>`, checked for up to 3 s.
- `LeanBrowser.last_outcome` returns the result as a dict. `LeanBrowserError.category` gives one of
  `blocked`, `ambiguous`, `stale`, `not_found`, `timeout`, `network`, `invalid`, `engine`.

**Safe recovery**
- Every action has a retry-safety class: `safe`, `conditional` or `unsafe`. Unsafe actions are never
  retried automatically.
- Duplicate guard: repeating a submit, payment, delete or send on the same page after a `verified`,
  `ambiguous` or `timed_out` outcome is blocked unless you pass `value="repeat"` (`submit="repeat"`).
- Fills, selects and checks check for partial success first. If the target was re-rendered, they
  re-identify it and retry once.
- An Obscura click that navigates no longer surfaces as a raw "execution context destroyed" error.

**Dry run**
- `dry_run=true` on `act` and `fill_form` returns `{"executed": false, target, risk, retry_safety,
  requires_confirmation}` and dispatches nothing. Tests check this with a page that counts every event,
  with the server's state and the field values, and confirm the engine isn't switched.

**Traces**
- Each record adds `run`, `step`, `outcome` (evidence, recovery, retry safety) and an error `category`.
- More redaction: card, CVV, OTP, PIN, token and ID-like fields, and sensitive URL parameters.
- Page text is now opt-in (`trace_page_text`). By default a record keeps only the status and header lines.
- `trace show` prints `ERROR:<category>` and the recovery steps.

**Release validation**
- `scripts/smoke_clean_install.sh` builds the wheel, installs it into a fresh venv, then runs
  `leanb install`, `leanb doctor` and an MCP round trip. It runs in CI.
- Eval reports now show p95 tokens and time, and failure categories.
- Two reliability eval tasks: `order-once` and `honest-failure`. Method: [`docs/benchmark.md`](docs/benchmark.md).

**Compatibility**
- Tool count stays at 7, and the schemas stay within the 700 proxy-token budget.
- Status lines changed: `fill_form` evidence is now separated by `;`, and some clicks that used to say
  `verified` now say `blocked` or `unverified`, which is the point of this release.
- Supported: macOS on Apple Silicon only.

**Not in this release**
- A 100-task benchmark. There are 20 fixture tasks and 5 live tasks.
- Linux support. This is the maintainer's macOS-only decision.
- Testing by outside developers.

## 0.1.0 (2026-11-14)

First version: Obscura-first browser with Chromium fallback, compact snapshots, diffs, 7 MCP tools, CLI,
Python API, eval harness.
