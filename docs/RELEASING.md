# Releasing

How a version goes from `main` to users. Nothing reaches PyPI without a maintainer publishing a GitHub Release.

## Automated (every push)

`.github/workflows/ci.yml` on macOS 15 (Apple Silicon), Ubuntu 24.04 x86_64 and Ubuntu 24.04 arm64:
- `./install.sh` from a fresh checkout, then the full test suite (both engines, the 100-task oracles, onboarding
  and Claude Code registration against a fake `claude` CLI),
- `scripts/smoke_clean_install.sh`: builds the wheel, checks its contents, installs it into a fresh venv whose
  path has a space, runs `leanb --version`, `leanb setup --yes --client none`, `leanb doctor`,
  `leanb doctor --json`, an MCP round trip (7 tools, open, dry run, verified click), and the same wheel
  through pipx.

## Release workflow

`.github/workflows/release.yml` runs when a GitHub Release is published:
1. builds the sdist and wheel once and fails if the tag isn't `v` + `lean_browser.__version__`,
2. runs the clean-install smoke test on that exact wheel on all three platforms,
3. attaches the files and `SHA256SUMS` to the GitHub Release,
4. publishes to PyPI with trusted publishing (OIDC, no stored token).

Run it by hand (Actions → Release → Run workflow → `testpypi`) to publish to TestPyPI first.

One-time setup, done by the maintainer on pypi.org and test.pypi.org: add a trusted publisher for
`Sanchit-hub/lean-agent-browser`, workflow `release.yml`, environments `pypi` and `testpypi`. Create those two
environments in the repository settings (requiring a reviewer on `pypi` is a good idea).

## Checklist for a release

1. `lean_browser/__version__` and `CHANGELOG.md` updated; CI green on `main`.
2. The [Claude Code acceptance test](#claude-code-acceptance-test) below, on a clean machine or user account,
   with the result recorded in the release notes.
3. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.
4. TestPyPI run of the release workflow; then `pipx install --index-url https://test.pypi.org/simple/
   --pip-args="--extra-index-url https://pypi.org/simple/" lean-agent-browser` on a clean machine and `leanb setup`.
5. Publish the GitHub Release for the tag; the workflow publishes to PyPI.
6. After PyPI: change the README install command to `pipx install lean-agent-browser`.

## Claude Code acceptance test

Automated in `tests/test_onboarding.py` (fake CLI everywhere; the real `claude` CLI under a throwaway HOME
when it's installed): registration is created with an absolute path, unrelated servers are preserved, a
second run doesn't duplicate, a changed path updates the entry, a path with spaces works, removal removes only
`lean-browser`, and a stale entry is reported as FAIL by doctor.

By hand, once per release candidate (needs a Claude Code login):

| # | Step | Expected |
|---|---|---|
| 1 | `pipx install "git+https://github.com/Sanchit-hub/lean-agent-browser@vX.Y.Z"` | installs; `leanb --version` prints X.Y.Z |
| 2 | `leanb setup` | asks before downloading and before changing Claude Code; doctor all PASS; Claude Code reports `✔ Connected` |
| 3 | `leanb setup` again | engines skipped, config kept, "Nothing to change" |
| 4 | `claude mcp list` | `lean-browser` plus every server that was there before |
| 5 | New Claude Code session, `/mcp` | `lean-browser` connected, 7 tools |
| 6 | The two [First task](../README.md#first-task) prompts | Claude calls `open` / `snapshot`; answers match the live pages |
| 7 | Ask Claude to call `act` with id 99999 | a useful `Error:` about the id, no crash |
| 8 | `/mcp` → reconnect `lean-browser`, then a new `open` | works; no stale session |
| 9 | `leanb uninstall` | removes engines and only the `lean-browser` entry; `claude mcp list` shows the rest |

## First-time user test

Before recommending a release widely, three people who have never worked on Lean get only the GitHub link and a
supported computer with Claude Code. Don't help them. Record time to the first successful task, the commands
they copied, every error and point of confusion, whether they recovered alone, and whether they understood
the outcome statuses. Fix repeated friction before widening the audience. Any critical failure blocks the
release.
