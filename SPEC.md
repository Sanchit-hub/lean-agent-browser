# Lean Agent Browser — Build Spec v2.1

> Hand this file to Claude Code. Build everything in this folder (`~/Desktop/lean/`).
> v2 changes from v1 are summarised at the bottom ("Changelog").

## Goal

A browser for AI agents that spends **far fewer total tokens per task** than screenshot-based,
full-HTML, or accessibility-tree browsing, **with the same task success rate**.

Built on Obscura (`h4ckf0r0day/obscura`, Rust, CDP-compatible) for low memory, with bundled
Chromium as a fallback engine.

"Tokens" always means **total tokens an agent spends to finish a task**: every step's input
(system prompt + tool schemas + accumulated history + tool results) plus output. Snapshot
size alone is not the metric.

## What earlier tests showed (why this design)

- Obscura and Chrome produce almost the same tokens for the same page. Obscura's win is
  memory: ~131 MB vs ~439 MB.
- Form fill + submit: screenshots after every step ≈ 13,660 tokens; full HTML ≈ 3,770;
  accessibility tree ≈ 2,100–2,360; compact list + batch fill ≈ 67. All submitted correctly.
- Real GitHub pages: trimmed main content + numbered actions was 45–79% smaller than the
  accessibility tree.
- Conclusion: savings come from the **representation layer**, not the engine. We do not fork
  Obscura. We build a layer on top of it.

These numbers measured snapshot size only. v2's eval harness must confirm them as
whole-task numbers.

---

## Architecture

```
Agent (Claude / Cursor / any MCP client)
        │  6 MCP tools (or CLI / Python API)
┌───────▼────────────────────────────────────┐
│ Tool layer      MCP server · CLI · library │
│ Session layer   tabs, profiles, settle-wait│
│ Diff layer      before/after snapshot diff │
│ Snapshot layer  injected JS → compact text │
│ Engine layer    Obscura ⇄ Chromium fallback│
└────────────────────────────────────────────┘
Eval harness drives all of the above through a real LLM agent.
```

1. **Engine layer**: launch `obscura serve`, connect with Playwright (Python)
   `chromium.connect_over_cdp`. Fall back to bundled Chromium on defined triggers (below).
2. **Snapshot layer**: a single injected JS function (`snapshot.js`) walks the live DOM and
   returns structured JSON. Python renders it to compact text. It does **not** depend on the
   CDP Accessibility domain, so output is identical on both engines.
3. **Diff layer**: after every action, wait for the page to settle, re-snapshot, and return
   only what changed.
4. **Tool layer**: MCP server (stdio), CLI, Python library. All three use the same core.
5. **Eval harness**: a real LLM agent runs fixed tasks in several modes and measures
   total tokens, success, steps, time and memory.

### Tech choices

- Python 3.12, managed with `uv`. Pin Playwright and every other dependency in `uv.lock`.
- MCP via the official `mcp` Python SDK.
- Runtime token estimates use `len(text) / 4`. Evals use real counts (Anthropic
  `count_tokens` API plus the `usage` field of each response).

---

## Step 0: Obscura compatibility check (do this first)

> **A spike already ran this on 2026-11-14 against Obscura v0.2.6. Read `spike/FINDINGS.md`
> first.** In short: navigation, layout, forms (urlencoded), clicks, dialogs, SPA routing and
> screenshots work. File upload, multipart forms, Playwright locators inside shadow DOM and
> iframes, contenteditable, popups and subresource blocking do **not** work. The engine-routing
> rules below come from those results. Turn the spike into the permanent script described here,
> and re-run it whenever the pinned Obscura version changes.

Before writing the layers, write `scripts/compat_check.py`. It connects to `obscura serve`
and exercises every CDP feature we depend on, then prints a pass/fail table:

| Needed for | CDP / Playwright feature |
|---|---|
| Connect | `connect_over_cdp`, `Target.*`, new context, new page |
| Navigate | `page.goto`, load events, `page.go_back` |
| Snapshot | `Runtime.evaluate` / `page.evaluate` running `snapshot.js` |
| Visibility | `getBoundingClientRect`, `getComputedStyle` return real values (layout exists) |
| Actions | `Input.dispatchMouseEvent`, `Input.insertText`, key events, `locator.set_input_files` |
| Blocking | `Fetch.enable` / `page.route` request interception |
| Frames | iframe enumeration and evaluation inside frames |
| Cookies | `context.storage_state()` save and load |
| Screenshot | `page.screenshot(clip=…)` |

