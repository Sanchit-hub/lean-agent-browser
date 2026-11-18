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
the input is `unverified`. If the action made the page schedule a short timer (a debounced autosave or delayed
validator, up to 3 s), Lean waits for it to fire before reading the field, so a field the page reverts a moment
later is caught; a page that schedules nothing isn't slowed down.

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

Errors win over every success signal above:
- New error text in a heading or live region, field errors, HTTP ≥ 400, a dialog whose message is an error, or a
  new "Try again" / "Retry" control make it `blocked`.
- New error text in the main content (plain paragraphs too, and same-origin frames; navigation, header, footer,
  links and buttons left out), or landing on an error path (`/error`, `/failed`, `/404`…), make it `blocked`;
  with a success signal at the same time it is `unverified`, since the page says both.
- A heading that was already there before the action ("Welcome back" on a login page that comes back) is not a
  new success message, and neither is a "Loading…"-style text ("Loading complete").
- When a live message is the only evidence and the page set a short timer (≤ 3 s) in response to the action,
  the page is read again after it fires, so an optimistic "Saved" that turns into an error is caught. Pages that
  set no timer aren't slowed down.

Otherwise:
- While the page shows a new "Processing…" / "Please wait" / "Loading…", Lean waits up to 8 s for the real answer.
- A dialog that was answered with nothing changing afterwards, or a new tab opening, is not proof for a submit.
- A click that changed nothing waits briefly for a late popup only when the target is a link or form with a
  `target`, or the page set a short timer.
- Time-like texts that only tick ("Last updated 3s ago") are not new evidence.

**Before a submit is dispatched**, the form's own validation (required, email, minlength, pattern) is checked.
If it fails, the submit is not sent and the status is `blocked` with the fields and messages. Chromium would
silently refuse that submit; Obscura doesn't validate forms at all and would have sent it.

**Error and success words** are English plus common ones in German, French, Italian, Spanish, Portuguese,
Russian, Chinese, Japanese, Korean and Hindi ("gespeichert", "enregistré", "guardado", "сохранено", "保存成功",
"保存しました", "저장되었습니다", "सहेजा गया", ...). Negated forms ("nicht gespeichert", "non enregistré",
"no guardado", "не сохранено", "未保存", "保存されていません", "저장되지 않", "सहेजा नहीं") count as errors, never
success, and a text that has both a success and an error word is not success.

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

With `HTTP(S)_PROXY` / `ALL_PROXY` set, the guard checks each destination and then chains to that proxy
(`NO_PROXY` hosts connect directly). Limits: the upstream proxy resolves names itself, so DNS rebinding is
only covered for direct connections; a `socks://` proxy can't be chained and turns the guard off, with a note.

## Where it is tested

| Area | Code | Tests |
|---|---|---|
| Verification honesty: 46 action cases + 11 `expect=` cases × 2 engines, false-verified must be 0 (the red-team cases in `KNOWN_FALSE_VERIFIED` are strict xfails until fixed) | `session.py` `_signals`, `_status`, `_after` | `tests/test_verification.py`, `scripts/verification_matrix.py` (repeated runs; weekly `reliability.yml`) |
| Outcomes on real flows: rejected login, server rejection, slow submit, `expect=` | `session.py` | `tests/test_reliability.py` |
| Duplicate guard, action keys (across sessions, different keys, no key, concurrent claims, errors after claim), retry-safety classes, dry run | `session.py` `act`, `fill_form`, `retry_safety`; `action_keys.py` | `tests/test_reliability.py` |
| Recovery after re-render, reordered lists | `session.py` `_resolve_or_recover`, `_perform_guarded` | `tests/test_reliability.py`, `tests/test_session.py` |
| Private network: URL check, both engines, redirect hops, DNS rebinding, WebSockets, behind the user's proxy | `tools.py`, `engine.py` `_route`, `netguard.py` | `tests/test_engine.py`, `tests/test_netguard.py`, `tests/test_tools.py` |
| Uploads limited to allowed folders | `session.py` `_perform` (resolved path) | `tests/test_session.py` |
| Trace redaction | `trace.py` | `tests/test_trace.py` |
| MCP contract, invalid calls, stdout purity, isolation, concurrency | `mcp_server.py`, `tools.py` | `tests/test_contract.py` |
| Engine crash mid-session | `tools.py`, `engine.py` | `test_engine_crash_mid_session_is_explained_and_recoverable` |
| Agent-level outcomes (server-checked, 100 tasks) | — | `evals/` (needs `claude -p`) |

## Real-site canary

Fixture results don't prove real sites work. `scripts/canary.py` opens about 10 stable public pages
(example.com, Wikipedia, python.org, the Python docs, MDN, Hacker News, a GitHub repo, rust-lang.org, httpbin,
IANA) through the Python API with default settings and the private network blocked. On each it checks the
first snapshot for a stable string, then runs one read-only action: `snapshot(find=...)`, `wait_for`, or a
click on a same-site link that must change the page. It never types, submits or logs in. Each row records
the engine that served the page, the fallback reason, seconds and pass/fail; `--json` writes them.

Real sites change and flake, so it exits 1 only when more than `--max-failures` (default 2) sites fail on
one engine. It runs weekly and by hand (`canary.yml`, macOS and Linux x86_64), never on push or PR, and
uploads the JSON. A failure means look, not necessarily a bug: check whether the site changed or was down.

```bash
.venv/bin/python scripts/canary.py --json canary.json
.venv/bin/python scripts/canary.py --engines obscura --sites wikipedia,github
```

## Known gaps

- A field is re-read after short timers (≤ 3 s) the page scheduled during the action. A page that changes the
  field later than that, or from a server push rather than a timer, is not seen.

- Success and error words cover eleven languages, a handful of words each. Other languages, and wordings
  outside the list, end `unverified`: honest but unhelpful, so pass `expect=`. The `expect=` negation check
  ("not <text>") knows the same eleven languages, both before the text ("nicht gespeichert", "no se ha
  guardado", "未保存") and after it ("保存されていません", "저장되지 않", "सहेजा नहीं"); other negations still count.
- Non-submit clicks are verified by any page change.
- The suite's pages were written by the project. Cases from other people's real failures belong in
  `evals/bench/verification.py`.
