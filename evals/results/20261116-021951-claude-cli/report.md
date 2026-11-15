# Eval report — 20261116-021951-claude-cli

Model `claude-sonnet-5-5 via claude -p`, effort `medium`, 1 tasks × 3 run(s). Success is verified by the fixture server.

## Summary — Prompt caching ON (cost-weighted input)

| Mode | Success | Median total tokens | p95 total tokens | Mean steps | Median time (s) | p95 time (s) | Tool schema tokens |
|---|---|---|---|---|---|---|---|
| lean | 3/3 (100%) | 2,847 | 2,847 | 3.0 | 10.6 | 10.6 | — |
| playwright-mcp | 3/3 (100%) | 5,127 | 5,130 | 3.0 | 11.4 | 11.6 | — |

### Per task — Prompt caching ON (cost-weighted input)

| Task | lean | playwright-mcp |
|---|---|---|
| hidden-price | ✅ 3/3 · 2,760 (2,587–2,847) | ✅ 3/3 · 4,974 (4,665–5,130) |
