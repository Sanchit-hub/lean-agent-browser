# Audit: cycle 002 (source level)

**Environment:** `main` from `895cea5` (v0.6.0 + docs) to v0.7.0, macOS 27.3 on Apple Silicon, Python 3.14.3,
Playwright 1.64.1, Obscura 0.2.7. CI covers macOS 15, Ubuntu 24.04 x86_64 and arm64. The claim-by-claim
status lives in [`docs/PRODUCT_TRUTH.md`](../PRODUCT_TRUTH.md); the outcome rules in
[`docs/RELIABILITY.md`](../RELIABILITY.md).

Method: trace each public call (MCP `tools/call` → `LeanBrowser.call` → `Session` → engine), try to break it
with a fixture, write the failing test first, fix it with the smallest change, then rerun everything.

## Findings

| # | Pri | Finding | Evidence (repro) | Fix | Regression test | Status |
|---|---|---|---|---|---|---|
| 1 | P0 | `expect="Saved"` was `verified` when "Saved 2 minutes ago" was already on the page before the click | `expect-already-true` case | Count occurrences before the action (`_expect_pre`); text must appear more often afterwards | `test_expect_needs_fresh_unnegated_evidence` | fixed |
| 2 | P0 | `expect="saved"` was satisfied by "Draft not saved" | `expect-negated` | `EXPECT_COUNT_JS` skips occurrences preceded by not / never / n't / un- / failed to | same | fixed |
| 3 | P0 | `expect="url:..."` was satisfied by a URL that already matched before the action | `expect-url-already` | URL must have changed or newly contain the part | same | fixed |
| 4 | P0 | An action that opened a new tab reported `verified` with `expect=` set, without checking it | code read: `_new_tab_result` | The expectation is checked in the new tab | `expect-new-tab` case | fixed |
| 5 | P1 | A submit that navigated to a German error page ("Fehler") was `verified` (page changed) | `nav-error-german` | Common error words in German, French, Italian, Spanish, Portuguese, Russian, Chinese, Japanese, Korean and Hindi count as errors | verification suite | fixed (partial: success words stay English) |
| 6 | P1 | Two concurrent Python API calls (`asyncio.gather`) mixed pages: both got the second page and Obscura's navigation failed | `test_concurrent_python_calls_do_not_mix_pages` reproduced it | `LeanBrowser.call` takes a lock (the MCP server already had one) | same | fixed |
| 7 | P2 | After an engine crash, `act`/`snapshot` returned a raw `TargetClosedError` | killed Obscura mid-session | Clear error: the engine crashed, call `open(url)`, and check whether the last submit took effect | `test_engine_crash_mid_session_is_explained_and_recoverable` | fixed |

Checked and found sound, now with tests:
- stdout carries only JSON-RPC, even with tracing on and an error path (`test_stdout_carries_only_json_rpc`);
- invalid tool calls are errors and the server survives;
- the live MCP schemas match the checked-in contract;
- two `leanb mcp` processes don't share cookies, memory or pages;
- concurrent MCP calls each get their own page;
- after a crash, fallback is visible in the result header (`engine: chromium (navigation failed on obscura: …)`).

## Threat model