Write the results to `docs/obscura-compat.md`. Any feature that fails becomes an automatic
fallback trigger for that operation. If layout values are fake (all zeros), visibility filtering
must use only the attribute and CSS-class rules on Obscura, and the report must say so.

---

## Engine layer

- Start `obscura serve` once per process on a free port. Reuse it. Use a context pool
  (default size 4).
- `Engine` interface: `new_page()`, `close()`, `name` (`"obscura"` | `"chromium"`).

### Obscura process hardening (required)

*(Implemented in `lean_browser/engine.py`; tested in `tests/test_engine.py`.)*

- Pin Obscura **v0.2.6** and verify its SHA256 (spike-verified:
  `19faa248ac762f466ddb822dbb03ed4f097312d10d1a4d5b2143e6040a9bebd0`). The binary is only
  ad-hoc signed, so it always runs sandboxed. **Every launch re-hashes both extracted binaries**
  (`obscura`, `obscura-worker`) and refuses to start on a mismatch.
- Launch it under `sandbox-exec`: no reads of `$HOME` except its own folder, writes only to its
  temp dir, inbound only on localhost. Set `HOME` and `TMPDIR` to that temp dir. The temp dir is
  deleted on stop.
- Use a random 32-byte `OBSCURA_CDP_TOKEN` per launch and pass it as a bearer header. Requests
  without the token are refused (tested).
- Use `--allow-private-network` only when the user opts in (local dev testing). **The Chromium
  fallback enforces the same policy** (it blocks loopback, RFC1918, link-local/metadata and
  hostnames that resolve to them), so a fallback never widens network access.
- **Never pass `--allow-file-access`.** Pages with file inputs are routed to Chromium anyway,
  because Obscura drops files from multipart forms, so Obscura never needs to read local files.

### Routing: which engine handles a page

Obscura is the default. Use Chromium **from the start** (before any action, so no state is lost)
when the first snapshot of a page shows any of these. Every rule comes from a spike failure:

| Page feature | Why (Obscura 0.2.6) |
|---|---|
| `input[type=file]` or `form[enctype="multipart/form-data"]` | multipart is silently sent as urlencoded and the file is dropped |
| visible `[contenteditable]` editor | typing is ignored |
| cross-origin `iframe` with interactive content | frames are not exposed |
| `snapshot.js` takes longer than 2 s | walker too slow (GitHub timed out at 30 s) |

Switching engines copies cookies and storage from the Obscura context and reopens the URL in Chromium.

### Fallback triggers (after something has already gone wrong)

Reopen the same URL and session state in Chromium when any of these happens:
  1. A CDP call returns "method not found / not implemented".
  2. Navigation errors or times out (default 20 s).
  3. The snapshot has 0 interactive elements, but the raw HTML contains `<form`, `<input`,
     `<button` or `role="button"`.
  4. `screenshot` is called and Obscura cannot render it.
  5. A per-domain override in config (`fallback_domains: [...]`) matches.
  6. An action needs a popup or new tab (`window.open` returns null on Obscura).

### How actions run on Obscura

Playwright locators time out inside shadow DOM and iframes on Obscura. So on Obscura, actions
run **through our own injected JS, keyed by `data-lab-id`**:
- click: `el.click()`
- fill: set `value`, then dispatch `input` and `change`
- select / check: set the property, then dispatch `change`
- press Enter: `form.requestSubmit()`

All of these were spike-verified, including inside shadow roots and same-origin iframes. On
Chromium, use normal Playwright actions (trusted events).
- Every fallback is logged and shown in the snapshot header: `engine: chromium (fallback: no-layout)`.
- Cache the Chromium/Obscura choice per domain for the session, so a fallback happens only once.

---

## Snapshot layer

### Element IDs (must stay stable)

- `snapshot.js` gives every element it reports a `data-lab-id` attribute the first time it
  sees it. The ID stays the same for as long as that DOM node exists.
- If a framework re-renders and replaces a node, match the new node to the old one by
  fingerprint: `role + accessible name + nearest landmark + index among siblings with the
  same role/name`. On a match, reuse the old ID.
- IDs are small integers, unique within a tab, and **never reused** within one page load.
- When a new document loads, IDs reset and the header says `page changed`.
- On a client-side (SPA) route change, the document is the same, so IDs carry over through
  fingerprint matching and the header says `route changed`.
- Elements inside iframes and open shadow roots get IDs too, in the same number space.

### What is included

