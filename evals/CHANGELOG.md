# Eval changelog

## 2026-11-15 (later): Vercel agent-browser added as a baseline

Same harness as below: `claude -p`, Claude Sonnet 5.5, our system prompt, only the MCP server under
test attached, server-verified success. agent-browser 0.41.0 ran through `agent-browser mcp` with its
default `core` tool profile, on the same Chrome for Testing build as the other modes. It ran **1 time
per task** (18 runs), because each run costs about 5× a lean run. The other two rows are the 3-run
results from the entry below.

| | Success | Median tokens per task | Mean turns | Mean time | Mean list-price cost per task |
|---|---|---|---|---|---|
| Playwright MCP 0.0.83 (3 runs) | 54/54 | 48,576 | 7.5 | 18.6 s | $0.025 |
| agent-browser 0.41.0 (1 run) | 17/18 | 146,314 | 8.7 | 16.1 s | $0.062 |
| **Lean (3 runs)** | **54/54** | **11,572** | **5.1** | **11.0 s** | **$0.013** |

- **Why agent-browser uses so many tokens:** its default `core` profile exposes 29 tools whose definitions
  Claude counts at **~31,600 tokens**, against ~7,100 for Playwright MCP and **~1,550 for lean's 7 tools**.
  These were measured with `claude -p` as the input-token difference against a run with no MCP server.
  Those definitions go with every request. The page snapshots themselves are compact.
- **The one failure (`apply`) is a configuration limit, not a harness bug.** The `core` profile has no
  file-upload tool, so the agent filled the form but couldn't attach the resume. `--tools all` adds
  uploads, with an even larger schema.
- **Fairness notes:**
  - agent-browser is designed mainly as a CLI driven through shell commands plus a skill. MCP is one of
    its supported modes, not its main one.
  - n=1 here.
- **Raw data:** `evals/results/20261115-021309-claude-cli/` (gitignored).

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
