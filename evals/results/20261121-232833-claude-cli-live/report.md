# Eval report — 20261121-232833-claude-cli-live

Model `claude-sonnet-5-5 via claude -p`, effort `medium`, 32 tasks × 1 run(s). Success is verified by the fixture server.

## Summary — Prompt caching ON (cost-weighted input)

| Mode | Success | Median total tokens | p95 total tokens | Mean steps | Median time (s) | p95 time (s) | Tool schema tokens |
|---|---|---|---|---|---|---|---|
| lean | 29/32 (91%) | 4,155 | 41,598 | 5.3 | 17.7 | 34.1 | — |
| playwright-mcp | 31/32 (97%) | 4,975 | 12,208 | 3.7 | 14.9 | 19.2 | — |

### Per task — Prompt caching ON (cost-weighted input)

| Task | lean | playwright-mcp |
|---|---|---|
| live-python-designer | ✅ 1/1 · 7,358 | ✅ 1/1 · 12,208 |
| live-halley | ✅ 1/1 · 7,140 | ✅ 1/1 · 14,484 |
| live-obscura-license | ✅ 1/1 · 5,865 | ✅ 1/1 · 5,098 |
| live-example-link | ✅ 1/1 · 3,003 | ✅ 1/1 · 4,306 |
| live-httpbin-form | ✅ 1/1 · 4,593 | ✅ 1/1 · 9,555 |
| live-books-price | ✅ 1/1 · 2,464 | ✅ 1/1 · 4,990 |
| live-books-travel | ✅ 1/1 · 8,526 | ✅ 1/1 · 4,540 |
| live-books-page2 | ✅ 1/1 · 2,513 | ✅ 1/1 · 3,702 |
| live-books-links | ✅ 1/1 · 33,547 | ✅ 1/1 · 4,082 |
| live-quotes-love | ✅ 1/1 · 3,595 | ✅ 1/1 · 4,566 |
| live-quotes-js | ✅ 1/1 · 3,109 | ✅ 1/1 · 5,613 |
| live-quotes-scroll | ❌ 0/1 · 16,298 | ❌ 0/1 · 4,919 |
| live-ti-dropdown | ✅ 1/1 · 3,000 | ✅ 1/1 · 5,756 |
| live-ti-checkboxes | ✅ 1/1 · 2,951 | ✅ 1/1 · 4,777 |
| live-ti-loading | ✅ 1/1 · 4,060 | ✅ 1/1 · 4,913 |
| live-ti-confirm | ✅ 1/1 · 4,120 | ✅ 1/1 · 6,256 |
| live-ti-prompt | ✅ 1/1 · 5,426 | ✅ 1/1 · 7,080 |
| live-ti-tables | ✅ 1/1 · 3,147 | ✅ 1/1 · 4,826 |
| live-ti-hover | ✅ 1/1 · 7,771 | ✅ 1/1 · 6,739 |
| live-ti-add | ✅ 1/1 · 3,996 | ✅ 1/1 · 4,816 |
| live-ti-window | ✅ 1/1 · 2,904 | ✅ 1/1 · 7,985 |
| live-ti-frames | ✅ 1/1 · 3,496 | ✅ 1/1 · 4,562 |
| live-ti-iframe-editor | ❌ 0/1 · 6,453 | ✅ 1/1 · 4,540 |
| live-ti-controls | ✅ 1/1 · 4,189 | ✅ 1/1 · 5,004 |
| live-ti-enable | ✅ 1/1 · 3,704 | ✅ 1/1 · 6,210 |
| live-ti-shadow | ✅ 1/1 · 2,814 | ✅ 1/1 · 4,959 |
| live-ti-slider | ✅ 1/1 · 4,915 | ✅ 1/1 · 6,125 |
| live-ti-keys | ✅ 1/1 · 4,610 | ✅ 1/1 · 4,941 |
| live-ti-status | ✅ 1/1 · 2,492 | ✅ 1/1 · 4,714 |
| live-todomvc | ❌ 0/1 · 41,598 | ✅ 1/1 · 5,926 |
| live-wiki-search | ✅ 1/1 · 7,728 | ✅ 1/1 · 5,127 |
| live-hn-links | ✅ 1/1 · 53,350 | ✅ 1/1 · 4,321 |

## Failures

| Mode | Task | Run | Category | Stop | Reason | Tool errors |
|---|---|---|---|---|---|---|
| lean | live-quotes-scroll | 1 | wrong_answer | success | answer missing ['george bernard shaw'] | cost_usd=0.04856010000000001 |
| playwright-mcp | live-quotes-scroll | 1 | wrong_answer | success | answer missing ['george bernard shaw'] | cost_usd=0.012545899999999999 |
| lean | live-ti-iframe-editor | 1 | wrong_answer | success | answer missing ['your content goes here'] | cost_usd=0.0208511 |
| lean | live-todomvc | 1 | step_limit | error_max_turns | answer missing ['2'] | cost_usd=0.11717940000000002 |
