# Eval report — 20261115-020227-claude-cli

Model `claude-sonnet-5-5 via claude -p`, effort `medium`, 6 tasks × 1 run(s). Success is verified by the fixture server.

## Summary — Prompt caching ON (cost-weighted input)

| Mode | Success | Median total tokens | Mean total tokens | Mean steps | Mean time (s) | Tool schema tokens |
|---|---|---|---|---|---|---|
| playwright-mcp | 6/6 (100%) | 10,123 | 11,527 | 8.0 | 20.1 | — |
| lean | 6/6 (100%) | 4,710 | 4,619 | 5.5 | 11.6 | — |

### Per task — Prompt caching ON (cost-weighted input)

| Task | playwright-mcp | lean |
|---|---|---|
| login | ✅ 1/1 · 6,869 | ✅ 1/1 · 4,404 |
| apply | ✅ 1/1 · 11,549 | ✅ 1/1 · 5,335 |
| booking | ✅ 1/1 · 20,255 | ✅ 1/1 · 6,441 |
| spa | ✅ 1/1 · 13,144 | ✅ 1/1 · 5,016 |
| orders | ✅ 1/1 · 8,697 | ✅ 1/1 · 3,584 |
| injection | ✅ 1/1 · 8,651 | ✅ 1/1 · 2,933 |
