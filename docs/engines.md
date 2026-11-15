# Engines and compatibility

Lean runs pages on **Obscura** by default and falls back to **Chromium** (Playwright's Chrome for
Testing) when a page needs something Obscura can't do. Both engines sit behind the same API. Every
fallback is visible in the snapshot header (`engine: chromium (reason)`) and in traces.

## Pinned Obscura versions

| Version | Status | Release archive SHA256 (macOS arm64) |
|---|---|---|
| **0.2.7** | **default** (since 2026-11-15) | `fc7e73f23058f18d6d5be983d83b24ba374d12167677657a307a9476c0f5a7c1` |
| 0.2.6 | rollback: `LEANB_OBSCURA_VERSION=0.2.6` | `19faa248ac762f466ddb822dbb03ed4f097312d10d1a4d5b2143e6040a9bebd0` |

Both binaries are hash-checked before every launch (`lean_browser/engine.py: OBSCURA_HASHES`).
The full test suite passed on both versions on 2026-11-15 (170 passed, 1 skipped).

## Compatibility matrix

Generated with `python scripts/obscura_matrix.py 0.2.6 0.2.7`. It drives Obscura directly, with no routing.

| Check | Obscura 0.2.6 | Obscura 0.2.7 | Lean's handling |
|---|---|---|---|
| File upload in a multipart form | ❌ | ❌ | routed to Chromium |
| Playwright locator inside shadow DOM | ❌ | ❌ | Lean acts by id through its own JS (works) |
| Playwright `frame_locator` (same-origin iframe) | ❌ | ✅ | Lean acts by id through its own JS (works on both) |
| Typing into `contenteditable` | ❌ | ❌ | routed to Chromium |
| `window.open` popup | ❌ | ❌ | `target=_blank` opens in the same tab |
| `table.rows` / `cells` | ❌ | ✅ | `extract` uses selectors (works on both) |
| `el.required` / `img.alt` properties | ❌ | ❌ | the snapshot reads attributes |
| CDP dialog events | ❌ | ❌ | init-script shim records alert, confirm and prompt |
| Wikipedia "Halley's Comet" page stays responsive | ❌ (script thread hangs) | ✅ (5.4 s) | probes are time-boxed; a hung page moves to Chromium |
| 4 computed-style props on 6k elements | 722 ms | 699 ms | the snapshot uses `checkVisibility()` (~2 ms) |

## Routing rules (unchanged in 0.2.7)

A page goes to Chromium **before any action** when it has a file input or multipart form, a visible
`contenteditable` editor, or a cross-origin iframe. It also moves to Chromium when navigation fails,
when a snapshot is too slow, or when the page stops answering scripts. A domain that failed on Obscura
stays on Chromium for the rest of the session. The rules were kept even where 0.2.7 improved, because
the specific failures they cover still fail there.

## Platforms

macOS on Apple Silicon only, which is what CI tests (`macos-15`). Obscura runs under macOS
`sandbox-exec` with a parent-death watchdog.
