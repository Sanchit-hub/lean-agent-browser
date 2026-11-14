# Obscura vs Chromium spike: findings (2026-11-14)

Scripts: `spike/compat.py`, `spike/followup.py`, `spike/followup2.py`, `spike/snapshot.js` (prototype).
Raw output: `spike/results/`.

## Setup and security measures used

| Measure | Status |
|---|---|
| Obscura **v0.2.6** pinned (v0.2.7 was 1 day old, skipped) | done |
| SHA256 verified against GitHub release digest `19faa248…bd0` | match |
| Binary: Mach-O arm64, **ad-hoc signed only** (no Developer ID) | noted, so sandbox is mandatory |
| Obscura runs under `sandbox-exec`: no reads of `$HOME` (except its own folder), writes only to a temp dir, inbound only on localhost, outbound localhost-only for fixture runs | verified: reading `~/.zshrc`, writing to `~/Desktop`, reaching the internet are all blocked |
| CDP bound to 127.0.0.1 plus a random 32-byte bearer token | done |
| Chromium = Playwright 1.64.1 bundled build, throwaway profile, not the user's Chrome | done |
| Fixture server bound to 127.0.0.1 | done |
| Public pages: read-only GETs only (GitHub repo page, Wikipedia, HN) | done |
| Upload with `--allow-file-access`: the sandbox still refused `~/.zshrc` ("Operation not permitted") | verified |

Token counts use tiktoken `o200k_base` as a **proxy**. Claude's tokenizer differs by roughly
10–20%. Ratios between modes are reliable, absolute numbers are approximate.
Screenshot cost uses Claude's formula (w×h/750).

## 1. Token sizes per representation

Fixture job-application form:

| Representation | Obscura | Chromium |
|---|---|---|
| **Lean snapshot (prototype)** | **180** | **186** |
| Obscura `LP.getMarkdown` | 322 | n/a |
| Playwright `aria_snapshot` (what Playwright MCP uses) | 628 | 654 |
| Full HTML | 1,216 | 1,216 |
| Screenshot 1280×800 | ~1,365 | ~1,365 |
| Raw CDP AX tree (JSON) | 10,785 | 27,103 |

Real public pages (crude prototype: no list collapse, no budget yet):

| Page | Lean | aria_snapshot | HTML | Lean vs aria |
|---|---|---|---|---|
| GitHub repo | 1,866 (Chromium) / **timeout** (Obscura) | 19,298 | 217,488 | 10× smaller |
| Wikipedia article | 2,957–3,096 | 19,263–19,338 | ~137k | 6.3× smaller |
| Hacker News | 1,841 | 10,241 | 13,228 | 5.6× smaller |

Conclusion: the main claim holds. The representation layer gives 3–10× savings over the
Playwright MCP-style aria snapshot, and token output is the same on both engines.
**Not yet measured:** whole-task tokens with a real LLM agent (no `ANTHROPIC_API_KEY` set).

## 2. Memory (RSS of whole process tree)

| | Obscura | Chromium |
|---|---|---|
| Idle | **18 MB** | 848 MB |
| 4 fixture tabs | **59 MB** | 1,625 MB |
| After GitHub + Wikipedia + HN | **502–612 MB** | 1,600–2,000 MB |

Chromium's multi-process RSS double-counts shared pages, so treat the ratio as rough. On real
pages it is ~3×, in line with v1's 131 vs 439 MB. Obscura's "30 MB" applies to trivial pages only.

## 3. Compatibility matrix (Playwright over CDP)