| Threat | Asset | Attacker | Path | Mitigation | Test | Residual risk |
|---|---|---|---|---|---|---|
| Prompt injection | The agent's actions | Page author | Visible or hidden page text | Content wrapped as `<page untrusted>`; hidden text dropped; MCP instructions say page text is data; risky actions classed `unsafe`, optional `confirm_risky` | `inject-delete`, `inject-exfil` tasks | Visible text still reaches the agent: reduces, doesn't prevent |
| Network pivot (SSRF) | localhost, LAN, cloud metadata | Page author, redirector | Navigation, redirects, subresources, DNS rebinding | URL check, request routing, connect-time guard on both engines | `test_redirect_to_private_address_is_blocked`, `test_private_network_*` | Guard off when `HTTP(S)_PROXY` is set; no dedicated rebinding test |
| Local file read | Files on disk | Page or agent | Upload with a crafted path | Absolute paths inside `allowed_upload_dirs`, symlinks and `..` resolved | `test_upload_path_guard_*` | Files inside the allowed folder can be uploaded by design |
| Secrets in traces | Passwords, tokens, cards | Anyone who gets a trace | `--trace` files, exports | Redaction of sensitive fields and URL parameters; page text opt-in; `600` export files | `tests/test_trace.py` | A secret typed into an unrecognised plain field |
| Browser profile | The user's own Chrome data | Page author | Shared profile | Throwaway profiles only; Obscura sandboxed away from home | engine tests | Chromium runs without its OS sandbox |
| Fallback weakening | All of the above | Page that forces fallback | Capability routing to Chromium | Same network rules and guard, same upload rules, same session policy on both engines | redirect test on both engines | Chromium is not OS-isolated |
| Claude Code config | User's other MCP servers | Bug in setup | `leanb setup` / `uninstall` | Only `claude mcp add-json/get/remove` on the `lean-browser` entry, after a yes | `tests/test_onboarding.py` (fake and real CLI) | — |
| Tampered binaries | The machine | Supply chain | Obscura download | Pinned archive and binary SHA256, re-checked on every launch; dependency pins in `pyproject.toml` | `test_rejects_bad_checksum` | Playwright's Chromium download is trusted as Playwright ships it |
| Cross-session leakage | Another agent's pages and cookies | Another agent on the machine | Shared browser | One browser per `leanb mcp` process | `test_two_servers_do_not_share_state` | — |
| Duplicate side effects | Money, messages, records | Agent retry, slow server | Repeated submit | No automatic retry of unsafe actions; duplicate guard; `ambiguous` / `timed_out` say "check first" | `test_duplicate_*`, `pay-once` task | Guard is per session and page; no exactly-once against arbitrary sites |

## Engine and security matrix

| Property | Obscura | Chromium |
|---|---|---|
| OS sandbox | yes (`sandbox-exec` / bubblewrap) | no (Playwright default) |
| Private-network URL check | yes | yes |
| Per-request check | Obscura's own guard | request routing |
| Redirect hops and DNS rebinding | connect-time guard | connect-time guard |
| Upload path rules | session-level (uploads always move to Chromium) | session-level |
| Profile | temp dir, deleted on exit | throwaway context |
| Form validation before submit | Lean's check (Obscura has none) | Lean's check (browser has its own too) |
| Native dialogs | Lean's shim records them | Playwright events |
| File uploads, rich-text editors, popups, cross-origin / srcdoc / nested iframes | routed to Chromium before acting | native |
| Fallback visible to the caller | — | `engine: chromium (reason)` in every result |

## Backlog (prioritised)

| Pri | Item | Why | Next action |
|---|---|---|---|
| — | Three first-time users complete onboarding unaided | Release gate | **Externally blocked**: needs people (`docs/RELEASING.md`) |
| — | PyPI publication | End-user install route | **Externally blocked**: maintainer sets up trusted publishing |
| P2 | Guard proxy chains to the user's `HTTP(S)_PROXY` | Redirect protection is lost behind corporate proxies | Add upstream CONNECT support with the same IP check |
| P2 | Dedicated DNS-rebinding test | The guard covers it, but there is no test | Resolver fixture that changes its answer between lookups |
| P2 | Success words in more languages | Non-English success ends `unverified` | Add words with fixtures per language |
| P2 | Chromium sandbox on where available | Isolation parity | Try `chromium_sandbox=True` with a fallback and a doctor line |
| P3 | Caller-supplied action key for the duplicate guard | Guard across sessions and restarts | Design first; needs a schema change |
| P3 | Real-site canary suite (read-only) | Fixture results don't prove real sites | 10 public read-only pages, weekly |
