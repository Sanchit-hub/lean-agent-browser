# Eval report — 20261115-003259-claude-cli

Model `claude-sonnet-5-5 via claude -p`, effort `medium`, 1 tasks × 1 run(s). Success is verified by the fixture server.

## Summary — Prompt caching ON (cost-weighted input)

| Mode | Success | Median total tokens | Mean total tokens | Mean steps | Mean time (s) | Tool schema tokens |
|---|---|---|---|---|---|---|
| lean | 1/1 (100%) | 4,223 | 4,223 | 3.0 | 7.6 | — |
| playwright-mcp | 1/1 (100%) | 15,040 | 15,040 | 5.0 | 12.7 | — |

### Per task — Prompt caching ON (cost-weighted input)

| Task | lean | playwright-mcp |
|---|---|---|
| login | ✅ 1/1 · 4,223 | ✅ 1/1 · 15,040 |
