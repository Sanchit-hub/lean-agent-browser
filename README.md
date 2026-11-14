# Lean Agent Browser

A browser for AI agents that spends far fewer tokens than screenshot, HTML or accessibility-tree
browsing. Pages come back as compact text with numeric element ids, and actions return only what
changed. It runs on [Obscura](https://github.com/h4ckf0r0day/obscura), a small Rust headless browser,
and falls back to Chromium for anything Obscura can't handle.

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

```
> act fill 10 asha@example.com
~10: textbox "Email"* type=email = "asha@example.com"   (error cleared)
```

**Measured so far** (default snapshot vs Playwright's aria snapshot, tiktoken proxy): GitHub repo
page 949 vs 19,298 tokens, Wikipedia 954 vs 19,338, Hacker News 959 vs 10,263. Obscura also uses
about 3× less memory than Chromium on real pages. Whole-task numbers come from the eval harness
(`evals/`), which needs an Anthropic API key. See `SPEC.md` and `spike/FINDINGS.md` for the details.

## Install (macOS, Apple Silicon)

```bash
./install.sh
```

The installer:
- creates `.venv/` with pinned Python dependencies
- downloads **Obscura 0.2.6** and checks its SHA256 against a pinned value
- installs the Obscura binaries to `~/.lean-browser/bin/` and re-checks their hashes
- installs Playwright's Chromium to `~/.lean-browser/pw-browsers/`
- runs `leanb doctor` to check everything works

To also install the Playwright MCP baseline used by the evals (needs Node.js 20 or later), run
`./install.sh --with-eval`.

## Use it from Claude Code (MCP)

```bash
claude mcp add lean-browser -- ~/Desktop/lean/.venv/bin/leanb mcp
```

There are six tools. Their definitions add up to about 515 tokens, and they are sent with every request:

| Tool | What it does |
|---|---|
| `open(url, mode?, block?)` | Navigate, then return a snapshot. `mode` is `actions` (default), `read` (markdown) or `full`. |
| `snapshot(mode?, budget?, expand?, more?, find?)` | Current page. `expand:h1` opens a collapsed group, `more:k1` continues cut-off output, and `find` searches everything, including collapsed rows. |
| `act(action, id?, value?)` | Actions: `click`, `fill`, `select` (an option label, also works on custom dropdowns), `check`, `uncheck`, `clear`, `press`, `hover`, `focus`, `upload`, `scroll`, `back`, `forward`, `reload`, `wait_for`, `tab` (`list` / `new:URL` / `switch:N` / `close:N`), `dialog` (`accept` / `dismiss` the next native dialog). Returns a diff. |
| `fill_form(fields, submit?)` | `{id: value}` for a whole form in one call. `submit=true` clicks the form's submit button. |
| `extract(kind?, within?)` | Deterministic JSON for a `table`, `list` or `form` (no LLM involved). |
| `screenshot(id?)` | Viewport or element PNG. Only for captchas, charts or layout. |

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
snapshot_timeout_s = 2.0            # slower snapshots move the page to Chromium
```

## Security model

- **Obscura is pinned and verified.** Obscura 0.2.6 is pinned, and the SHA256 of both binaries is
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