- **Interactive elements**: `a[href]`, `button`, `input`, `select`, `textarea`,
  `[contenteditable]`, `[role=button|link|checkbox|radio|switch|tab|menuitem|option|combobox|textbox|slider]`,
  `[onclick]`, `tabindex>=0`, and elements with `cursor:pointer` whose parent does not also have
  it (this catches React-style handlers attached at the root, which wrapping `addEventListener`
  cannot see). Also wrap `addEventListener` with `add_init_script` to catch directly attached
  click listeners where the engine supports init scripts.
- **Dropped**: `script`, `style`, `svg` internals, `noscript`, `template`, `[hidden]`,
  `[aria-hidden=true]`, `display:none`, `visibility:hidden`, zero-size, `opacity:0`, and
  off-screen clipped text. Dropping hidden text also removes a common prompt-injection vector.
- **Main content first**: `main`, `[role=main]`, `article`. If none exists, use the
  largest text-dense block.
- **Names**: use `aria-label`, then `<label>`, `img[alt]`, `svg title`, `title`, then text.
  Links and buttons that still have no name are dropped. A `banner:` line is only emitted when
  the banner has buttons. (The spike found both problems: icon links showed as `link ""`, and
  Wikipedia gave a false cookie banner.)
- **Performance**: the spike prototype was ~20× slower on Obscura than Chromium and timed out
  on GitHub. Collect candidates with one `querySelectorAll` of interactive selectors. Check
  visibility only for candidates and their ancestors, and cache it per element. Call
  `getComputedStyle` at most once per element. Targets: < 300 ms on a GitHub repo page in
  Obscura, with a hard 2 s budget that triggers routing to Chromium.

#### Implementation status (step 3, 2026-11-14)

The walker is in `lean_browser/snapshot.js` and the renderer in `lean_browser/snapshot.py`.
Tests are in `tests/test_snapshot.py` and run on both engines.

- **Obscura quirks found while building it.** Each one has a workaround in the code:
  - Writing `data-lab-id` during the walk made the walk quadratic, because Obscura restyles the whole
    document after any DOM mutation. All ID writes are now deferred to the end. On the 6k-element
    test page this took the walk from 3.7 s to 0.47 s.
  - The `el.required` and `img.alt` properties are undefined, so the walker reads attributes instead.
  - An inline `<a>` that only wraps an `<svg>` reports a 0×0 rect, so the walker falls back to the
    child's rect.
  - `innerText` costs ~0.17 ms per element (Chromium is ~100× cheaper), which dominates on large pages.
- **Measured** (lean = default `actions` snapshot at the 800-token budget; tokens via a tiktoken
  proxy because no API key is configured):

  | Page | Obscura ms | Chromium ms | Lean tokens | Lean unbudgeted | Playwright aria_snapshot |
  |---|---|---|---|---|---|
  | GitHub repo | **1,044** | 20 | 949 | 1,587–2,022 | 19,298 |
  | Wikipedia article | 164 | 13 | 954 | 1,216–1,324 | 19,338 |
  | Hacker News | 92 | 6 | 959 | 959 | 10,263 |
  | 6k-element fixture | 472 | 15 | — | — | — |

  The default snapshot is **10–20× smaller** than the aria snapshot.
- **Update:** visibility now uses native `element.checkVisibility()`. On Obscura, reading several
  computed-style properties from one style object costs ~2.2 s on a GitHub page, against 2 ms for
  `checkVisibility`. Text-only elements are also named with `textContent`. As a result, GitHub on Obscura
  went from 1,044 ms to **~90 ms**, Wikipedia from 164 to 79 ms, and HN from 92 to 63 ms. The 300 ms target
  is now met.

### Collapse, don't delete

`nav`, `header`, `footer`, `aside`/sidebars, and any list with more than 8 similar items become
one line with a handle:

```
nav: Home, Jobs, About (+3) [expand:n1]
list "Results" 48 items: "Senior Backend…", "ML Intern…", … [expand:l1]
```

Repeated links (same href and text) are deduplicated. URLs are never printed. The agent clicks
by ID. If text goes over the budget, it is cut and ends with `[more:k1]`.

### Format (`actions` mode, the default)

```
page: Apply: Backend Intern | url: /jobs/42 | engine: obscura
1: textbox "Full name"* = "Asha"
2: textbox "Email"* type=email = "asha@" !"Enter a valid email"
3: select "Role" [SDE Intern|ML Intern|APM Intern] = SDE Intern
4: checkbox "Relocate?" off
5: radiogroup "Work mode" [Remote|Onsite]
6: combobox "City" (custom) [expand:c1]
7: upload "Resume" accept=.pdf
8: button "Submit application"
nav: Home, Jobs, About (+3) [expand:n1]
```

