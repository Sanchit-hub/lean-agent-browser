# Lean Agent Browser

[![CI](https://github.com/Sanchit-hub/lean-agent-browser/actions/workflows/ci.yml/badge.svg)](https://github.com/Sanchit-hub/lean-agent-browser/actions/workflows/ci.yml)
![platform](https://img.shields.io/badge/platform-macOS%20(Apple%20Silicon)-lightgrey)
![license](https://img.shields.io/badge/license-Apache--2.0-blue)

**Lean Agent Browser helps AI agents complete web tasks with less context, fewer tool calls, and actions
that report what actually changed.**

| Same 18 tasks, same agent (Claude Sonnet 5.5) | Success | Median tokens per task | Mean turns | Mean time |
|---|---|---|---|---|
| Playwright MCP 0.0.83 (3 runs) | 54/54 | 48,576 | 7.5 | 18.6 s |
| Vercel agent-browser 0.41.0, MCP `core` profile (1 run) | 17/18 | 146,314 | 8.7 | 16.1 s |
| **Lean Agent Browser (3 runs)** | **54/54** | **11,572** | **5.1** | **11.0 s** |

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

Act on an id, and you get back a verified status plus only what changed:

```
> act fill 10 asha@example.com
status: verified (value set)
~10: textbox "Email"* type=email = "asha@example.com"   (error cleared)
```

## Quickstart (macOS, Apple Silicon)

```bash
git clone https://github.com/Sanchit-hub/lean-agent-browser && cd lean-agent-browser
./install.sh                                         # pinned, checksummed Obscura + Chromium, then a self-check
.venv/bin/leanb open https://news.ycombinator.com/   # print a snapshot
```

Or as a package, without cloning (the repo is private for now, so this needs GitHub access; not on PyPI yet):

```bash
pip install "git+https://github.com/Sanchit-hub/lean-agent-browser"
leanb install    # pinned, checksummed Obscura + Chromium into ~/.lean-browser
leanb doctor
```

From Python:

```python
from lean_browser import LeanBrowser

async with LeanBrowser() as browser:
    page = await browser.open("https://httpbin.org/forms/post")
    print(page)                                    # ids for every field
    print(await browser.fill_form({1: "Asha", 3: "asha@example.com"}, submit=True))
```

More in [`examples/`](examples/): `quickstart.py`, `form_fill.py` (fills a public form in one call and
checks what the server received), and `structured_extract.py` (a Wikipedia table as JSON, no LLM involved).

## How it works

```
agent ──MCP / CLI / Python──▶  6 tools  ──▶  snapshot · act · diff · settle  ──▶  Obscura (default, ~3× less memory)
                                                                             └─▶  Chromium (file uploads, rich-text
                                                                                  editors, cross-origin iframes, failures)
```

- **Compact snapshots.** One line per interactive element, each with a stable id. Navigation, footers
  and long lists collapse into one line you can expand. Hidden text is dropped.
- **Diffs, not page dumps.** After every action the browser waits for the page to settle and
  returns only the changes, or `no change` plus a hint.
- **Two engines, one API.** Obscura serves pages by default. Pages it can't handle go to Chromium
  before any action. The routing rules come from tests documented in [`spike/FINDINGS.md`](spike/FINDINGS.md).

## Limitations

- **macOS on Apple Silicon only** for now. The Obscura sandbox uses macOS `sandbox-exec`.
- The benchmark compares against one baseline (Playwright MCP) on 18 tasks we wrote ourselves. It is a
  promising result, not proof against every browser agent.
- Obscura 0.2.7 can't upload files, type into rich-text editors, open popups or read cross-origin
  iframes. Those pages run on Chromium automatically.

See [`ROADMAP.md`](ROADMAP.md) for what's next.

## Install details

`./install.sh`:
- creates `.venv/` with pinned Python dependencies
- downloads **Obscura 0.2.7** and checks its SHA256 against a pinned value
- installs the Obscura binaries to `~/.lean-browser/bin/` and re-checks their hashes
- installs Playwright's Chromium to `~/.lean-browser/pw-browsers/`
- runs `leanb doctor` to check everything works

To also install the Playwright MCP baseline used by the evals (needs Node.js 20 or later), run
`./install.sh --with-eval`.

## Use it from Claude Code (MCP)

```bash
claude mcp add lean-browser -- "$PWD/.venv/bin/leanb" mcp
```

There are seven tools. Claude counts their definitions at about 1.5k tokens, and they are sent with every request (Playwright MCP's come to ~7.1k, agent-browser's default profile to ~31.6k; measured with `claude -p`, see `evals/CHANGELOG.md`):

| Tool | What it does |
|---|---|
| `open(url, mode?, block?)` | Navigate, then return a snapshot. `mode` is `minimal` (interactive elements only), `actions` (default), `read` (markdown) or `full`. |
| `snapshot(mode?, budget?, expand?, more?, find?, within?)` | Current page. `expand:h1` opens a collapsed group, `more:k1` continues cut-off output, `find` searches everything (including collapsed rows), and `within=<id>` shows only the form, table or section containing that element. |
| `act(action, id?, value?)` | Actions: `click`, `fill`, `select` (an option label, also works on custom dropdowns), `check`, `uncheck`, `clear`, `press`, `hover`, `focus`, `upload`, `scroll`, `back`, `forward`, `reload`, `wait_for`, `tab` (`list` / `new:URL` / `switch:N` / `close:N`), `dialog` (`accept` / `dismiss` the next native dialog). Returns a status line (`verified` / `unverified` / `timed_out`, with evidence) and a diff. A re-rendered element is re-found once by role and name; if that's ambiguous, nothing is clicked. |
| `fill_form(fields, submit?)` | `{id: value}` for a whole form in one call. `submit=true` clicks the form's submit button. |
| `extract(kind?, within?, fields?, new_only?)` | Deterministic JSON for a `table`, `list` or `form` (no LLM involved). Every result carries its source URL, plus row or item numbers and element ids. `fields` picks columns, and `new_only` returns only rows not returned before, which suits pagination and infinite scroll. |
| `screenshot(id?, annotate?)` | Viewport or element PNG. `annotate=true` draws each snapshot id on its element, so the image maps back to ids the agent can act on. Only for captchas, charts or layout. |

## CLI

```bash
leanb open https://news.ycombinator.com/          # one-shot snapshot
leanb open https://en.wikipedia.org/wiki/Rust --mode read
leanb shell https://example.com/login             # interactive: act / fill / find / expand / extract ...
leanb doctor                                      # check the install
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
snapshot_timeout_s = 2.0            # slower snapshots move the page to Chromium
```

## Security model

- **Obscura is pinned and verified.** Obscura 0.2.7 is pinned, and the SHA256 of both binaries is
  re-checked on every launch. The binary is only ad-hoc signed, so it **always runs under macOS
  `sandbox-exec`**: it can't read your home folder (except its own), can only write to its own temp
  dir, and only accepts connections on localhost. Its CDP port is bound to 127.0.0.1 and needs a
  random 32-byte token per launch.
- **Chromium never touches your profile.** It is Playwright's bundled build with a throwaway
  profile, not your own Chrome.
- **No private network by default.** localhost, RFC1918 and link-local (including 169.254.169.254)
  are blocked on both engines unless you set `allow_private_network`, so falling back to Chromium
  never widens network access.
- **Untrusted page content.** Everything taken from a page comes back inside
  `<page untrusted="true">…</page>`, and the MCP server instructions tell the agent to treat it as
  data. Hidden text (`display:none`, off-screen, `aria-hidden`, tiny fonts) is dropped, which removes
  a common prompt-injection trick. Password values are never shown (`••••`).
- **Uploads are restricted.** Only absolute paths inside `allowed_upload_dirs` can be uploaded.

## How it decides between Obscura and Chromium

Obscura is the default. A page goes to Chromium **before any action** if it has a file input or a
multipart form (Obscura drops the file without any error), a visible rich-text editor (typing is
ignored), or a cross-origin iframe. A page also moves to Chromium if a snapshot takes longer than
2 s, if navigation fails, or if Obscura isn't installed. Cookies are carried over. Every routing rule
comes from a test in `spike/FINDINGS.md`.

## Evals

**No API key? Use your Claude subscription.** `evals/claude_driver.py` runs the same tasks with the
Claude Code CLI (`claude -p`) as the agent. Built-in tools are disabled, only the browser MCP server
under test is attached, and the system prompt is our own:

```bash
.venv/bin/python -m evals.claude_driver --quick      # 6 tasks: Playwright MCP vs lean
.venv/bin/python -m evals.claude_driver --runs 3     # all 18 tasks x 2 modes x 3 runs
```

**With an API key** (in your environment, or in the gitignored, `chmod 600` file `.env`):

```bash
export ANTHROPIC_API_KEY=...
.venv/bin/leanb-eval --estimate          # cost before anything runs
.venv/bin/leanb-eval --quick             # 6 tasks, Playwright MCP vs lean, 1 run (~$1)
.venv/bin/leanb-eval -y                  # 18 tasks × 6 modes × 3 runs
.venv/bin/leanb-eval --schema-tokens     # exact tool-definition tokens per mode
```

- Tasks run against a local fixture site (`evals/fixtures/`), and **success is checked by the server**,
  not by what the agent says.
- There are six modes: screenshot, full HTML, aria snapshot, Playwright MCP, lean, and lean with
  automatic escalation.
- The report is written to `evals/report.md`.

## Development

```bash
.venv/bin/python -m pytest -q        # ~135 tests; uses the local fixture site, both engines
.venv/bin/python scripts/snap.py login.html,orders.html obscura    # look at snapshots
```

Layout:
- `lean_browser/`: engine.py (Obscura + Chromium, routing, sandbox), snapshot.js and snapshot.py,
  settle.py, diff.py, session.py, extract.js, tools.py, mcp_server.py, cli.py
- `evals/`: fixtures/, tasks.py, oracle.py, modes.py, runner.py, report.py
- `spike/`: the original Obscura vs Chromium investigation
