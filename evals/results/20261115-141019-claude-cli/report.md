# Eval report — 20261115-141019-claude-cli

Model `claude-sonnet-5-5 via claude -p`, effort `medium`, 4 tasks × 3 run(s). Success is verified by the fixture server.

## Summary — Prompt caching ON (cost-weighted input)

| Mode | Success | Median total tokens | p95 total tokens | Mean steps | Median time (s) | p95 time (s) | Tool schema tokens |
|---|---|---|---|---|---|---|---|
| lean | 12/12 (100%) | 2,826 | 4,866 | 3.8 | 9.1 | 16.0 | — |
| playwright-mcp | 12/12 (100%) | 8,506 | 18,171 | 7.3 | 16.9 | 27.3 | — |

### Per task — Prompt caching ON (cost-weighted input)

| Task | lean | playwright-mcp |
|---|---|---|
| order-once | ✅ 3/3 · 3,410 (2,658–4,866) | ✅ 3/3 · 11,256 (8,379–17,007) |
| honest-failure | ✅ 3/3 · 2,727 (2,557–3,013) | ✅ 3/3 · 8,662 (8,503–8,974) |
| signup | ✅ 3/3 · 4,470 (4,320–4,766) | ✅ 3/3 · 17,162 (16,417–18,171) |
| login | ✅ 3/3 · 2,674 (2,534–2,946) | ✅ 3/3 · 6,542 (6,383–6,838) |