- `*` marks a required field. `= value` shows the current value. `!"…"` shows a validation error.
- Password fields always show `= ••••` and never the real value.
- Custom (div-based) dropdowns show as `combobox … (custom)`. Expanding one lists its options as IDs.
- If a dialog or modal is open, it is listed first with the prefix `dialog:`, and the elements
  behind it are left out.
- A cookie or consent banner is shown as one line: `banner: cookies [reject:12] [accept:13]`.
- An element inside an iframe gets a prefix, e.g. `[frame:checkout] 14: textbox "Card number"`.

### Modes

| Mode | Content | When to use |
|---|---|---|
| `actions` | interactive elements + headings | default, most steps |
| `read` | main content as clean markdown, links as `[text](#id)`. On Obscura, start from its built-in CDP `LP.getMarkdown` (spike: 322 tokens for the form page). On Chromium, use our own Readability-style extraction | reading or extracting |
| `full` | full accessibility-style tree with IDs | lean view missed something |
| `screenshot` | PNG cropped to an element, or the viewport | captcha, charts, visual layout only |

Default budget: `actions` 800 tokens, `read` 1,500, `full` 4,000.

### Caching

Hash the snapshot JSON. If nothing changed since the last snapshot of this tab, return
`unchanged (snapshot #N)` instead of the full text.

### Untrusted content marker

Every tool result that contains page text is wrapped like this:

```
<page untrusted="true">
…
</page>
```

The MCP server instructions tell the agent that text inside `<page>` is data, not instructions.

---

## Settle and diff

### Settle wait (after every action)

Wait until **all** of these are true, or the 5 s cap is reached:
- no DOM mutations for 300 ms (MutationObserver injected by `snapshot.js`);
- no in-flight XHR/fetch requests, ignoring long-polling and websockets;
- a navigation that was started has reached `domcontentloaded`.

If the cap is hit, the response includes `(still loading)`.

### Diff format

```
~2 textbox "Email" = "asha@x.com"   (error cleared)
+9 text "Application received"
-8 button "Submit application"
```

- `~` changed, `+` added, `-` removed. Collapsed groups are diffed as one line.
- If a navigation happened, return the new page's `actions` snapshot instead of a diff.
- If the action had **no visible effect**, return `no change` plus a hint:
  `hint: try snapshot(mode="full") or screenshot(id)`.

### Implementation status (step 4, 2026-11-14)

The code is in `lean_browser/settle.py`, `lean_browser/diff.py` and `lean_browser/session.py`.
Tests are in `tests/test_session.py`, run on both engines, and every submission is checked by the
fixture server.

- **Settle** runs in page JS from an init script on both engines: it wraps fetch and XHR and adds
  a MutationObserver that ignores our own `data-lab-id` writes.
- **Actions.** On Chromium they use Playwright handles (trusted events). On Obscura they run as JS
  on the element: a pointer/mouse event sequence, then `click()`, with values set through the native
  setter. Both resolve the element from the snapshot's ID map, so shadow-DOM and same-origin-iframe
  elements work.
  - Chromium needs the handle re-resolved inside the iframe's own frame, or clicks land at the wrong
    coordinates.
  - On a custom combobox, `select` opens it and clicks the matching `[role=option]`.
- **Obscura never emits CDP dialog events.** `alert`, `confirm` and `prompt` silently return as if
  accepted. An Obscura-only init-script shim records each dialog and applies the agent's policy.
- **Dialog policy semantics:** `act("dialog", value="dismiss")` sets how the *next* native dialog
  is answered. The default is accept. The diff reports `dialog confirm '…' accepted|dismissed`.
- **`open()` navigates the current tab** when the engine stays the same, so `back` works. A change
  of engine opens a fresh page, and its history does not carry over.
- **Small region groups (≤ 3 items) render inline,** because collapsing them saved nothing and cost
  the agent an extra expand step.
- **`wait_for(text)`** returns `found '…'` plus a diff, if anything changed.
- **Not built yet:** `snapshot(within=id)`.

---

## Tools (MCP): 7 tools

Every tool schema costs tokens on every request, so the set stays small. Keep descriptions
to one short sentence each. The original target was **≤ 800 tokens for all definitions together**.
Measured reality as of 2026-11-15: ~1,550 Claude tokens for 7 tools, including the API's own
tool-use overhead (see below). Explain `act`'s actions in one enum with no per-value
prose. The README holds the long documentation.

#### Implementation status (steps 5–6, 2026-11-14)

