# Eval report — 20261122-000810-claude-cli-live

Model `claude-sonnet-5-5 via claude -p`, effort `medium`, 19 tasks × 1 run(s). Success is verified by the fixture server.

## Summary — Prompt caching ON (cost-weighted input)

| Mode | Success | Median total tokens | p95 total tokens | Mean steps | Median time (s) | p95 time (s) | Tool schema tokens |
|---|---|---|---|---|---|---|---|
| lean | 17/19 (89%) | 4,234 | 25,955 | 5.4 | 24.4 | 61.2 | — |
| playwright-mcp | 19/19 (100%) | 5,650 | 7,349 | 4.4 | 17.9 | 42.0 | — |

### Per task — Prompt caching ON (cost-weighted input)

| Task | lean | playwright-mcp |
|---|---|---|
| live-utp-classattr | ✅ 1/1 · 5,921 | ✅ 1/1 · 5,566 |
| live-utp-loaddelay | ✅ 1/1 · 2,450 | ✅ 1/1 · 5,912 |
| live-utp-ajax | ✅ 1/1 · 4,355 | ✅ 1/1 · 6,152 |
| live-utp-clientdelay | ✅ 1/1 · 5,853 | ✅ 1/1 · 6,159 |
| live-utp-textinput | ✅ 1/1 · 3,332 | ✅ 1/1 · 5,140 |
| live-utp-verifytext | ✅ 1/1 · 2,605 | ✅ 1/1 · 4,718 |
| live-utp-mouseover | ❌ 0/1 · 25,955 | ✅ 1/1 · 6,678 |
| live-utp-alerts | ✅ 1/1 · 3,104 | ✅ 1/1 · 5,568 |
| live-dq-textbox | ✅ 1/1 · 4,508 | ✅ 1/1 · 5,650 |
| live-dq-radio | ✅ 1/1 · 3,575 | ✅ 1/1 · 5,775 |
| live-dq-webtables | ✅ 1/1 · 2,708 | ✅ 1/1 · 3,787 |
| live-dq-select | ✅ 1/1 · 3,442 | ✅ 1/1 · 4,906 |
| live-dq-doubleclick | ❌ 0/1 · 4,824 | ✅ 1/1 · 6,449 |
| live-dq-modal | ✅ 1/1 · 3,610 | ✅ 1/1 · 5,209 |
| live-dq-dynamic | ✅ 1/1 · 2,478 | ✅ 1/1 · 5,515 |
| live-dq-date | ✅ 1/1 · 4,775 | ✅ 1/1 · 7,349 |
| live-dq-autocomplete | ✅ 1/1 · 4,397 | ✅ 1/1 · 6,893 |
| live-dq-slider | ✅ 1/1 · 7,754 | ✅ 1/1 · 4,793 |
| live-dq-tabs | ✅ 1/1 · 4,234 | ✅ 1/1 · 6,140 |

## Failures

| Mode | Task | Run | Category | Stop | Reason | Tool errors |
|---|---|---|---|---|---|---|
| lean | live-utp-mouseover | 1 | wrong_answer | success | answer missing ['2'] | cost_usd=0.07022730000000002 |
| lean | live-dq-doubleclick | 1 | wrong_answer | success | answer missing ['double click'] | cost_usd=0.0158801 |
