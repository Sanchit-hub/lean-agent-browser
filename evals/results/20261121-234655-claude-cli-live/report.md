# Eval report — 20261121-234655-claude-cli-live

Model `claude-sonnet-5-5 via claude -p`, effort `medium`, 7 tasks × 1 run(s). Success is verified by the fixture server.

## Summary — Prompt caching ON (cost-weighted input)

| Mode | Success | Median total tokens | p95 total tokens | Mean steps | Median time (s) | p95 time (s) | Tool schema tokens |
|---|---|---|---|---|---|---|---|
| lean | 7/7 (100%) | 7,272 | 10,329 | 5.7 | 25.0 | 43.6 | — |

### Per task — Prompt caching ON (cost-weighted input)

| Task | lean |
|---|---|
| live-todomvc | ✅ 1/1 · 9,667 |
| live-ti-iframe-editor | ✅ 1/1 · 2,403 |
| live-books-links | ✅ 1/1 · 7,272 |
| live-hn-links | ✅ 1/1 · 10,329 |
| live-quotes-scroll | ✅ 1/1 · 5,298 |
| live-ti-hover | ✅ 1/1 · 9,160 |
| live-books-travel | ✅ 1/1 · 4,654 |
