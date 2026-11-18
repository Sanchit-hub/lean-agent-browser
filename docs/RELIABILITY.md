# Reliability spec

What each action reports, what evidence it needs, and which tests hold it to that. The rule: an action
is `verified` only when the page shows evidence that the wanted outcome happened. When in doubt, say less.
A false `verified` (the outcome did not happen) is a release-blocking defect. An honest `unverified` on
an outcome that did happen is a smaller defect, tracked in the same suite.

## Statuses

| Status | Meaning | Retry? |
|---|---|---|
| `verified` | Evidence the outcome happened (below) | no need |
| `unverified` | It ran; nothing shows it worked | check the page first |
| `blocked` | Not done: the page rejected it, form validation stopped it, or Lean refused (confirmation, duplicate, private network) | fix the cause |
| `ambiguous` | May or may not have been sent (an error after dispatch) | never blindly |
| `timed_out` | The page was still busy when the wait ended | never blindly for submits |
| `done` | Hover, focus, scroll: nothing to verify | — |

## Evidence rules

**Field actions** (`fill`, `clear`, `select`, `check`, `uncheck`, `upload`, sliders): the field's state is read
back after the page settles. `verified` only if it holds the requested value. A field that strips or reverts
the input is `unverified`.

**Submit-like actions** (submit buttons, payment/delete/send-like names, Enter in a form field, `fill_form`
with `submit`): `verified` needs one of
- a navigation or SPA route change, unless the same form came back with the same headings and no success
  message (a silent rejection),
- a new success message (heading or live region) that isn't negated ("was not saved", "wasn't sent" and
  "unsuccessful" count as errors),
- the clicked control went away or the form was cleared, unless the page shows a new "Processing…"-style
  text,
- the caller's `expect=` postcondition, with fresh evidence only (for field actions, `expect=` is an extra
  condition that just has to hold afterwards):
  - text must appear more often than it did before the action, and not as "not <text>" / "un<text>",
  - `url:` must newly match,
  - `gone:` needs an element that existed before.
  After a new tab opens, the expectation is checked in that tab.

Otherwise:
- New error text, field errors or HTTP ≥ 400 make it `blocked`.
- While the page shows a new "Processing…" / "Please wait" / "Loading…", Lean waits up to 8 s for the real answer.
- A dialog that was answered with nothing changing afterwards, or a new tab opening, is not proof for a submit.
- Time-like texts that only tick ("Last updated 3s ago") are not new evidence.

**Before a submit is dispatched**, the form's own validation (required, email, minlength, pattern) is checked.
If it fails, the submit is not sent and the status is `blocked` with the fields and messages. Chromium would
silently refuse that submit; Obscura doesn't validate forms at all and would have sent it.

**Error words** are mostly English, plus common ones in German, French, Italian, Spanish, Portuguese,
Russian, Chinese, Japanese, Korean and Hindi. Success words are English only.

**Other clicks**: `verified` if the page changed. This is weaker evidence: a page that changes on its own can
make an unrelated click look verified. Pass `expect=` when it matters.

## Recovery and duplicates

- A re-rendered target is re-found once, by role and name plus a fingerprint that must not contradict the
  original (link target, test id, field name, form, row text, landmark). If the match is ambiguous or
  contradicted, nothing is dispatched.
- Field actions retry once after a re-render, and only after checking the field isn't already in the wanted
  state. Submit-like actions are never retried.
- Repeating a submit-like action on the same page after `verified`, `ambiguous` or `timed_out` is blocked
  unless `value="repeat"` (`submit="repeat"` for `fill_form`). The guard is per session and per page.
- An optional `key` on `act` and `fill_form` names the action (for example `order-123`). If a submit-like
  action with that key already ended `verified`, `ambiguous` or `timed_out`, the call is `blocked` with the
  earlier status, time and URL, unless `value="repeat"` / `submit="repeat"`. A `blocked` or `unverified`
  result doesn't block, and never replaces one that does. Keys live in `~/.lean-browser/action_keys.json`
  (or `$LEANB_STATE_DIR`), mode 600, for 24 hours, so the guard survives new pages, sessions and restarts.
  Writes are atomic (temp file + `os.replace`) under a file lock. Without a key nothing changes.
  - The key is claimed (`in_progress`) under the lock before dispatch, so of several calls racing with one key
    across processes exactly one is sent; the others are `blocked` ("in use by another call"). A claim left by
    a crashed process stops blocking after 10 minutes.
  - An error after the claim releases the key if nothing was sent, and records `ambiguous` otherwise.

## Network boundary

localhost, RFC1918, link-local (169.254.169.254), unique-local and reserved addresses are blocked unless
`allow_private_network` is set. Three layers:
1. the URL passed to `open` is checked first, with a clear error,
2. Chromium's request routing checks every request it sees,
3. both engines connect through a local guard proxy (`lean_browser/netguard.py`). It resolves each host,
   refuses if any address is private, and connects to the address it checked. That covers redirect hops
   (which request routing never sees), DNS rebinding, subresources and WebSockets.

Limit: if `HTTP(S)_PROXY` is set in the environment, the guard proxy is off and redirect hops aren't checked.

## Where it is tested

| Area | Code | Tests |
|---|---|---|
| Verification honesty: 21 action cases + 6 `expect=` cases × 2 engines, false-verified must be 0 | `session.py` `_signals`, `_status`, `_after` | `tests/test_verification.py`, `scripts/verification_matrix.py` (repeated runs; weekly `reliability.yml`) |
| Outcomes on real flows: rejected login, server rejection, slow submit, `expect=` | `session.py` | `tests/test_reliability.py` |
| Duplicate guard, action keys (across sessions, different keys, no key, concurrent claims, errors after claim), retry-safety classes, dry run | `session.py` `act`, `fill_form`, `retry_safety`; `action_keys.py` | `tests/test_reliability.py` |
| Recovery after re-render, reordered lists | `session.py` `_resolve_or_recover`, `_perform_guarded` | `tests/test_reliability.py`, `tests/test_session.py` |
| Private network: URL check, both engines, redirect hops | `tools.py`, `engine.py` `_route`, `netguard.py` | `tests/test_engine.py`, `tests/test_tools.py` |
| Uploads limited to allowed folders | `session.py` `_perform` (resolved path) | `tests/test_session.py` |
| Trace redaction | `trace.py` | `tests/test_trace.py` |
| MCP contract, invalid calls, stdout purity, isolation, concurrency | `mcp_server.py`, `tools.py` | `tests/test_contract.py` |
| Engine crash mid-session | `tools.py`, `engine.py` | `test_engine_crash_mid_session_is_explained_and_recoverable` |
| Agent-level outcomes (server-checked, 100 tasks) | — | `evals/` (needs `claude -p`) |

## Known gaps

- English-only success and error words. A page in another language usually ends `unverified`, which is
  honest but unhelpful.
- Non-submit clicks are verified by any page change.
- The suite's pages were written by the project. Cases from other people's real failures belong in
  `evals/bench/verification.py`.
