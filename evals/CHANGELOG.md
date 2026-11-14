# Eval changelog

## 2026-11-15: first real-agent eval (lean vs Playwright MCP)

**Setup**
- **Agent:** Claude Sonnet 5.5 via the Claude Code CLI (`claude -p`, subscription login, no API key),
  run by `evals/claude_driver.py`. Built-in tools were disabled, only the browser MCP server under
  test was attached, and the system prompt was our own, identical for both modes.
- **Tasks:** the 18 fixture tasks × 2 modes × 3 runs = 108 runs. Success was checked by the fixture
  server.
- **Raw data:** `evals/results/20261115-004405-claude-cli/` (gitignored). That folder holds
  `runs.jsonl` and one JSON transcript per run.

**Result**

| | Success | Total tokens | Median tokens per task | Mean turns | Mean time | List-price cost |
|---|---|---|---|---|---|---|
| Playwright MCP 0.0.83 | **54/54** | 3,140,224 | 48,576 | 7.5 | 18.6 s | $1.36 |
| **Lean** | **54/54** | **705,150** | **11,572** | **5.1** | **11.0 s** | **$0.68** |

- **Same success rate, 4.5× fewer tokens** (lean used 22% of Playwright MCP's tokens). Per task,
  the saving ranged from 1.7× (`article`, a long read) to 7.0× (`todo`).
- **Pass bar met:** lean's success equals the best baseline (54/54 each), and its median tokens are
  24% of Playwright MCP's, against a target of ≤ 50%.
- **Cost is only 2× lower, not 4.5×.** Claude Code always uses prompt caching, and most of Playwright
  MCP's large context is cheap cache reads. Output tokens and per-turn overhead dominate what remains.
- **Lean was faster:** 1.7× less time per task and fewer turns (5.1 vs 7.5). `fill_form` and diffs
  removed whole round trips.
- **Variance was low** for both modes. Most tasks varied by less than 1% across the 3 runs. The
  widest spreads were lean on `article` (11.7k–17.5k) and `feed` (11.6k–18.9k), and Playwright MCP on
  `booking` (108k–121k).

**Harness fix during the run.** In the first single-run pass, Playwright MCP failed `apply` because,
by default, it only uploads files from its working folder, and the resume lived elsewhere. That was
a harness configuration problem, not a capability problem. The resume is now copied into the run's
working folder for **both** modes, with the same path in both prompts. After the fix, both modes
passed `apply` in all 3 runs.

**Not covered by this run**
- The screenshot, full-HTML and raw-aria baselines. They need the API runner (`leanb-eval`) and an
  account with API credits.
- The `lean-escalate` mode.
- Absolute token counts include `claude -p`'s small fixed overhead in both modes. They are not raw
  Messages API counts.
