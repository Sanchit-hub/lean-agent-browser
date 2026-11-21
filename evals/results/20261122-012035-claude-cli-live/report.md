# Eval report — 20261122-012035-claude-cli-live

Model `claude-sonnet-5-5 via claude -p`, effort `medium`, 51 tasks × 1 run(s). Success is verified by the fixture server.

## Summary — Prompt caching ON (cost-weighted input)

| Mode | Success | Median total tokens | p95 total tokens | Mean steps | Median time (s) | p95 time (s) | Tool schema tokens |
|---|---|---|---|---|---|---|---|
| lean | 51/51 (100%) | 4,008 | 9,016 | 4.1 | 16.5 | 30.4 | — |

### Per task — Prompt caching ON (cost-weighted input)

| Task | lean |
|---|---|
| live-python-designer | ✅ 1/1 · 5,545 |
| live-halley | ✅ 1/1 · 5,645 |
| live-obscura-license | ✅ 1/1 · 5,907 |
| live-example-link | ✅ 1/1 · 5,550 |
| live-httpbin-form | ✅ 1/1 · 5,554 |
| live-books-price | ✅ 1/1 · 2,334 |
| live-books-travel | ✅ 1/1 · 5,112 |
| live-books-page2 | ✅ 1/1 · 2,466 |
| live-books-links | ✅ 1/1 · 7,247 |
| live-quotes-love | ✅ 1/1 · 3,864 |
| live-quotes-js | ✅ 1/1 · 3,066 |
| live-quotes-scroll | ✅ 1/1 · 7,041 |
| live-ti-dropdown | ✅ 1/1 · 3,008 |
| live-ti-checkboxes | ✅ 1/1 · 2,961 |
| live-ti-loading | ✅ 1/1 · 4,068 |
| live-ti-confirm | ✅ 1/1 · 4,475 |
| live-ti-prompt | ✅ 1/1 · 4,547 |
| live-ti-tables | ✅ 1/1 · 3,158 |
| live-ti-hover | ✅ 1/1 · 9,016 |
| live-ti-add | ✅ 1/1 · 4,008 |
| live-ti-window | ✅ 1/1 · 2,929 |
| live-ti-frames | ✅ 1/1 · 6,000 |
| live-ti-iframe-editor | ✅ 1/1 · 2,721 |
| live-ti-controls | ✅ 1/1 · 3,033 |
| live-ti-enable | ✅ 1/1 · 4,608 |
| live-ti-shadow | ✅ 1/1 · 2,679 |
| live-ti-slider | ✅ 1/1 · 4,066 |
| live-ti-keys | ✅ 1/1 · 3,532 |
| live-ti-status | ✅ 1/1 · 2,514 |
| live-todomvc | ✅ 1/1 · 9,851 |
| live-wiki-search | ✅ 1/1 · 7,858 |
| live-hn-links | ✅ 1/1 · 18,111 |
| live-utp-classattr | ✅ 1/1 · 5,923 |
| live-utp-loaddelay | ✅ 1/1 · 2,494 |
| live-utp-ajax | ✅ 1/1 · 5,378 |
| live-utp-clientdelay | ✅ 1/1 · 4,170 |
| live-utp-textinput | ✅ 1/1 · 3,338 |
| live-utp-verifytext | ✅ 1/1 · 2,614 |
| live-utp-mouseover | ✅ 1/1 · 4,124 |
| live-utp-alerts | ✅ 1/1 · 3,116 |
| live-dq-textbox | ✅ 1/1 · 3,855 |
| live-dq-radio | ✅ 1/1 · 3,573 |
| live-dq-webtables | ✅ 1/1 · 2,718 |
| live-dq-select | ✅ 1/1 · 3,267 |
| live-dq-doubleclick | ✅ 1/1 · 3,064 |
| live-dq-modal | ✅ 1/1 · 3,528 |
| live-dq-dynamic | ✅ 1/1 · 3,676 |
| live-dq-date | ✅ 1/1 · 7,669 |
| live-dq-autocomplete | ✅ 1/1 · 4,423 |
| live-dq-slider | ✅ 1/1 · 3,023 |
| live-dq-tabs | ✅ 1/1 · 4,249 |
