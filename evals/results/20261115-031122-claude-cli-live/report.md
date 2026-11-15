# Eval report — 20261115-031122-claude-cli-live

Model `claude-sonnet-5-5 via claude -p`, effort `medium`, 5 tasks × 1 run(s). Success is verified by the fixture server.

## Summary — Prompt caching ON (cost-weighted input)

| Mode | Success | Median total tokens | Mean total tokens | Mean steps | Mean time (s) | Tool schema tokens |
|---|---|---|---|---|---|---|
| playwright-mcp | 5/5 (100%) | 5,075 | 7,619 | 4.2 | 14.8 | — |
| lean | 3/5 (60%) | 1,554 | 1,569 | 1.0 | 9.5 | — |

### Per task — Prompt caching ON (cost-weighted input)

| Task | playwright-mcp | lean |
|---|---|---|
| live-python-designer | ✅ 1/1 · 4,095 | ✅ 1/1 · 1,537 |
| live-halley | ✅ 1/1 · 14,520 | ✅ 1/1 · 1,532 |
| live-obscura-license | ✅ 1/1 · 5,075 | ❌ 0/1 · 1,554 |
| live-example-link | ✅ 1/1 · 4,276 | ✅ 1/1 · 1,612 |
| live-httpbin-form | ✅ 1/1 · 10,130 | ❌ 0/1 · 1,608 |

## Failures

| Mode | Task | Run | Stop | Reason | Tool errors |
|---|---|---|---|---|---|
| lean | live-obscura-license | 1 | success | answer missing ['apache'] | cost_usd=0.006366 |
| lean | live-httpbin-form | 1 | success | answer missing ['lean tester'] | cost_usd=0.006612 |
