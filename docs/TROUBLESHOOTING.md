# Troubleshooting

Start with:

```bash
leanb doctor
```

Each line is `PASS`, `WARN` (works, with something missing or reduced), `FAIL` (broken) or
`NOT SUPPORTED`, and anything that isn't `PASS` comes with a `fix:` line. If the fix doesn't help, open an
issue with the output of `leanb doctor --json`. It shortens your home folder to `~` and contains no page
content, cookies or keys.

## Installing

**`pipx: command not found`**
Install pipx: `brew install pipx` (macOS) or `sudo apt install pipx` (Ubuntu), then `pipx ensurepath`
and open a new terminal.

**`requires a different Python` / `Python 3.12+ required`**
pipx used an older Python (macOS's built-in `python3` is 3.9). Point it at a newer one:
`pipx install --python python3.12 "git+https://github.com/Sanchit-hub/lean-agent-browser@v0.7.0"`
(`brew install python@3.12` or `sudo apt install python3.12` first if you don't have it).

**`leanb: command not found` after installing**
pipx's bin folder isn't on your PATH. Run `pipx ensurepath`, then open a new terminal.

**`git: command not found` while installing**
Installing from GitHub needs git: `xcode-select --install` (macOS) or `sudo apt install git`.

**`Obscura checksum mismatch`**
The download didn't match the pinned SHA256, so nothing was installed. This is usually a broken
download or a proxy rewriting it. Run `leanb install` again. If it keeps failing, don't work around it:
open an issue. Chromium keeps working in the meantime.

**Downloads fail behind a proxy**
`leanb install` uses Python's standard `HTTPS_PROXY` / `HTTP_PROXY` variables. Playwright's Chromium download
honours them too.

## doctor results

**`WARN obscura: Obscura ... is not installed`**
Run `leanb install` (or `leanb setup`). Until then Chromium serves every page, which works but uses about
3× more memory.

**`WARN sandbox: bubblewrap not found` (Linux)**
`sudo apt install bubblewrap`. Obscura only ever runs inside a sandbox, so without bubblewrap it stays off and
Chromium serves every page. Chromium does not get the same isolation (see the README's Security model).

**`WARN os sandbox: Chromium runs without its OS sandbox`**
Chromium works, but without its own sandbox around page renderers, so a browser exploit would get further.
On Linux the sandbox needs unprivileged user namespaces: Ubuntu 24.04 restricts them (same fix as the
bubblewrap entry below), and most containers don't allow them. The reason after the colon says what failed.
If it says `LEANB_CHROMIUM_SANDBOX=0`, unset that variable.

**`FAIL obscura: ... bwrap: setting up uid map: Permission denied` (Ubuntu 24.04)**
Ubuntu 24.04 restricts unprivileged user namespaces, which bubblewrap needs. Either allow them
(`sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`, and add it to `/etc/sysctl.d/` to keep it)
or leave Obscura off and use Chromium only (`prefer = "chromium"` in `~/.lean-browser/config.toml`).

**`FAIL chromium page: ... error while loading shared libraries` (Linux)**
Chromium's system libraries are missing. Run the `sudo ... playwright install-deps chromium` command that
doctor prints (it uses the Python inside your Lean install).

**`FAIL chromium page: Executable doesn't exist`**
Chromium isn't downloaded yet: `leanb install`.

**`FAIL config: ... is not valid TOML`** or **`WARN config: unknown keys ignored`**
Fix the line it names in `~/.lean-browser/config.toml`, or delete the file to go back to the defaults.

**`FAIL mcp: the MCP server did not start or answer`**
Run the command it prints (`/path/to/leanb mcp`) by hand: the error appears on the terminal. Press Ctrl-C to stop it.

**`NOT SUPPORTED platform`**
Your OS or CPU isn't in the tested set (macOS on Apple Silicon, Ubuntu 24.04 on x86_64 and arm64).
Chromium alone may still work, but nothing is promised.

## Claude Code

**`WARN claude code: Claude Code CLI not found`**
Install Claude Code, open a new terminal, then `leanb setup --client claude`.

**`WARN claude code: no 'lean-browser' MCP server registered here`**
`leanb setup --client claude`. If you registered it with `local` scope in a project folder, doctor (which
looks from your home folder) won't see it; `--scope user` makes it available everywhere.

**`FAIL claude code: 'lean-browser' points to ..., which does not exist`**
The entry points to an old install (for example a deleted checkout or a reinstalled pipx venv).
`leanb setup --client claude` replaces it.

**Claude doesn't use the browser, or `/mcp` doesn't list `lean-browser`**
- Start a new Claude Code session after registering: running sessions don't pick up new servers.
- Run `claude mcp get lean-browser`. It should say `✔ Connected`. If it says failed, run `leanb doctor`.
- Ask explicitly: "Use Lean Agent Browser to open ...".

**A tool call fails with `blocked: private network`**
localhost, LAN and cloud-metadata addresses are blocked by default. To test a local app, set
`allow_private_network = true` in `~/.lean-browser/config.toml` (doctor will warn while it's on), or register
a second server with `leanb --allow-private-network mcp` for local work only.

## Pages

**`status: unverified`**
The action ran, but nothing on the page proves it worked. Look at the page (`snapshot`) before doing it
again. Pass `expect=` (text, `url:/path` or `gone:<id>`) when you know what success looks like.

**`status: ambiguous`**
It may or may not have been sent. Don't retry a payment, order or send: check the page or the account first.

**`status: blocked`**
The page rejected it (field errors, HTTP errors) or Lean refused it (confirmation needed, duplicate). The
reason is on the status line.

**Timeouts on slow sites**
`nav_timeout_ms` (default 20000) in the config raises the navigation limit. A page whose snapshot takes
over `snapshot_timeout_s` moves to Chromium automatically.

**Bot checks and logins**
Lean doesn't solve captchas or bypass bot detection. Pages behind a login need you to sign in within the
session first; Lean never uses your own browser profile.

## Reporting a bug

Open an issue with:
- `leanb doctor --json` output,
- the command or prompt you ran, and what you expected,
- the error text.

Don't attach traces from real accounts: they can contain page text. Remove anything private first.
Security problems go to the private channel in [`SECURITY.md`](../SECURITY.md), not a public issue.