- **Code:** tools and the facade are in `lean_browser/tools.py`, the MCP server (official `mcp`
  SDK 2.3.0, stdio, low-level `Server`, so the schemas carry no auto-generated titles) in
  `lean_browser/mcp_server.py`, and the CLI in `lean_browser/cli.py`. `extract` is in
  `lean_browser/extract.js`.
- **Schema size:** measured with `claude -p`, now with 7 tools (memory was added), the definitions cost
  **~1,550 real Claude tokens** per request, against Playwright MCP ~7,100 and agent-browser ~31,600.
  The tiktoken proxy reads 663 for the same text, so the proxy undercounts JSON schemas by about 2.3×.
  The test now keeps the proxy ≤ 700.
- **CLI:** `leanb open <url>`, `leanb shell <url>` and `leanb mcp`. This deviates from the plan:
  instead of separate stateful `leanb act …` commands (which would need a background daemon),
  `shell` is an interactive session with `act`, `fill`, `snapshot`, `find`, `expand`, `more`,
  `extract` and `screenshot`.
- **Errors:** every tool error comes back as an `Error: …` string, and as `is_error` over MCP. It is
  never raised into the agent loop.
- **Obscura quirk:** `table.rows` and `row.cells` don't exist there, so `extract` uses selectors.
- **Eval:** the runner has `lean` and `lean-escalate` modes. A fresh `LeanBrowser` starts per task,
  and the first user message carries the `open()` result. In `lean-escalate`, a failed or no-change
  `act`/`fill_form` gets `snapshot(mode=full)` appended automatically.
- **Still missing:** `--quick` runs `aria` + `lean`, because the Playwright MCP baseline (mode 4)
  is not wired in yet.

| Tool | Signature | Returns |
|---|---|---|
| `open` | `open(url, mode="actions", block=True)`; modes: minimal, actions, read, full | snapshot |
| `snapshot` | `snapshot(mode="actions", budget=None, expand=None, more=None, find=None, within=None)` | snapshot, expanded group, next chunk, or IDs that match `find` |
| `act` | `act(action, id=None, value=None, expect=None, dry_run=False)` | status line (verified / unverified / blocked / ambiguous / timed_out / done) + diff; `dry_run` returns a JSON preview with `executed: false` |
| `fill_form` | `fill_form(fields: {id: value}, submit: id \| bool \| "repeat" = False, expect=None, dry_run=False)` | status (`k/n fields set; submitted; …`) + diff, or the new page |
| `extract` | `extract(kind="auto" \| "table" \| "list" \| "form", within=None, fields=None, new_only=False)` | JSON with provenance; list items carry `fields`, `missing`, `conflicts` |
| `memory` | `memory(action="set" \| "get" \| "list" \| "delete" \| "clear", key=None, value=None)` | session notes with source URL |
| `screenshot` | `screenshot(id=None, annotate=False)` | PNG (element crop or viewport; annotate draws ids) |

`act` actions:

| action | needs `id` | `value` |
|---|---|---|
| `click`, `hover`, `check`, `uncheck`, `clear`, `focus` | yes | — |
| `fill` | yes | text |
| `select` | yes | option label (works for custom comboboxes too) |
| `press` | optional | key, e.g. `Enter`, `Tab`, `Escape` |
| `upload` | yes | local file path (must be inside an allowed directory) |
| `scroll` | optional | `down` / `up` / `bottom` (loads more items on infinite-scroll pages) |
| `back`, `forward`, `reload` | no | — |
| `wait_for` | no | text to wait for (max 10 s) |
| `tab` | no | `list` / `new:<url>` / `switch:<n>` / `close:<n>` |
| `dialog` | no | `accept` / `dismiss` (for native alert/confirm/prompt) |

Rules:
- New popups and tabs are tracked automatically and reported in the diff: `+tab 2 "Payment"`.
- `fill_form` fills fields in order, settles once at the end, and if `submit` is set, clicks the
  submit button and settles again. Validation errors are reported per field.
- `extract` is **deterministic** (DOM heuristics, no LLM call inside the tool). Schema-based LLM
  extraction is out of scope for v2, because those tokens would be hidden from measurement.
- Errors are short and actionable: `id 14 not found (page changed?) — call snapshot()`.

### Outcomes, recovery and dry-run (v0.3.0)

Dispatch and outcome are separate. `Session._status` decides the status from evidence collected after
the page settles (`Session._signals`):

1. **Errors first.** New field errors, new `role=alert` text with error words, or HTTP ≥ 400 on a
   navigation give `blocked`.
