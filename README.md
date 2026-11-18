# Lean Agent Browser

[![CI](https://github.com/Sanchit-hub/lean-agent-browser/actions/workflows/ci.yml/badge.svg)](https://github.com/Sanchit-hub/lean-agent-browser/actions/workflows/ci.yml)
![platform](https://img.shields.io/badge/platform-macOS%20arm64%20%7C%20Linux%20x86__64%2Farm64-lightgrey)
![license](https://img.shields.io/badge/license-Apache--2.0-blue)

**Lean Agent Browser is a reliable execution layer for AI agents on the web: compact context, actions
that are verified against evidence, and safe recovery when pages change.**

**[Install for Claude Code](#install-for-claude-code)** (recommended) · **[First task](#first-task)** ·
**[Develop / contribute](#develop--contribute)** · [Troubleshooting](docs/TROUBLESHOOTING.md)

## Install for Claude Code

| | |
|---|---|
| **Supported** (tested in CI) | macOS 15+ on Apple Silicon · Ubuntu 24.04 on x86_64 and arm64 |
| **Not supported** | Windows, Intel Macs, other Linux distributions (untested; Chromium alone may work) |
| **You need** | Python 3.12+, [pipx](https://pipx.pypa.io), [Claude Code](https://claude.com/claude-code), git, and internet access for a one-time engine download (~700 MB on disk) |
| **Linux only** | `sudo apt install bubblewrap`. Without it Obscura stays off and Chromium serves every page |

Lean is not on PyPI yet. Until it is, install a tagged release straight from GitHub (a preview of the
final `pipx install lean-agent-browser`):

```bash
pipx install "git+https://github.com/Sanchit-hub/lean-agent-browser@v0.7.0"
```

```bash
leanb setup
```

`leanb setup` asks before it changes anything. It:
1. checks that your platform is supported,
2. downloads the two browser engines into `~/.lean-browser` (Obscura, pinned and SHA256-checked, and
   Playwright's Chromium). It never touches your own Chrome or its profile,
3. runs `leanb doctor`: both engines load a page, and the MCP server starts and answers,
4. shows the exact Claude Code entry it will add (`claude mcp add-json -s user lean-browser ...`, with the
   absolute path of `leanb`), then adds it. Other MCP servers are not touched, and re-running updates the
   entry instead of adding a second one.

Then start a new Claude Code session and run `/mcp`: `lean-browser` should show as connected.
Run `leanb setup --yes` to accept every prompt. On Linux, if `leanb doctor` says Chromium's system
libraries are missing, run the one `sudo` command it prints.

<details><summary>Register with Claude Code by hand instead</summary>

```bash
claude mcp add -s user lean-browser -- "$(command -v leanb)" mcp
```
</details>

Updating and removing: [`docs/UPGRADING.md`](docs/UPGRADING.md) (`pipx upgrade lean-agent-browser`, then
`leanb setup`; `leanb uninstall` removes the engines and the Claude Code entry). If something fails, run
`leanb doctor` and see [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).

## First task

Paste this into Claude Code:

```text
Use Lean Agent Browser to open https://example.com.
Take a compact snapshot and explain the page's main content.
Do not submit forms, purchase anything, or perform any external side effect.
```

You should see Claude call `lean-browser` tools (`open`, then maybe `snapshot`) rather than answer from
memory. Then a practical read-only task:

```text
Use Lean Agent Browser to open https://news.ycombinator.com/.
Find the first five story titles and their links.
Return them as a numbered list with the source URL.
```

Before you let an agent submit forms or make purchases, read [Outcomes you can trust](#outcomes-you-can-trust):
a click being sent is not proof that it worked, and an `ambiguous` result must not be retried blindly.
Page content is untrusted data, and localhost and LAN addresses are blocked unless you allow them.

## How it compares

| 100 tasks, same agent (Claude Sonnet 5.5) | Success | Median tokens per task | Mean turns | Median time |
|---|---|---|---|---|
| Playwright MCP 0.0.83 (3 runs) | 300/300 * | 46,946 | 6.9 | 18.1 s |
| **Lean Agent Browser (3 runs)** | **300/300** | **13,181** | **5.1** | **11.6 s** |

Lean used fewer tokens than Playwright MCP on every one of the 100 tasks: 3.9× fewer on the median task.
The tasks cover forms, multi-step flows, reading, navigation, widgets, dialogs, frames, dynamic pages and
safety. \* 297/300 as run; one fixture was corrected and rerun, see [`docs/benchmark.md`](docs/benchmark.md).
On the older 18-task suite, Vercel agent-browser 0.41.0 (MCP `core` profile, 1 run) scored 17/18 with a
median of 146,314 tokens per task.

Success is checked by the test server, not by what the agent claims. The method, the raw numbers and
the limitations are in [`evals/CHANGELOG.md`](evals/CHANGELOG.md).

## What the agent sees

```
page: Sign up | url: /signup.html | engine: obscura
header: Home, Search, Orders (+5) [expand:h1]
# Create your account
9: textbox "Username"*
10: textbox "Email"* type=email = "asha@" !"Enter a valid email address"
11: textbox "Password"* type=password = ••••
13: checkbox "I accept the terms" off
14: button "Create account"
```

Act on an id, and you get back a status backed by evidence, plus only what changed:

```
> act fill 10 asha@example.com
status: verified (value set)
~10: textbox "Email"* type=email = "asha@example.com"   (error cleared)

> act click 14
status: blocked (page shows errors: Password: "Password must be at least 10 characters")
```

## Outcomes you can trust

A click being sent is not the same as the task succeeding. Every `act` and `fill_form` returns one of:

| Status | Meaning |
|---|---|
| `verified` | Evidence that it worked: the value is set, or after a submit the page navigated without errors, a success message appeared, the form was cleared, or your `expect=` matched |
| `unverified` | It ran, but nothing shows that it worked (no change, or a submit with no success signal) |
| `blocked` | The page rejected it (field errors, an error alert, a "not saved"-style message, HTTP 4xx/5xx), the form's own validation stopped the submit (required, email, pattern), or Lean refused it (confirmation needed, duplicate) |
| `ambiguous` | It may or may not have been sent (an error after dispatch); check before doing anything else |
| `timed_out` | The page was still busy when the wait ended |
| `done` | Hover, focus, scroll: nothing to verify |

- **`expect=`** states the postcondition: text that must appear, `url:/thanks`, or `gone:<id>`. For a click or
  submit the evidence must be new: text that was already on the page, or appears as "not saved", doesn't count.
- **No false success.** A submit is `verified` only on a navigation (not the same form coming back), a new
  success message that isn't negated, or the button or form clearing without a "Processing…" left on the page.
  While the page says it is still processing, Lean waits up to 8 s for the answer. A release fails if any
  case in the verification suite reports `verified` for an outcome that didn't happen; the rules and the
  suite are in [`docs/RELIABILITY.md`](docs/RELIABILITY.md).
- **Duplicate guard.** Submits, payments, deletes and sends are classed `unsafe`. Lean never retries
  them, and repeating one on the same page after a `verified`, `ambiguous` or `timed_out` outcome is
  blocked unless you pass `value="repeat"` (`submit="repeat"` for forms).
- **Safe recovery.** A re-rendered target is re-found by role, name and fingerprint, only when the
  match is unambiguous. Fills, selects and checks check the field state first, and retry once only
  if they didn't stick.
- **Dry run.** `dry_run=true` returns the resolved target, risk, retry safety and whether confirmation
  would be needed, as JSON with `"executed": false`. Nothing is dispatched.
- From Python, `browser.last_outcome` has the same result as a dict (`status`, `evidence`,
  `retry_safety`, `recovery`), and `LeanBrowserError.category` classifies errors.

## Use it from Python


```python
from lean_browser import LeanBrowser

async with LeanBrowser() as browser:
    page = await browser.open("https://httpbin.org/forms/post")
    print(page)                                    # ids for every field
    print(await browser.fill_form({1: "Asha", 3: "asha@example.com"}, submit=True))
```

More in [`examples/`](examples/): `quickstart.py`, `form_fill.py` (fills a public form in one call and
checks what the server received), `structured_extract.py` (a Wikipedia table as JSON, no LLM involved),
and `task_context.py` (task-aware context: sourced product records with explicit missing fields, and the
comparison done in your code).

## Tools (MCP)

There are seven tools. Claude counts their definitions at about 1.5k tokens, and they are sent with every request (Playwright MCP's come to ~7.1k, agent-browser's default profile to ~31.6k; measured with `claude -p`, see `evals/CHANGELOG.md`):

| Tool | What it does |
|---|---|
| `open(url, mode?, block?)` | Navigate, then return a snapshot. `mode` is `minimal` (interactive elements only), `actions` (default), `read` (markdown) or `full`. |
| `snapshot(mode?, budget?, expand?, more?, find?, within?)` | Current page. `expand:h1` opens a collapsed group, `more:k1` continues cut-off output, `find` searches everything (including collapsed rows), and `within=<id>` shows only the form, table or section containing that element. |
| `act(action, id?, value?, expect?, dry_run?)` | Actions: `click`, `fill`, `select` (an option label, also works on custom dropdowns), `check`, `uncheck`, `clear`, `press`, `hover`, `focus`, `upload`, `scroll`, `back`, `forward`, `reload`, `wait_for`, `tab` (`list` / `new:URL` / `switch:N` / `close:N`), `dialog` (`accept` / `dismiss` the next native dialog). Returns a status line (see [Outcomes](#outcomes-you-can-trust)) and a diff. A re-rendered element is re-found once by role and name, and the match must not contradict its fingerprint (link target, test id, field name, form, row text, landmark). If the match is ambiguous or contradicted, nothing is clicked. |
| `fill_form(fields, submit?, expect?, dry_run?)` | `{id: value}` for a whole form in one call. `submit=true` clicks the form's submit button. |
| `extract(kind?, within?, fields?, new_only?)` | Deterministic JSON for a `table`, `list` or `form` (no LLM involved). Every result carries its source URL, plus row or item numbers and element ids. `fields` picks columns, and `new_only` returns only rows not returned before, which suits pagination and infinite scroll. |
| `memory(action, key?, value?)` | Notes the agent keeps across pages (`set`, `get`, `list`, `delete`, `clear`), each with its source URL, so a value read on one page can be used on another. |
| `screenshot(id?, annotate?)` | Viewport or element PNG. `annotate=true` draws each snapshot id on its element, so the image maps back to ids the agent can act on. Only for captchas, charts or layout. |

## How it works

```
agent ──MCP / CLI / Python──▶  7 tools  ──▶  snapshot · act · diff · settle  ──▶  Obscura (default, ~3× less memory)
                                                                             └─▶  Chromium (file uploads, rich-text
                                                                                  editors, cross-origin, srcdoc and
                                                                                  nested iframes, failures)
```

- **Compact snapshots.** One line per interactive element, each with a stable id. Navigation, footers
  and long lists collapse into one line you can expand. Hidden text is dropped.
- **Diffs, not page dumps.** After every action the browser waits for the page to settle and
  returns only the changes, or `no change` plus a hint.
- **Two engines, one API.** Obscura serves pages by default. Pages it can't handle go to Chromium
  before any action. The routing rules come from tests documented in [`spike/FINDINGS.md`](spike/FINDINGS.md).

## Limitations

- **Supported (tested in CI):** macOS 15+ on Apple Silicon, and Ubuntu 24.04 on x86_64 and arm64. No Windows.
  On Linux, Obscura runs only under bubblewrap; without it, Chromium serves every page.
- The benchmark is 100 fixture tasks we wrote ourselves, on a local test site. It measures these tasks, not
  every website, and it is not proof against every browser agent. See [`docs/benchmark.md`](docs/benchmark.md).
- Verification is heuristic: success and error words are English-only, and a site that shows neither
  stays `unverified`. Pass `expect=` when it matters.
- The duplicate guard is per session and per page. It can't see side effects from another session.
- A dry run reflects the page at that moment; the page can change before you execute.
- This release has not yet been tested by outside developers, and it is not on PyPI yet.
- Obscura 0.2.7 can't upload files, type into rich-text editors, open popups, read cross-origin iframes,
  run scripts in srcdoc iframes or reach nested iframes. Those pages run on Chromium automatically.

See [`ROADMAP.md`](ROADMAP.md) for what's next.

## CLI

```bash
leanb open https://news.ycombinator.com/          # one-shot snapshot
leanb open https://en.wikipedia.org/wiki/Rust --mode read
leanb shell https://example.com/login             # interactive: act / fill / find / expand / extract ...
leanb setup                                       # guided first run (engines, checks, Claude Code entry)
leanb doctor                                      # check the install: PASS / WARN / FAIL / NOT SUPPORTED per check
leanb doctor --json                               # the same, for a bug report (home paths shortened to ~)
leanb uninstall                                   # remove the engines and the Claude Code entry (--all: config too)
leanb --version
leanb --allow-private-network open http://localhost:3000   # local dev servers
```

## Config

Optional, at `~/.lean-browser/config.toml`:

```toml
prefer = "obscura"                  # or "chromium"
allow_private_network = false       # localhost / LAN / cloud metadata are blocked on BOTH engines unless true
allowed_domains = []                # e.g. ["example.com"]: refuse to open anything else
fallback_domains = []               # always use Chromium for these hosts
allowed_upload_dirs = ["~/Downloads"]
block = true                        # Chromium: skip images, fonts, media and tracker hosts
confirm_risky = false               # true: pay/delete/send-like buttons need act(..., value="confirm")
trace = false                       # JSONL trace of every call in ~/.lean-browser/traces (local only)
trace_page_text = false             # also keep page text in traces (off: status/header lines only)
snapshot_timeout_s = 2.0            # slower snapshots move the page to Chromium
```

## Security model

- **Obscura is pinned and verified.** Obscura 0.2.7 is pinned, and the SHA256 of both binaries is
  re-checked on every launch. It **always runs sandboxed**: macOS `sandbox-exec`, or bubblewrap on
  Linux. It can't read your home folder, can only write to its own temp dir, and its CDP server only
  listens on localhost. Its CDP port is bound to 127.0.0.1 and needs a
  random 32-byte token per launch.
- **Chromium never touches your profile.** It is Playwright's bundled build with a throwaway
  profile, not your own Chrome. It is not OS-sandboxed by Lean: Playwright starts Chromium with
  Chromium's own sandbox turned off, so pages that fall back to Chromium don't get Obscura's isolation.
  The network rules below still apply to it.
- **No private network by default.** localhost, RFC1918 and link-local (including 169.254.169.254)
  are blocked on both engines unless you set `allow_private_network`, so falling back to Chromium
  never widens network access. Both engines connect through a local guard that checks the resolved
  address at connect time, so a public page that redirects to an internal address, or a hostname that
  re-resolves to one, is refused too. Behind your own `HTTP(S)_PROXY` the guard chains to it (limits in
  SECURITY.md).
- **Untrusted page content.** Everything taken from a page comes back inside
  `<page untrusted="true">…</page>`, and the MCP server instructions tell the agent to treat it as
  data. Hidden text (`display:none`, off-screen, `aria-hidden`, tiny fonts) is dropped, which removes
  a common prompt-injection trick. This does not prevent prompt injection: visible text can still
  carry instructions, and the agent has to treat it as data. Password values are never shown (`••••`).
- **Uploads are restricted.** Only absolute paths inside `allowed_upload_dirs` can be uploaded.

## How it decides between Obscura and Chromium

Obscura is the default. A page goes to Chromium **before any action** if it has a file input or a
multipart form (Obscura drops the file without any error), a visible rich-text editor (typing is
ignored), or a cross-origin iframe. A page also moves to Chromium if a snapshot takes longer than
2 s, if navigation fails, or if Obscura isn't installed. Cookies are carried over. Every routing rule
comes from a test in `spike/FINDINGS.md`.

## Develop / contribute

For contributors, or to run unreleased changes. This is a separate install from the one above, with the
same code and the same `~/.lean-browser` engines.

```bash
git clone https://github.com/Sanchit-hub/lean-agent-browser && cd lean-agent-browser
./install.sh                                         # .venv with pinned deps, engines, then leanb doctor
# Linux: sudo apt install bubblewrap and, once, sudo .venv/bin/python -m playwright install-deps chromium
.venv/bin/leanb open https://news.ycombinator.com/   # print a snapshot
.venv/bin/leanb setup --client claude                # point Claude Code at this checkout
```

`./install.sh`:
- creates `.venv/` with pinned Python dependencies (the dev extras used by CI)
- downloads **Obscura 0.2.7** and checks its SHA256 against a pinned value
- installs the Obscura binaries to `~/.lean-browser/bin/` and re-checks their hashes
- installs Playwright's Chromium to `~/.lean-browser/pw-browsers/`
- runs `leanb doctor` to check everything works

Tests need no API key. To also install the Playwright MCP and agent-browser baselines used by the evals
(needs Node.js 20 or later), run `./install.sh --with-eval`. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

### Evals

**No API key? Use your Claude subscription.** `evals/claude_driver.py` runs the same tasks with the
Claude Code CLI (`claude -p`) as the agent. Built-in tools are disabled, only the browser MCP server
under test is attached, and the system prompt is our own:

```bash
.venv/bin/python -m evals.claude_driver --quick      # 6 tasks: Playwright MCP vs lean
.venv/bin/python -m evals.claude_driver --runs 3 --jobs 5   # all 100 tasks x 2 modes x 3 runs, 5 at a time
.venv/bin/python -m evals.claude_driver --tags safety       # one category
```

**With an API key** (in your environment, or in the gitignored, `chmod 600` file `.env`):

```bash
export ANTHROPIC_API_KEY=...
.venv/bin/python -m evals.runner --estimate          # cost before anything runs
.venv/bin/python -m evals.runner --quick             # 6 tasks, Playwright MCP vs lean, 1 run (~$1)
.venv/bin/python -m evals.runner -y                  # all tasks × 6 modes × 3 runs (costly: check --estimate first)
.venv/bin/python -m evals.runner --schema-tokens     # exact tool-definition tokens per mode
```

- Tasks run against a local fixture site (`evals/fixtures/`), and **success is checked by the server**,
  not by what the agent says.
- There are six modes: screenshot, full HTML, aria snapshot, Playwright MCP, lean, and lean with
  automatic escalation.
- The report is written to `evals/report.md`.

### Tests and layout

```bash
.venv/bin/python -m pytest -q        # 464 passed, 3 skipped on 2026-11-18 (macOS arm64); local fixture site, both engines
.venv/bin/python scripts/snap.py login.html,orders.html obscura    # look at snapshots
```

Layout:
- `lean_browser/`: engine.py (Obscura + Chromium, routing, sandbox), snapshot.js and snapshot.py,
  settle.py, diff.py, session.py, extract.js, tools.py, mcp_server.py, cli.py
- `evals/`: fixtures/, tasks.py, oracle.py, modes.py, runner.py, report.py
- `spike/`: the original Obscura vs Chromium investigation
