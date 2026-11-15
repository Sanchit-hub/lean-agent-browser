# Eval changelog

## 2026-11-16 (v0.4.0): 100-task fixture suite

80 new tasks (`evals/bench/`) joined the original 20. Claude Sonnet 5.5 via `claude -p`, 3 runs per tool,
5 agents in parallel (each with its own fixture server).

| Mode | Success | Tasks solved every run | Median total tokens | p95 total tokens | Mean turns | Median time |
|---|---|---|---|---|---|---|
| **Lean** | **300/300** | **100/100** | **13,181** | **28,497** | **5.1** | **11.6 s** |
| Playwright MCP 0.0.83 | 300/300 (297/300 as run) | 100/100 | 46,946 | 101,198 | 6.9 | 18.1 s |
| Vercel agent-browser 0.41.0 (`core` profile) | 17/18, original 18 tasks, 1 run (2026-11-15) | — | 146,314 | 398,947 | 8.7 | 12.9 s |

- **The fixture correction.** Playwright MCP's three failures were all on `hidden-price`. It reported an
  off-screen "sale price" (`left:-9999px`), which screen readers also read, so the fixture was wrong to treat
  it as a hidden decoy. It now uses only truly hidden text. That task was rerun 3× for both tools: both 3/3.
  Raw data for both runs is published.
- **Tokens.** Lean used fewer tokens on all 100 tasks (per-task ratio 1.4× to 8.3×, median 3.9×). The original
  20 tasks alone: Lean 12,644 median, Playwright MCP 47,313.
- **Pilot.** A 1-run pilot of the 80 new tasks found six Lean bugs (Lean 74/80, Playwright MCP 79/80), all fixed
  before the full run. The worst: after a list re-rendered in a new order, Lean approved the wrong person's
  leave request. See `CHANGELOG.md` 0.4.0.
- **Invalid: the 100-task agent-browser attempt** (`20261116-022027-claude-cli/`). It ran 4 at a time. On the
  20 tasks it reached, its runs took 3–5× more turns than the sequential 2026-11-15 runs of the same tasks
  (login: 41 turns vs 7), which points to parallel agent-browser instances getting in each other's way. Then
  the Claude subscription hit its 5-hour limit, and the other 80 runs never browsed. None of it is reported.
  The driver now refuses `--jobs` > 1 for agent-browser and stops cleanly at a usage limit (`--resume` continues).
- **Limits.** We wrote every task, on a local site. Both tools reached 100%, so the suite no longer separates
  them on success. agent-browser only has the 18-task, 1-run result.

Raw data: `evals/results/20261116-014739-claude-cli/` (full run), `20261116-021951-claude-cli/`
(`hidden-price` rerun), `20261116-022027-claude-cli/` (invalid agent-browser attempt), `20261116-012329-claude-cli/` (pilot).

## 2026-11-15 (v0.3.0): reliability tasks

Two new fixture tasks test honest outcomes rather than raw capability:

- `order-once`: place exactly one order. The verifier fails a duplicate order.
- `honest-failure`: log in with a wrong password and report whether it worked. The verifier fails an
  agent that claims success.

They ran together with `signup` and `login`: 4 tasks × 3 runs, Claude Sonnet 5.5 via `claude -p`, on
v0.3 code (evidence-backed statuses and the duplicate guard).

| Mode | Success | Median total tokens | p95 total tokens | Median time |
|---|---|---|---|---|
| **Lean** | **12/12** | **9,114** | **17,056** | **9.2 s** |
| Playwright MCP 0.0.83 | 12/12 | 46,506 | 98,778 | 17.0 s |

No duplicate orders and no false success claims in either mode. This is a small sample (4 tasks), so
it shows the new behavior works with a real agent. It does not measure reliability in general. Raw data:
`evals/results/20261115-141019-claude-cli/`.

## 2026-11-15 (night): live-site suite

Five tasks on real public pages (Wikipedia ×2, a GitHub repo, example.com, httpbin's test form). Success
is judged from the final answer, because there is no fixture server. Each task ran once per mode.
**Live pages and networks vary, so treat these as a sanity check, not a benchmark.**

| Task | Playwright MCP tokens | Lean tokens |
|---|---|---|
| live-python-designer | 17,326 ✅ | 8,129 ✅ |
| live-halley | 25,761 ✅ | 8,183 ✅ * |
| live-obscura-license | 18,193 ✅ | 8,400 ✅ |
| live-example-link | 25,219 ✅ | 11,809 ✅ |
| live-httpbin-form | 48,079 ✅ | 12,856 ✅ |
| **Total** | **5/5, 134,578** | **5/5, 49,377 (2.7× fewer)** |

\* `live-halley` first **timed out on lean (900 s)**. That page leaves Obscura's script thread stuck
after load, and lean had no time limit on its page calls. Fixed in `367f395`: probes are time-boxed, the
page moves to Chromium, and the hung engine restarts. After the fix the task passed in 26 s.

A run before that one is **invalid**: the `leanb` script had been removed by mistake, so `claude -p`
ran without browsing tools and the agent answered from memory. The driver now refuses to start when an
MCP server binary is missing.

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
