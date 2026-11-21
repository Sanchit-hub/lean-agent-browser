# Product truth (verified 2026-11-22)

What exists today, checked against the code, the tests and CI rather than older notes or the README. Each
public claim maps to where it is implemented and what proves it. Update this at the end of every cycle.
Status is one of: **verified** (a test or recorded run proves it), **partial** (true with stated limits),
**unverified** (no evidence yet), **not supported**.

## Truth ledger

| Claim | Implementation | Evidence | Status | Risk |
|---|---|---|---|---|
| Compact snapshots with stable ids, collapsed groups, find/expand | `snapshot.js`, `snapshot.py` | `tests/test_snapshot.py` (both engines) | verified | low |
| `verified` means the page shows evidence the outcome happened | `session.py` `_signals`, `_status`, `_after` | `tests/test_verification.py`; `scripts/verification_matrix.py` 1,400 runs on `b539371`: 0 false verified, 0 false unverified | verified on the suite (incl. 24 red-team cases); success/error words in English plus ten common languages | medium |
| `expect=` postconditions need new, non-negated evidence | `session.py` `_expect_pre`, `_check_expect`, `EXPECT_COUNT_JS` | `test_expect_needs_fresh_unnegated_evidence` (5 cases × 2 engines) | verified | low |
| Form validation is checked before a submit (Obscura doesn't validate) | `session.py` `FORM_INVALID_JS`, `_form_invalid` | `html5-required` case | verified | low |
| Submits, payments and deletes are never retried automatically | `session.py` `_perform_guarded`, `retry_safety` | `test_slow_submit_times_out_honestly_and_is_not_repeated`, `test_retry_safety_classes` | verified | low |
| Repeating an unsafe action is blocked unless `value="repeat"` | `session.py` `act` (`_unsafe_log`), `fill_form` | `test_duplicate_*` | partial: without `key=`, per session and page (with `key=`: next row) | medium |
| With `key=`, the duplicate guard holds across pages, sessions and restarts (24 h, this machine) | `action_keys.py`, `session.py` `act`, `fill_form` | `test_action_key_*`, `test_one_key_across_two_servers_sends_once` (claimed atomically before dispatch) | verified; only for calls that pass the same key | medium |
| Re-rendered targets are re-found only on an unambiguous, non-contradicting match | `session.py` `_resolve_or_recover` | `test_conditional_action_retried_once_after_rerender`, `test_reordered_list_keeps_ids_with_their_rows`, `rerender` task | verified | low |
| `dry_run` dispatches nothing | `session.py` `act`, `fill_form` | `test_dry_run_*`, clean-install MCP round trip | verified | low |
| Private network blocked on both engines, including redirect hops | `tools.py` `_check_domain`, `engine.py` `_route`, `netguard.py` | `test_redirect_to_private_address_is_blocked[both]`, `test_private_network_*`, `test_netguard_refuses_private_targets` `tests/test_netguard.py` (DNS rebinding, behind the user's proxy) | verified (socks proxies turn the guard off) | high |
| Obscura is hash-pinned and always sandboxed | `engine.py` `verify_obscura`, `ObscuraProcess`, `sandbox_profile`, `bwrap_args` | `tests/test_engine.py` sandbox tests (macOS and Linux CI) | verified | low |
| Engine fallback is visible, including after an engine crash | `engine.py` (`engine: chromium (reason)` in every header) | fallback tests; `test_engine_crash_mid_session_is_explained_and_recoverable` | verified | low |
| Uploads only from allowed folders (symlinks and `..` resolved) | `session.py` `_check_upload` | `test_upload_on_chromium_and_guard`, `test_upload_path_guard_resolves_symlinks_and_dotdot` | verified | low |
| Passwords never shown; traces redact secrets and keep page text only on opt-in | `snapshot.js`, `trace.py` | `tests/test_trace.py` | verified | low |
| Page content is marked untrusted; hidden text dropped | `snapshot.py` `wrap_untrusted`, `snapshot.js` | `inject-delete`, `inject-exfil` benchmark tasks; snapshot tests | partial: reduces prompt injection, does not prevent it | medium |
| MCP: 7 tools with a stable contract; invalid calls are errors, not crashes; stdout is pure JSON-RPC | `mcp_server.py`, `tools.py` | `tests/test_contract.py` | verified | low |
| Separate agents don't share state; concurrent calls don't mix pages | one browser per `leanb mcp` process; locks in `mcp_server.py` and `LeanBrowser.call` | `test_two_servers_do_not_share_state`, `test_concurrent_*` | verified | low |
| Install, setup, doctor, Claude Code registration, upgrade, uninstall | `onboarding.py`, `doctor.py`, `claude_code.py`, `installer.py` | `tests/test_onboarding.py`, `scripts/smoke_clean_install.sh` in CI on 3 platforms | verified by us; **unverified by outside users** | medium |
| Supported platforms: macOS arm64, Ubuntu 24.04 x86_64 and arm64 | CI matrix | `ci.yml` runs | verified | low |
| Fewer tokens than Playwright MCP | `evals/` | 100 fixture tasks × 3 runs (`docs/benchmark.md`) | partial: our own fixture tasks only, not real sites | medium |
| Chromium runs inside its own OS sandbox where the host allows it | `engine.py` `_chromium_context` (sandboxed launch, fallback with a note), `doctor.py` `check_chromium_sandbox` | `test_chromium_tries_its_os_sandbox_and_reports_it`, `test_chromium_falls_back_without_os_sandbox` | verified on macOS; partial on Linux: off where user namespaces are restricted (doctor WARN) | medium |
| Pages in other languages | `ERROR_RE` has common error words in several languages | `nav-error-german`, `success-*`, `negated-*` cases | partial: success and error words in ten common languages (German, French, Italian, Spanish, Portuguese, Russian, Chinese, Japanese, Korean, Hindi); others end `unverified`; `expect=` negation covers the same languages | medium |
| Exactly-once execution on arbitrary websites | — | — | not supported, not claimed | — |

## Release state

| Item | Value | Source |
|---|---|---|
| Version | 0.8.0 (`lean_browser.__version__`, the only version source; `pyproject.toml` reads it) | `leanb --version` |
| Tags | `v0.5.0`, `v0.6.0`, `v0.7.0`, `v0.8.0` (`v0.8.0` on `6cd2f0d`; `pip install` from it gives `leanb 0.8.0`) | `git tag` |
| GitHub Releases | none (held until the first-time user test) | `gh api .../releases` |
| `main` after the tag | ahead of `v0.8.0` with the real-site hardening (`ef616ee`, `6f60a47`, docs), listed under Unreleased in `CHANGELOG.md`; not tagged | `git log v0.8.0..main` |
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
  throwaway profile. Lean starts it with Chromium's own OS sandbox where the host allows it (macOS: on;
  Linux: needs unprivileged user namespaces, otherwise off with a doctor WARN). Without Obscura (no bubblewrap,
  or an unsupported platform) Chromium serves every page.
- Disk use after setup: about 135 MB for Obscura and 570 MB for Chromium (measured on macOS).

## Tests

| Run | Result |
|---|---|
| CI (3 platforms), commit `6f60a47` (CI #61, last code change of the hardening) | green: macOS 15, Ubuntu 24.04 x86_64 and arm64 |
| CI (3 platforms), commit `ef616ee` (CI #60, hardening round 1) | green |
| Full suite, macOS arm64 (local), `6f60a47` | 675 passed, 5 skipped, 1 xfailed, 11 min 42 s |
| Verification suite, 70 cases × 2 engines × 10 runs, `6f60a47` | 380 true verified, 1,020 correctly unverified: **0 false verified, 0 false unverified**; p50 1.11 s, p95 4.15 s |
| Real-site canary, 10 pages × 2 engines (local, during the hardening) | 20/20 pass |
| README route from GitHub, tag `v0.8.0`, throwaway HOME (2026-11-21) | `pipx install "git+...@v0.8.0"` in 1 min 16 s, `leanb setup --yes --client none` in 5 min 42 s (engine downloads), doctor 10/10 PASS. pipx itself was not installed on this Mac; the README links it. Claude Code registration was not repeated (it needs a signed-in CLI in that HOME) |
| README second task (Hacker News titles + links) through `claude -p` | v0.8.0: correct but 25 turns, because snapshots carry no link addresses and the agent clicked every story; one domain wrong. After the `extract` url fix: 4 turns, all five URLs right |
| Full suite, macOS arm64 (local), 2026-11-18 | 396 passed, 3 skipped (395 + 1 that failed only because the version was bumped mid-run; it passes on rerun), 5 min 52 s |
| Clean-install test, macOS arm64 (local) | passed: wheel contents, venv path with a space, `setup --yes`, doctor 9/9 PASS, `doctor --json`, MCP round trip |
| pipx install of the checkout (local, PIPX_HOME with a space) | `leanb --version` 0.5.0, doctor all PASS, install kind `pipx` |
| Real Claude Code CLI 2.1.322, throwaway HOME | register, no duplicate, update a stale entry, unrelated server kept, uninstall removes only `lean-browser` |
| CI (3 platforms), commit `3bfe8d0` (CI #58, latest `main` at this audit) | green: macOS 15, Ubuntu 24.04 x86_64 and arm64 |
| CI (3 platforms), commit `6cd2f0d` (CI #56, tag `v0.8.0`) | green |
| Full suite, macOS arm64 (local), `2593515` (v0.8.0 code) | 663 passed, 5 skipped, 1 xfailed (Obscura WebSocket stub), 11 min 12 s |
| Verification suite, 70 cases × 2 engines × 10 runs, after the timing fix (`2593515`) | 380 true verified, 1,020 correctly unverified: 0 false verified, 0 false unverified; **p50 1.10 s, p95 4.15 s** |
| Verification suite, 70 cases (incl. 24 red-team) × 2 engines × 10 runs (`b539371`) | **380 true verified, 1,020 correctly unverified: 0 false verified, 0 false unverified, 0 setup errors, known-gap list empty**; p50 1.89 s (was 1.14 s: the new evidence checks), p95 6.16 s |
| Verification suite, 69 cases (incl. 23 red-team) × 2 engines × 10 runs (`ffa68a0`) | 360 true verified, 1,000 correctly unverified, 0 false unverified, 0 setup errors; 20 false verified, all from the one documented known gap `rt-fill-reverted-late`; p50 1.14 s, p95 6.18 s |
| Verification suite, 27 cases × 2 engines × 10 runs (v0.7.0) | 0 false verified, 0 false unverified in 540 runs |
| Full suite, macOS arm64 (local), v0.7.0 | 464 passed, 3 skipped |
| CI (3 platforms), commit `db68cb1` (v0.7.0) | green |
| Verification suite, 20 cases × 2 engines × 10 runs (v0.6.0) | 0 false verified, 0 false unverified in 400 runs (`scripts/verification_matrix.py`) |
| CI (3 platforms), commit `dfc8805` | green: macOS 15, Ubuntu 24.04 x86_64 and arm64, each with the clean-install test including pipx |
| README route from GitHub, tag `v0.5.0`, throwaway HOME | `pipx install "git+...@v0.5.0"`, `leanb setup --yes`: doctor 9/9 PASS, Claude Code entry added and reported `✔ Connected` |
| README first-task prompt through `claude -p` with Lean attached | Claude called `open` then `snapshot` and described example.com correctly |

Skipped tests are listed by `pytest -rs`. They are conditional: the real-Claude-CLI test is skipped where
`claude` isn't installed (CI), and platform-specific tests are skipped on the other platform.

## Benchmark evidence

- `main` after hardening (`6f60a47`), Lean and Playwright MCP × 3 on all 100 fixture tasks (2026-11-22): Lean
  300/300 (297/300 as run; three runs blocked by a duplicate key left by an earlier run, a harness fault, fixed
  and rerun 9/9), median 13,505 tokens (+2.5% vs v0.4.0, a small real increase); Playwright MCP 300/300, median
  46,997 (`evals/results/20261122-012443-claude-cli/`, `evals/results/20261122-015654-claude-cli/`).
- Live suite, 51 real-site tasks, 1 run, answer-checked: Lean 51/51 after the fixes, median 12,699 tokens
  (`evals/results/20261122-012035-claude-cli-live/`). The first runs (47/51) are what found the fixes.

- v0.8.0, Lean × 1 on all 100 fixture tasks (2026-11-20): 100/100, median 13,409 tokens, p95 30,202; action
  statuses unchanged from v0.6.0 (`evals/results/20261120-032626-claude-cli/`, `docs/benchmark.md`).

100 fixture tasks × 3 runs: Lean 300/300 (median 13,181 tokens), Playwright MCP 300/300 after one fixture
correction (46,946). Raw files are in `evals/results/20261116-014739-claude-cli/` and
`evals/results/20261116-021951-claude-cli/`; method and caveats are in `docs/benchmark.md`. agent-browser has
only the older 18-task, 1-run result. Every task was written by the project author.

## Discrepancies found and fixed (v0.5.0)

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
- Network containment: connect-time guard on both engines, with redirect and DNS-rebinding tests. Behind
  the user's `HTTP(S)_PROXY` it chains to that proxy (rebinding is then the proxy's own resolution); a
  `socks://` proxy turns it off. WebSockets are tested on Chromium: to 127.0.0.1, a privately resolving
  name and 169.254.169.254 they are refused, to the page's own public origin they work. Obscura's own
  `WebSocket` is a stub that fakes `open` and never connects; Lean replaces it there with an honest failure
  (error + close), moves pages that open one at load to Chromium, and after an action that opens one tells
  the caller and opens that host in Chromium from then on.
- Chromium runs without its OS sandbox on hosts that restrict unprivileged user namespaces (doctor WARN).
- Upgrade from v0.5.0 is tested in CI (pipx); older versions were never tagged.
