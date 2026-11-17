# Changelog

## 0.5.0 (2026-11-18): install and connect without help

**Onboarding**
- `leanb setup`: a guided first run. It checks the platform, downloads the pinned engines (asks first), writes a
  commented default config only if none exists, runs the doctor, and registers Lean with Claude Code. It
  shows the exact entry and asks before changing anything (`--yes` accepts every prompt). Safe to re-run.
- Claude Code registration goes through `claude mcp add-json / get / remove` with the absolute path of the
  running `leanb`, user scope by default. A second run changes nothing, a moved install updates the entry
  instead of adding a second one, and other MCP servers are never touched.
- `leanb doctor` reports each check as PASS, WARN, FAIL or NOT SUPPORTED with a fix line. New checks: platform
  support, Python and dependencies, config validity (bad TOML, unknown keys, private network left on), an
  MCP round trip through the real `leanb mcp` command, and the Claude Code entry (missing, or pointing to a
  deleted install). `--json` gives the same result for bug reports, with home paths shortened to `~`.
- `leanb uninstall` removes the engines and the `lean-browser` Claude Code entry after listing them
  (`--all` also removes config and traces). `leanb --version`.
- Opening a localhost or LAN address now says why it was blocked and how to allow it, instead of
  `net::ERR_BLOCKED_BY_CLIENT`.

**Packaging**
- One version source (`lean_browser.__version__`); the MCP server reports it too (it said 0.1.0).
- The wheel ships only `lean_browser`; `evals/` runs from a checkout (`python -m evals.runner` replaces
  the `leanb-eval` script). A top-level `evals` package could clash with other packages.
- Release workflow: build once, test that wheel on all three platforms, attach checksums, publish with PyPI
  trusted publishing when a GitHub Release is published. Not published yet.
- The clean-install test checks the wheel's contents, installs into a path with a space, runs `setup`,
  `doctor --json` and pipx.

**Docs**
- README starts with Install for Claude Code, First task and Develop / contribute. The `memory` tool is in
  the tools table, and the outdated "private repository" note is gone.
- New: `docs/TROUBLESHOOTING.md`, `docs/UPGRADING.md`, `docs/RELEASING.md` (release checklist, Claude Code
  acceptance test, first-time user test), `docs/BASELINE.md`; issue and PR templates.
- Security docs say plainly that Playwright runs Chromium with its own sandbox off, and that dropping hidden
  text does not prevent prompt injection.

## 0.4.0 (2026-11-16): 100-task benchmark and Linux

**Benchmark**
- The fixture suite grew from 20 to **100 tasks** in nine categories (`evals/bench/`). Each task has a
  server-side verifier and a scripted reference solution that the test suite runs.
- Full run, Claude Sonnet 5.5 via `claude -p`, 3 runs each: Lean 300/300 with a median of 13,181 tokens per
  task, Playwright MCP 300/300 with 46,946 (after one fixture correction, explained in `docs/benchmark.md`).
  Lean used fewer tokens on all 100 tasks.
- `claude_driver --jobs N` runs agents in parallel, each with its own fixture server; `--tags` picks a
  category; `--resume` continues an interrupted run, and a Claude usage limit stops the run cleanly instead
  of recording runs that never happened. The report adds success by category and tasks solved in every run.

**Fixes found by the benchmark**
- Ids follow the row a control is in. After a list re-rendered in a new order, an id could move to
  another row's button, and Lean approved the wrong person's request.
- Repeated controls say which row they belong to: `button "Approve" (in "Nisha Gupta, 2 days")`.
- Switch and custom checkbox state comes from `aria-checked` (Obscura reported every switch as off).
- Sliders, both native range inputs and ARIA sliders, can be set with `fill` and are verified.
  `fill` used to claim "value set" on a slider it never moved.
- Buttons inside headings get ids. Disclosures show `[open]`/`[closed]` and the text they reveal.
- Pages with srcdoc or nested iframes go to Chromium.
- `act(dialog, "accept:TEXT")` answers a `prompt()`.

**Linux**
- Supported and tested in CI: Ubuntu 24.04 on x86_64 and arm64, next to macOS 15 on Apple Silicon.
- Pinned, hash-checked Obscura 0.2.7 builds per platform.
- On Linux, Obscura runs only under bubblewrap: no home folder, read-only system folders, its own user and
  PID namespaces, and it dies with its client. Without bubblewrap, Chromium serves every page.
- `install.sh` hands engine installation to `leanb install`, so the hashes live in one place.

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
