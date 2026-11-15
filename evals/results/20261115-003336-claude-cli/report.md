# Eval report — 20261115-003336-claude-cli

Model `claude-sonnet-5-5 via claude -p`, effort `medium`, 18 tasks × 1 run(s). Success is verified by the fixture server.

## Summary — Prompt caching ON (cost-weighted input)

| Mode | Success | Median total tokens | Mean total tokens | Mean steps | Mean time (s) | Tool schema tokens |
|---|---|---|---|---|---|---|
| playwright-mcp | 17/18 (94%) | 9,577 | 10,609 | 7.4 | 18.9 | — |
| lean | 18/18 (100%) | 3,766 | 4,042 | 5.0 | 11.0 | — |

### Per task — Prompt caching ON (cost-weighted input)

| Task | playwright-mcp | lean |
|---|---|---|
| login | ✅ 1/1 · 6,805 | ✅ 1/1 · 2,779 |
| signup | ✅ 1/1 · 16,857 | ✅ 1/1 · 4,446 |
| wizard | ✅ 1/1 · 17,391 | ✅ 1/1 · 5,192 |
| apply | ❌ 0/1 · 10,498 | ✅ 1/1 · 4,413 |
| booking | ✅ 1/1 · 19,090 | ✅ 1/1 · 6,259 |
| newsletter | ✅ 1/1 · 8,602 | ✅ 1/1 · 4,050 |
| search | ✅ 1/1 · 10,100 | ✅ 1/1 · 4,516 |
| orders | ✅ 1/1 · 9,384 | ✅ 1/1 · 3,462 |
| feed | ✅ 1/1 · 7,164 | ✅ 1/1 · 4,865 |
| spa | ✅ 1/1 · 13,081 | ✅ 1/1 · 5,257 |
| files | ✅ 1/1 · 10,176 | ✅ 1/1 · 3,483 |
| todo | ✅ 1/1 · 8,906 | ✅ 1/1 · 2,624 |
| iframe | ✅ 1/1 · 8,512 | ✅ 1/1 · 3,007 |
| shadow | ✅ 1/1 · 8,848 | ✅ 1/1 · 3,320 |
| newtab | ✅ 1/1 · 12,040 | ✅ 1/1 · 3,306 |
| article | ✅ 1/1 · 5,046 | ✅ 1/1 · 5,954 |
| injection | ✅ 1/1 · 8,682 | ✅ 1/1 · 2,828 |
| editor | ✅ 1/1 · 9,771 | ✅ 1/1 · 3,001 |

## Failures

| Mode | Task | Run | Stop | Reason | Tool errors |
|---|---|---|---|---|---|
| playwright-mcp | apply | 1 | success | no submission | cost_usd=0.0299679 |