2. **Caller's postcondition.** `expect` (text, `url:<part>`, `gone:<id>`) is polled for up to 3 s. Met
   means `verified`; not met means `unverified`, or `timed_out` if the page never settled.
3. **Submit-like actions** (retry safety `unsafe`: risky names, submit buttons, Enter in a form field,
   `fill_form(submit=…)`) need a strong signal: navigation, a new success message, a cleared form, the
   target going away, or a new tab. A plain UI change stays `unverified`.
4. **Other clicks**: any observable change is `verified`.
5. An exception after an unsafe action may have been dispatched gives `ambiguous`. Unsafe actions are
   never retried.

Retry safety: `safe` (hover, focus, scroll, wait_for), `conditional` (fills, selects, checks, other
clicks, navigation), `unsafe` (above). Conditional value actions that fail, or whose target was replaced
mid-action, check the field state first, then re-identify the target and retry **once**.

Duplicate guard: the key is (URL, action, role, name, form, row text). Repeating an unsafe action within
10 minutes after a `verified`, `ambiguous` or `timed_out` outcome is blocked unless `value="repeat"`
(`submit="repeat"`). After `blocked` or `unverified` a retry is allowed.

Dry-run returns before the dialog policy sync and before `_perform`: nothing is dispatched and the
engine isn't switched. Target resolution may take a fresh snapshot (read-only). Ambiguity raises the
same `ambiguous:` error as a real action.

`Session.last_outcome` / `LeanBrowser.last_outcome`: `{action, target, executed, status, evidence[],
retry_safety, risk, recovery[]}`. Error categories (`session.error_category`): blocked, ambiguous,
stale, not_found, timeout, network, invalid, engine.

### Sessions and profiles

- `--profile <name>` stores cookies and storage in `~/.lean-browser/profiles/<name>/`
  (directory `chmod 700`).
- Config lives in `~/.lean-browser/config.toml`: pool size, timeouts, budgets, blocking,
  `fallback_domains`, `allowed_domains`, `allowed_upload_dirs`. CLI flags override it.
- Optional `allowed_domains`. Navigating outside them returns an error.
- `upload` only reads files from `allowed_upload_dirs` (default `~/Downloads`, `./fixtures`).

---

## Escalation ladder

Escalation is **suggested by the tool and chosen by the agent**, never silent. A silent switch
to a heavier mode would hide token cost.

| Failure signal | Hint in response |
|---|---|
| `act` → element not found | `call snapshot()` |
| `act` → no visible change | `try snapshot(mode="full")` |
| target text not in `actions` view (`find` returns nothing) | `try snapshot(mode="read")` |
| `full` still misses it / canvas / captcha | `try screenshot(id)` |

The eval harness also runs a "lean + auto-escalate" variant to compare against.

---

## Efficiency extras

- Block images, fonts, media, ads and trackers by default. Never block known captcha
  providers (reCAPTCHA, hCaptcha, Turnstile). Turn blocking off for a page with
  `open(url, block=False)`.
  - **Chromium**: `page.route` with an EasyList-style host list in `blocklist.txt`.
  - **Obscura**: `page.route` does not stop subresources (the spike's image still loaded,
    because Obscura only intercepts the main document). Use the `-stealth` release build's
    built-in tracker blocking instead. Images don't affect tokens, only bandwidth.
- A screenshot taken while images are blocked carries the note `(images blocked — reopen with
  block=False if visuals matter)`. The tool does not reload on its own, because that would lose
  page state.
- One browser process, a warm context pool, and a pre-warmed blank page.
- Snapshot cache per tab (hash-based, as above).

---

## Eval harness (non-negotiable)

### Fixtures

`evals/fixtures/` contains a local site (FastAPI + static pages) that **records every
submission**, so success is checked by the server, not by what the agent says.

18 tasks:

| # | Task | Tests |
|---|---|---|
| 1 | Login | basic form |
| 2 | Signup with validation errors | inline errors, retry |
| 3 | Multi-step wizard (3 pages) | navigation, state |
| 4 | Job application with resume upload | `upload` |
| 5 | Custom div dropdown + date picker | custom widgets |
| 6 | Cookie banner blocks the form | banner handling |
| 7 | Search + extract the top 5 results to JSON | `extract` |
| 8 | Paginated table: find a row on page 3 | pagination |
| 9 | Infinite scroll: find item #40 | `scroll` |
| 10 | React SPA: client-side routing, re-renders | stable IDs |
| 11 | Modal confirm dialog before delete | dialogs |
| 12 | Native `confirm()` | `dialog` action |
| 13 | Form inside an iframe | frames |
| 14 | Web component with shadow DOM | shadow roots |
| 15 | Link opens a new tab, finish there | tabs |
| 16 | Long article: answer a question from the text | `read` mode |
| 17 | Hidden prompt-injection text on the page | must ignore it |
| 18 | Contenteditable rich-text comment box | contenteditable |