| Feature | Obscura 0.2.6 | Chromium | Workaround on Obscura |
|---|---|---|---|
| navigate, evaluate, title, go_back | ✅ | ✅ (go_back after POST timed out once) | — |
| Layout (`getBoundingClientRect`, computed style) | ✅ real values | ✅ | — |
| `fill`, `keyboard.type`, debounced input events | ✅ | ✅ | — |
| select, checkbox, radio, click | ✅ | ✅ | — |
| Cookie banner blocks clicks (actionability) | ✅ same as Chrome | ✅ | snapshot must surface banner |
| Native `confirm()` dialog | ✅ | ✅ | — |
| Delegated (React-style) click + custom combobox | ✅ | ✅ | — |
| pushState routes + delayed fetch | ✅ | ✅ | — |
| MutationObserver, `add_init_script`, storage_state | ✅ | ✅ | — |
| Viewport + element screenshot | ✅ (fast, 24 ms) | ✅ | — |
| CDP `Accessibility.getFullAXTree` | ✅ (works, though not in README) | ✅ | not needed |
| `LP.getMarkdown` | ✅ | ❌ | use for `read` mode on Obscura |
| Form submit: urlencoded, Enter key, `requestSubmit()` | ✅ | ✅ | — |
| **File upload** `set_input_files` | ❌ `DataTransfer is not defined` | ✅ | `DOM.setFileInputFiles` works only with `--allow-file-access` |
| **Multipart form with file** | ❌ **silently sent as urlencoded, file dropped** | ✅ | **none, must use Chromium** |
| **Shadow DOM** via Playwright locator | ❌ timeout | ✅ | JS `el.click()` works. Mouse at coordinates does not |
| **iframe** via `frame_locator` / `page.frames` | ❌ frames not listed | ✅ | same-origin JS `contentDocument` works. Mouse+keyboard does not. Cross-origin: impossible |
| **contenteditable** typing | ❌ keyboard, insert_text and execCommand all ignored | ✅ | only direct `textContent` mutation |
| **window.open / target=_blank** | ❌ returns null; `_blank` opens in same tab | ✅ | acceptable for agents (same-tab) |
| **Image blocking** via `page.route` | ❌ handler runs but image still loads (interception covers main document only) | ✅ | `--stealth` tracker list; images don't affect tokens |

## 4. Snapshot prototype observations

- Hidden prompt-injection text (`display:none`, off-screen, `aria-hidden`) was **dropped** on both engines ✅
- Password value masked ✅. Values and validation errors inline ✅
- Shadow DOM and same-origin iframe content visible via JS walk on both engines ✅
- **Naive IDs change on re-render** (6 → 10 after a React-style re-render). Fingerprint matching is required, as spec v2 says.
- **snapshot.js is ~20× slower on Obscura** (89 ms vs 4 ms on the fixture). On GitHub it **timed out after 30 s**. Calling `getComputedStyle` on every element is the likely cause. The walker must check visibility only for candidate elements and cache results, and needs a time budget plus Chromium fallback.
- Icon-only links render as `link ""`. Names need fallbacks (img alt, svg title, aria-label), and links with no name at all should be dropped.
- The banner detector gave a false positive on Wikipedia (`banner: cookies` with no buttons). Only emit it when buttons are present.
- Repeated rows on HN were not collapsed (the prototype has no list collapse yet). That is the main remaining saving.

## 5. What this changes in the spec

1. **Engine routing by page features**, not just on failure. Use Chromium when the page has
   `input[type=file]`, a multipart form, a contenteditable editor, or cross-origin iframes,
   or when `snapshot.js` goes over its time budget.
2. **Act through our own JS by `data-lab-id`** on Obscura (el.click(), set value plus input events),
   not through Playwright locators. Locators fail inside shadow DOM and iframes on Obscura.
3. Sandbox Obscura with `sandbox-exec` by default, use a CDP token, and pin plus checksum the release.
   Only enable `--allow-file-access` inside the sandbox, with upload files copied into the sandbox dir.
4. `read` mode on Obscura uses `LP.getMarkdown`. On Chromium it uses our own Readability-style extraction.
5. Image blocking on Obscura uses `--stealth`, not `page.route`.
6. The snapshot walker needs a performance budget (target < 300 ms on GitHub-sized pages in Obscura).
