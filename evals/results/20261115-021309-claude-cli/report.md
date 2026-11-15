# Eval report — 20261115-021309-claude-cli

Model `claude-sonnet-5-5 via claude -p`, effort `medium`, 18 tasks × 1 run(s). Success is verified by the fixture server.

## Summary — Prompt caching ON (cost-weighted input)

| Mode | Success | Median total tokens | Mean total tokens | Mean steps | Mean time (s) | Tool schema tokens |
|---|---|---|---|---|---|---|
| agent-browser | 17/18 (94%) | 24,714 | 29,850 | 8.7 | 16.1 | — |

### Per task — Prompt caching ON (cost-weighted input)

| Task | agent-browser |
|---|---|
| login | ✅ 1/1 · 23,064 |
| signup | ✅ 1/1 · 36,806 |
| wizard | ✅ 1/1 · 39,518 |
| apply | ❌ 0/1 · 31,095 |
| booking | ✅ 1/1 · 62,769 |
| newsletter | ✅ 1/1 · 24,534 |
| search | ✅ 1/1 · 30,242 |
| orders | ✅ 1/1 · 32,714 |
| feed | ✅ 1/1 · 17,502 |
| spa | ✅ 1/1 · 22,804 |
| files | ✅ 1/1 · 27,884 |
| todo | ✅ 1/1 · 50,619 |
| iframe | ✅ 1/1 · 24,398 |
| shadow | ✅ 1/1 · 24,746 |
| newtab | ✅ 1/1 · 24,683 |
| article | ✅ 1/1 · 20,701 |
| injection | ✅ 1/1 · 24,182 |
| editor | ✅ 1/1 · 19,037 |

## Failures

| Mode | Task | Run | Stop | Reason | Tool errors |
|---|---|---|---|---|---|
| agent-browser | apply | 1 | success | no submission | cost_usd=0.0680222 |
