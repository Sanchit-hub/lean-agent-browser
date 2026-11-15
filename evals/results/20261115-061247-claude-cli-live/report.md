# Eval report — 20261115-061247-claude-cli-live

Model `claude-sonnet-5-5 via claude -p`, effort `medium`, 5 tasks × 1 run(s). Success is verified by the fixture server.

## Summary — Prompt caching ON (cost-weighted input)

| Mode | Success | Median total tokens | Mean total tokens | Mean steps | Mean time (s) | Tool schema tokens |
|---|---|---|---|---|---|---|
| lean | 4/5 (80%) | 4,258 | 4,088 | 2.4 | 190.8 | — |

### Per task — Prompt caching ON (cost-weighted input)

| Task | lean |
|---|---|
| live-python-designer | ✅ 1/1 · 7,068 |
| live-halley | ❌ 0/1 · 0 |
| live-obscura-license | ✅ 1/1 · 5,744 |
| live-example-link | ✅ 1/1 · 3,371 |
| live-httpbin-form | ✅ 1/1 · 4,258 |

## Failures

| Mode | Task | Run | Stop | Reason | Tool errors |
|---|---|---|---|---|---|
| lean | live-halley | 1 | timeout | want 1986 | cost_usd=None |
