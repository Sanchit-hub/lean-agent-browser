# Eval report — 20261122-002129-claude-cli-live

Model `claude-sonnet-5-5 via claude -p`, effort `medium`, 4 tasks × 1 run(s). Success is verified by the fixture server.

## Summary — Prompt caching ON (cost-weighted input)

| Mode | Success | Median total tokens | p95 total tokens | Mean steps | Median time (s) | p95 time (s) | Tool schema tokens |
|---|---|---|---|---|---|---|---|
| lean | 4/4 (100%) | 5,111 | 9,659 | 6.2 | 20.6 | 25.0 | — |

### Per task — Prompt caching ON (cost-weighted input)

| Task | lean |
|---|---|
| live-dq-doubleclick | ✅ 1/1 · 4,873 |
| live-utp-mouseover | ✅ 1/1 · 5,349 |
| live-dq-slider | ✅ 1/1 · 4,807 |
| live-todomvc | ✅ 1/1 · 9,659 |