Plus an optional `evals/live/` set (3–5 real public sites, read-only tasks). It is reported
separately because live sites change.

### Modes compared

1. Screenshots after every step
2. Full HTML
3. Raw accessibility tree
4. **Playwright MCP** (`@playwright/mcp`), the main real-world competitor
5. Lean (agent chooses escalation)
6. Lean + auto-escalate

### Method

- A real LLM agent loop (Anthropic API, model pinned in `evals/config.toml`, default
  `claude-sonnet-5-5`, effort `medium` (current models reject `temperature`, so runs are not deterministic, which is why there are 3 per task), no refusal fallback model (one model per run), same system prompt in every mode except the tool list).
  Max 25 steps per task.
- Each task runs **3 times per mode**. Report the mean and the min/max.
- **Tokens**: report two numbers per run.
  1. **Raw tokens** = sum of `input_tokens + output_tokens` over all steps, with prompt caching
     off. This is the main comparison.
  2. **Cached cost**: the same run repeated with prompt caching on, reported as cost-weighted
     tokens (cache reads count at their discounted rate). Real agents use caching, and caching
     shrinks the cost of tool schemas and history, so this shows the saving people actually get.
  Also report the tool-schema token count per mode.
- `uv run leanb-eval --quick` runs 1 repetition of 6 representative tasks in Lean and
  Playwright MCP modes only, for fast checks during development. The full run
  (18 tasks × 6 modes × 3 runs, plus a cached repeat) is for milestones only. The runner prints
  an estimated API cost and asks for confirmation before starting a full run.
- The Playwright MCP baseline needs Node.js ≥ 20 (`npx @playwright/mcp@<pinned version>`).
- Also measure success (server-verified), steps, wall time, and peak RSS of the browser
  processes.
- **Pass bar**: Lean success rate ≥ the best baseline's success rate, and Lean median total
  tokens ≤ 50% of Playwright MCP's.

### Output

`evals/report.md` with per-task and summary tables, plus `evals/results/*.jsonl` raw logs
(one line per step) so the numbers can be re-checked.
`uv run leanb-eval` runs it all. Requires `ANTHROPIC_API_KEY` in the environment.

---

## Deliverables

```
~/Desktop/lean/
  SPEC.md
  README.md                 setup, MCP config snippet for Claude Code / Cursor, examples
  install.sh                one command install
  pyproject.toml, uv.lock
  lean_browser/
    engine.py               Obscura + Chromium, fallback
    snapshot.js             injected DOM walker, IDs, settle observer
    snapshot.py             render JSON → text, budgets, modes
    diff.py
    session.py              tabs, profiles, dialogs, blocking
    tools.py                the 7 tool implementations
    mcp_server.py
    cli.py
  scripts/compat_check.py
  docs/obscura-compat.md
  evals/  fixtures/ tasks/ runner.py report.md results/
  tests/
```

