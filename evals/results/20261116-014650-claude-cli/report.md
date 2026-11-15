# Eval report — 20261116-014650-claude-cli

Model `claude-sonnet-5-5 via claude -p`, effort `medium`, 9 tasks × 1 run(s). Success is verified by the fixture server.

## Summary — Prompt caching ON (cost-weighted input)

| Mode | Success | Median total tokens | p95 total tokens | Mean steps | Median time (s) | p95 time (s) | Tool schema tokens |
|---|---|---|---|---|---|---|---|
| lean | 9/9 (100%) | 3,449 | 3,952 | 3.9 | 10.3 | 11.7 | — |

### Per task — Prompt caching ON (cost-weighted input)

| Task | lean |
|---|---|
| rerender | ✅ 1/1 · 3,317 |
| nested-frame | ✅ 1/1 · 3,257 |
| srcdoc-poll | ✅ 1/1 · 3,722 |
| faq | ✅ 1/1 · 3,490 |
| slider | ✅ 1/1 · 3,449 |
| switches | ✅ 1/1 · 3,804 |
| returns | ✅ 1/1 · 3,952 |
| remove-one | ✅ 1/1 · 3,121 |
| same-name | ✅ 1/1 · 3,113 |
