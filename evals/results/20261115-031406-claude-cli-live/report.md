# Eval report — 20261115-031406-claude-cli-live

Model `claude-sonnet-5-5 via claude -p`, effort `medium`, 5 tasks × 1 run(s). Success is verified by the fixture server.

## Summary — Prompt caching ON (cost-weighted input)

| Mode | Success | Median total tokens | Mean total tokens | Mean steps | Mean time (s) | Tool schema tokens |
|---|---|---|---|---|---|---|
| lean | 0/5 (0%) | 0 | 0 | 1.0 | 5.0 | — |

### Per task — Prompt caching ON (cost-weighted input)

| Task | lean |
|---|---|
| live-python-designer | ❌ 0/1 · 0 |
| live-halley | ❌ 0/1 · 0 |
| live-obscura-license | ❌ 0/1 · 0 |
| live-example-link | ❌ 0/1 · 0 |
| live-httpbin-form | ❌ 0/1 · 0 |

## Failures

| Mode | Task | Run | Stop | Reason | Tool errors |
|---|---|---|---|---|---|
| lean | live-python-designer | 1 | success | answer missing ['guido van rossum'] | cost_usd=0 |
| lean | live-halley | 1 | success | want 1986 | cost_usd=0 |
| lean | live-obscura-license | 1 | success | answer missing ['apache'] | cost_usd=0 |
| lean | live-example-link | 1 | success | answer missing ['iana'] | cost_usd=0 |
| lean | live-httpbin-form | 1 | success | answer missing ['lean tester'] | cost_usd=0 |
