# Baseline (verified 2026-11-18)

What exists today, checked against the code, the test suite and CI rather than older notes. Update it
at the end of each milestone. Facts here come from the commands named next to them.

## Release state

| Item | Value | Source |
|---|---|---|
| Version | 0.5.0 (`lean_browser.__version__`, the only version source; `pyproject.toml` reads it) | `leanb --version` |
| Before this baseline | `main` at `575c6bf` (v0.4.0); no git tags and no GitHub Releases existed | `git tag`, `gh api .../releases` |
| Repository | public, Apache-2.0 | `gh repo view` |
| PyPI | not published | |
| Python | 3.12+ (`requires-python`); CI uses 3.12, also run locally on 3.14 | `pyproject.toml`, CI |

## Interfaces

**MCP tools (7):** `open`, `snapshot`, `act`, `fill_form`, `extract`, `screenshot`, `memory`. Counted from
`TOOLS` in `lean_browser/tools.py`, and checked over a real MCP connection by `leanb doctor` and
`scripts/smoke_clean_install.sh`.

**CLI (`leanb`):** `setup`, `doctor [--json]`, `install`, `uninstall`, `mcp`, `open`, `shell`, `trace`, `bench`
(source checkout only), `--version`. `setup`, `uninstall`, `--version` and the new doctor are new in 0.5.0.

**Python API:** `from lean_browser import LeanBrowser, LeanBrowserError, Config`.

## Platforms and engines

| Platform | Evidence | Status |
|---|---|---|
| macOS 15 on Apple Silicon | CI `test` job (`macos-15`): `install.sh`, full suite, clean-install test | supported |
| Ubuntu 24.04 x86_64 | CI `linux` job (`ubuntu-24.04`), with bubblewrap | supported |
| Ubuntu 24.04 arm64 | CI `linux` job (`ubuntu-24.04-arm`), with bubblewrap | supported |
| Intel Mac, other Linux, Windows | none | not supported; doctor reports NOT SUPPORTED |

- **Obscura 0.2.7** (Apache-2.0, `github.com/h4ckf0r0day/obscura`). The release archive's SHA256 and both
  binaries' SHA256 are pinned per platform in `lean_browser/engine.py`. The binaries are re-checked on
  every launch, and Obscura runs only sandboxed (`sandbox-exec` on macOS, bubblewrap on Linux).
  0.2.6 is kept for rollback on macOS only.
- **Chromium**: Playwright 1.64.1's bundled build, installed into `~/.lean-browser/pw-browsers`, with a
  throwaway profile. Playwright starts it with Chromium's own sandbox off. Without Obscura (no bubblewrap,
  or an unsupported platform) Chromium serves every page.
- Disk use after setup: about 135 MB for Obscura and 570 MB for Chromium (measured on macOS).

## Tests

| Run | Result |
|---|---|
| Full suite, macOS arm64 (local), 2026-11-18 | 396 passed, 3 skipped (395 + 1 that failed only because the version was bumped mid-run; it passes on rerun), 5 min 52 s |
| Clean-install test, macOS arm64 (local) | passed: wheel contents, venv path with a space, `setup --yes`, doctor 9/9 PASS, `doctor --json`, MCP round trip |
| pipx install of the checkout (local, PIPX_HOME with a space) | `leanb --version` 0.5.0, doctor all PASS, install kind `pipx` |
| Real Claude Code CLI 2.1.322, throwaway HOME | register, no duplicate, update a stale entry, unrelated server kept, uninstall removes only `lean-browser` |
| CI (3 platforms), commit `dfc8805` | green: macOS 15, Ubuntu 24.04 x86_64 and arm64, each with the clean-install test including pipx |
| README route from GitHub, tag `v0.5.0`, throwaway HOME | `pipx install "git+...@v0.5.0"`, `leanb setup --yes`: doctor 9/9 PASS, Claude Code entry added and reported `✔ Connected` |
| README first-task prompt through `claude -p` with Lean attached | Claude called `open` then `snapshot` and described example.com correctly |

Skipped tests are listed by `pytest -rs`. They are conditional: the real-Claude-CLI test is skipped where
`claude` isn't installed (CI), and platform-specific tests are skipped on the other platform.

## Benchmark evidence

100 fixture tasks × 3 runs: Lean 300/300 (median 13,181 tokens), Playwright MCP 300/300 after one fixture
correction (46,946). Raw files are in `evals/results/20261116-014739-claude-cli/` and
`evals/results/20261116-021951-claude-cli/`; method and caveats are in `docs/benchmark.md`. agent-browser has
only the older 18-task, 1-run result. Every task was written by the project author.

## Discrepancies found and fixed in this pass

| Found | Fix |
|---|---|
| README said the repository is private (it is public) | removed; README restructured around installing for Claude Code |
| README tool table listed 6 tools under "There are seven tools" (`memory` missing) | `memory` row added |
| MCP server docstring said 6 tools; server reported version 0.1.0 | 7 tools; reports the package version |
| Version written in two places (`pyproject.toml`, `__init__.py`) | single source |
| The wheel shipped a top-level `evals` package (would clash with other packages named `evals`) | wheel ships only `lean_browser`; `python -m evals.runner` replaces `leanb-eval` |
| Opening localhost returned `net::ERR_BLOCKED_BY_CLIENT` with no explanation | explains the private-network block and how to allow it |
| Docs implied Chromium was isolated like Obscura | README and SECURITY.md say Chromium's sandbox is off |
| Doctor printed free text; "Obscura not installed" still ended in "all good" | per-check PASS/WARN/FAIL/NOT SUPPORTED, warnings counted in the summary |

## Known gaps (not done)

- Not on PyPI. The release workflow is ready; trusted publishing has to be set up by the maintainer.
- No first-time user test by people outside the project yet (protocol in `docs/RELEASING.md`).
- One MCP client documented and tested: Claude Code.
- GitHub private vulnerability reporting is disabled on the repository, so the reporting link in
  `SECURITY.md` doesn't work until the maintainer enables it.
- Network containment: tested for localhost, RFC1918, link-local and metadata addresses on both engines,
  plus IPv4-mapped and unique-local IPv6 addresses (`test_is_private_host`). DNS rebinding, WebSockets and alternative IP encodings are not
  covered by dedicated tests.
- Chromium runs without its OS sandbox.
- No upgrade test from a previous release yet: 0.5.0 is the first tagged version.