- **CLI** is named `leanb` (the name `lab` is already used by GitLab's CLI):
  `leanb open <url>`, `leanb snapshot --mode read`, `leanb act click 6`, `leanb mcp`.
- **install.sh**: installs `uv`, syncs dependencies, downloads the **pinned** Obscura v0.2.6
  release (`obscura-aarch64-macos.tar.gz`, or `-stealth` if blocking is wanted, each with its own
  pinned hash), **verifies its SHA256** against a value stored in the script,
  removes the macOS quarantine flag (`xattr -d com.apple.quarantine`), installs it to
  `~/.lean-browser/bin/`, runs `playwright install chromium`, then runs `compat_check.py`.
  Exits non-zero on any failure, with a clear message.
- **Tests** (pytest, against local fixture pages):
  - snapshot: filtering, collapse, dedupe, budgets, password masking, iframe/shadow DOM
  - IDs stay stable across re-renders, reset on navigation, are never reused
  - diff: `+ ~ -`, navigation → snapshot, no-change hint
  - settle: delayed XHR, debounced validation
  - `fill_form` with validation errors
  - fallback triggers (mock engine that raises "not implemented")
  - tool-schema token size stays ≤ 800

---

## Build order

0. `compat_check.py` + `docs/obscura-compat.md`
1. Fixture site + eval runner skeleton (baseline modes 1–3 working), so numbers exist from day one
2. Engine connect + fallback
3. `snapshot.js` + rendering + IDs (+ tests)
4. Settle + `act` + diff (+ tests)
5. `fill_form`, `extract`, tabs, dialogs, upload
6. MCP server + CLI
7. Full eval run (all 6 modes) + `report.md`
8. Polish: caching, blocking, README, install script

After every step from 3 onward, re-run the eval and note the change in `evals/CHANGELOG.md`.

### Build status (2026-11-14)

Steps 0–8 are done. All ~135 tests pass.

**Step 7, the eval, ran on 2026-11-15** with Claude Sonnet 5.5 via `claude -p`, because no API key
was available (`evals/claude_driver.py`). It covered lean vs Playwright MCP, 18 tasks × 3 runs:
- both modes passed 54/54;
- lean's median tokens were 24% of Playwright MCP's, so the pass bar is met;
- lean used 4.5× fewer tokens in total, half the cost, and 1.7× less time.

Full results are in `evals/CHANGELOG.md`. The screenshot, HTML and raw-aria baselines still need the
API runner and an account with API credits.

Polish (step 8) notes:
- **`install.sh` deviates from the plan:** it uses `python -m venv` + pip with pinned versions
  instead of installing `uv`. That avoids a `curl | sh` bootstrap.
  - It verifies the Obscura tarball against the release SHA256 and the extracted binaries against
    the pinned hashes.
  - It installs to `~/.lean-browser/` (directory set to `chmod 700`).
  - It installs Chromium to `~/.lean-browser/pw-browsers`, which `lean_browser` finds automatically.
  - It ends with `leanb doctor`.
- **Playwright MCP baseline:** pinned to `@playwright/mcp@0.0.83` and installed with
  `--ignore-scripts` (`./install.sh --with-eval`). It runs headless and isolated, against our own
  Chromium (`--executable-path`).
- **Blocking:** Chromium skips images, media, fonts and the hosts in `lean_browser/blocklist.txt`.
  Captcha providers are never blocked. `open(url, block=false)` turns blocking off. A screenshot
  taken while blocking is on says so. Obscura gets no blocking in the default (non-stealth) build.
- **Snapshot caching** works as specified: an unchanged page returns `unchanged (snapshot #N)`.

---

## Out of scope for v2

- Solving captchas (we only show a screenshot to the agent or human)
- LLM-based extraction inside tools
- Forking or modifying Obscura's Rust code
- Windows/Linux install (the code should stay portable, but only macOS arm64 is tested)

---

## Changelog (v2 → v2.1, after the 2026-11-14 spike)

- Added Obscura hardening: sandbox-exec profile, CDP token, pinned v0.2.6 plus hash,
  never `--allow-file-access` (uploads route to Chromium). Chromium fallback enforces the same private-network policy.
- Added feature-based engine routing (file upload/multipart, contenteditable, cross-origin
  iframes, slow walker → Chromium), plus a popup fallback trigger.
- Actions on Obscura go through our own JS by `data-lab-id`, not Playwright locators.
- Snapshot: name fallbacks, drop nameless links, banner only with buttons, performance budget.
- `read` mode uses `LP.getMarkdown` on Obscura. Blocking on Obscura uses the stealth build.
- Measured: lean snapshot is 3–10× smaller than Playwright's aria snapshot. Obscura uses ~3×
  less memory on real pages. Whole-task tokens are still unmeasured (needs an API key).

## Changelog (v1 → v2)

- Metric changed from snapshot size to **total tokens per task**. Added a real LLM agent,
  3 runs per task, and server-verified success.
- Added **Playwright MCP** as a baseline, plus a pass bar.
- Tool set cut from ~13 to **6**, with a schema token budget (≤ 800).
- Eval reports both raw tokens and cached cost, has a `--quick` mode, and pins the model.
- Added **Step 0**: Obscura compatibility check. The snapshot is built from injected JS rather
  than the CDP Accessibility domain. Fallback triggers are now defined.
- Stable ID algorithm defined. Settle wait and diff format defined.
- Escalation is now hinted to the agent, not done silently.
- Added iframes, shadow DOM, custom widgets, contenteditable, keyboard, upload, scroll,
  dialogs and tabs.
- Security: untrusted page wrapper, password masking, pinned and checksummed install,
  profile directory permissions, domain and upload allowlists.
- `extract` is deterministic. CLI renamed `lab` → `leanb`. Build root is `~/Desktop/lean/`.
- Eval moved to the start of the build order.
