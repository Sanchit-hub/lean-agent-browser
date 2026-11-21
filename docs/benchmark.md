# Benchmark methodology

How the numbers in the README are produced, what they cover, and what they don't. Anyone with a
Claude subscription can rerun them on a Mac.

## What is measured

| Metric | How |
|---|---|
| Success | The fixture server records every submission. A run counts only if the server state matches the task (for read tasks, the final answer must contain the right value). The agent's own claim is never used. |
| Consistency | Tasks solved in **every** run, not just on average. |
| Tokens | Total tokens Claude processed for the task (input + cache + output), from `claude -p` usage. Tool-definition tokens are reported separately. |
| Turns, time | Model turns and wall-clock seconds per task; median and p95. Runs use `--jobs 5`, so times include some contention. |
| Failure category | `task_not_completed`, `wrong_answer`, `tool_error`, `timeout`, `step_limit`, `other` (`evals/report.py::failure_category`). |

## The suite: 100 fixture tasks

The original 20 tasks are in `evals/tasks.py`. The other 80 are in `evals/bench/`, one module per category.
Every task has a server-side verifier and a scripted Playwright reference solution. `tests/test_fixtures.py`
checks that each solution passes and that an empty run fails.

| Category | Tasks | What it exercises |
|---|---|---|
| Reading & extraction | 21 | filter a table then take the max, sum a column, date reasoning, hidden decoy prices, delayed content, ARIA tabs, accordions, nested config |
| Forms | 18 | fieldsets with repeated labels, radios, defaults to change, native date/time, range inputs, dependent selects, client and server validation |
| Widgets | 11 | autocomplete that only accepts a suggestion, ARIA listbox, keyboard slider, switches, steppers, tag input, calendar paging, reorder, contenteditable |
| Navigation & tabs | 11 | category drill-down, load-more, post chains, redirects, help-centre search, hash-routed SPA, broken link, values read in a new tab |
| Safety & honesty | 11 | one destructive action among look-alikes, injected instructions, impossible purchase, pay exactly once, transient 503, near-identical people, price change at checkout |
| Dialogs & overlays | 9 | `confirm()`, `prompt()`, `alert()`-only answers, modal forms, blocking popups, session-expiry modals, cookie banners |
| Dynamic pages | 7 | countdown-enabled buttons, infinite scroll, debounced live search, polling jobs, lists that re-render and reorder, self-re-rendering forms |
| Frames & shadow DOM | 6 | iframes, nested iframes, srcdoc iframes, shadow roots, nested shadow roots |
| Multi-step flows | 6 | four-page checkout, in-page wizard, seat map, returns, earliest free appointment, hash-routed tax form |

## Setup held equal across tools

- Same task definitions, start pages and verifiers.
- Same agent: Claude Sonnet 5.5 through `claude -p`, built-in tools disabled (`--tools ""`), only the
  browser MCP server under test loaded (`--strict-mcp-config`), the same system prompt for every tool.
- Same machine. Each parallel worker has its own fixture server, and each run starts from `/api/reset`.
- Integration mode: all three tools are compared **as MCP servers**. Vercel agent-browser is designed
  mainly as a CLI; we used its MCP `core` tool profile, which is labeled in every table.

## Results (2026-11-22, `main` after v0.8.0 and the real-site hardening)

Same 100 tasks, model, prompts and setup as the v0.4.0 baseline below; both tools rerun 3 times on the same day
(`evals/results/20261122-012443-claude-cli/`). Lean was at commit `6f60a47`; Playwright MCP is still 0.0.83.

| Tool | Runs | Success | Solved every run | Median tokens per task | Mean tokens per task | Tokens per successful task | p95 tokens | Mean turns | Median time |
|---|---|---|---|---|---|---|---|---|---|
| **Lean Agent Browser** | 3 | **300/300** ‡ | **100/100** ‡ | **13,505** | **15,841** | **15,841** ‡ | **30,534** | **5.1** | **11.7 s** |
| Playwright MCP 0.0.83 | 3 | 300/300 | 100/100 | 46,997 | 53,888 | 53,888 | 96,750 | 6.9 | 17.3 s |

‡ As run, Lean was 297/300 (16,001 tokens per successful task). All three failures were the benchmark's fault,
not Lean's. The runs shared one action-key store (`~/.lean-browser/action_keys.json`), so a `key` the agent picked
in run 1 (`giftcard-sneha-1000`, `brochure-tara`, `review-chai-1`) correctly blocked the same submit in run 3,
and the agent then answered "done". The driver now gives every run its own `LEANB_STATE_DIR`. The three tasks
were rerun 3× with that fix: 9/9 (`evals/results/20261122-015654-claude-cli/`). Both folders are published.

Browser tool calls (Lean, from its traces): 1,225 in 300 runs, 4.1 per task (v0.4.0: 1,218). Action statuses
across them: verified 562, unverified 49, blocked 26, done 20 (v0.4.0: 563, 53, 15, 19). Playwright MCP's tool
calls aren't recorded by this harness. Per-run medians: Lean 13,437 / 13,518 / 13,531; Playwright MCP 46,989 /
47,001 / 46,997.

**What changed since v0.4.0:**
- Success: the same (300/300 for both once the harness fix is applied).
- Lean's tokens went **up a little**, not down: median +2.5% (13,181 → 13,505), mean +3.6%, per-task median
  change +2.7%. The three new per-run medians all sit above the three old ones (13,158–13,378), so this is a
  small real increase, not noise. Likely causes: the tool schemas grew (~1.65k → ~1.76k tokens per request, measured with
  `claude -p`, for `key`, `dblclick` and the extract `url` hint) and results now carry more evidence. It is inside the 10%
  release gate.
- Turns, tool calls and time are unchanged (5.07 → 5.10 turns, 11.6 → 11.7 s median).
- Playwright MCP is unchanged too (median 46,946 → 46,997).
- Lean still used fewer tokens than Playwright MCP on **all 100 tasks**: per-task ratio 1.06× to 8.3×,
  median 3.75×; 3.5× on the overall median.

## Live suite: 51 real-site tasks (2026-11-22, reported separately)

`evals/live_tasks.py`: read-and-interact tasks on public pages, mostly sites built for automation practice
(books.toscrape.com, quotes.toscrape.com, the-internet.herokuapp.com, uitestingplayground.com, demoqa.com) plus
Wikipedia, GitHub, Hacker News, httpbin and TodoMVC. No logins, payments or real accounts. Success is judged
from the final answer against known values, one run each.

| Run | Lean | Playwright MCP |
|---|---|---|
| First runs, before the hardening fixes (32 + 19 tasks) | 47/51 † | 51/51 † |
| After the fixes (`evals/results/20261122-012035-claude-cli-live/`) | **51/51**, median 12,699 tokens, 4.1 turns | not rerun |

† One task (`live-quotes-scroll`) failed for both tools because our expected answer was wrong; it is counted
as passed here and the task is corrected. Lean's four real failures (TodoMVC, a TinyMCE editor, a double-click
and a hover-replaced link) and its two very expensive link tasks (121k and 188k tokens, now ~10k and ~12k) led
to the fixes in `CHANGELOG.md` (Unreleased). One run per task on live pages: treat it as a smoke test that found
bugs, not a measurement. Don't compare it with the fixture numbers.

## Results (2026-11-16, v0.4.0, the documented baseline)

| Tool | Runs | Success | Tasks solved every run | Median tokens per task | p95 tokens | Mean turns | Median time |
|---|---|---|---|---|---|---|---|
| **Lean Agent Browser** | 3 | **300/300** | **100/100** | **13,181** | **28,497** | **5.1** | **11.6 s** |
| Playwright MCP 0.0.83 | 3 | 300/300 * | 100/100 * | 46,946 | 101,198 | 6.9 | 18.1 s |
| Vercel agent-browser 0.41.0, MCP `core` profile † | 1 | 17/18 | — | 146,314 | 398,947 | 8.7 | 12.9 s |

\* As run, Playwright MCP was 297/300. All three failures were on `hidden-price`, where it reported a
"sale price" that the page had placed off-screen (`left:-9999px`). Screen readers read off-screen text, so
reporting it is a fair reading and the fixture was wrong to count it as a decoy. We replaced it with truly
hidden text (`display:none`, `visibility:hidden`, `[hidden]`) and reran that one task 3× for both tools: both
3/3. The table uses the corrected task. Both runs are published.

† agent-browser is from the earlier sequential run on the original 18 tasks (`evals/results/20261115-021309-claude-cli/`),
so it is not directly comparable with the 100-task rows. A 100-task agent-browser attempt on 2026-11-16 is not
reported: it ran 4 at a time, its runs took 3–5× more turns than the sequential runs of the same tasks (which
points to parallel agent-browser instances getting in each other's way), and it used up the Claude
subscription's 5-hour limit after 20 tasks, so the other 80 runs never browsed. The driver now refuses
`--jobs` > 1 for agent-browser and stops cleanly at a usage limit.

Lean used fewer tokens than Playwright MCP on **all 100 tasks**. The per-task ratio ranges from 1.4× to
8.3×, with a median of 3.9×.

| Category | Tasks | Lean median tokens | Playwright MCP median tokens | Ratio |
|---|---|---|---|---|
| Reading & extraction | 21 | 12,578 | 36,582 | 2.9× |
| Forms | 18 | 13,169 | 37,327 | 2.8× |
| Widgets | 11 | 16,756 | 70,531 | 4.2× |
| Navigation & tabs | 11 | 20,057 | 68,915 | 3.4× |
| Safety & honesty | 11 | 9,311 | 46,519 | 5.0× |
| Dialogs & overlays | 9 | 12,670 | 55,391 | 4.4× |
| Dynamic pages | 7 | 16,843 | 77,997 | 4.6× |
| Frames & shadow DOM | 6 | 9,393 | 46,606 | 5.0× |
| Multi-step flows | 6 | 25,845 | 91,647 | 3.5× |

### Rerun on v0.8.0

v0.7.0 and v0.8.0 tightened what counts as `verified` again (fresh `expect=` evidence, plain-text errors,
error routes, standing headings, timer-aware field and toast checks), so Lean was rerun once on all 100 tasks
(2026-11-20, `evals/results/20261120-032626-claude-cli/`): **100/100**, median 13,409 tokens, p95 30,202, 5.0
steps, 11.0 s. Against the v0.6.0 rerun (99/100, 13,110 / 28,356, 5.1 steps, 12.0 s) that is within single-run
noise. Action statuses across all 100 tasks barely moved (verified 185 vs 188, unverified 15 vs 15, blocked 5 vs
5), so the stricter rules did not make the agent see more honest successes as unverified. One run, our own
fixture tasks.

### Rerun after v0.6.0's verification changes

v0.6.0 changed what counts as `verified` (see `docs/RELIABILITY.md`), so Lean was rerun once on all 100 tasks
(2026-11-18, `evals/results/20261118-040843-claude-cli/`): **99/100**, median 13,110 tokens, p95 28,356, 5.1
turns, 11.3 s. That is in line with v0.4.0's 13,181 / 28,497. The one failure (`waitlist`) was a real bug in
checking ARIA checkboxes, which was fixed. That task was rerun 3/3 (`evals/results/20261118-041748-claude-cli/`).
Playwright MCP wasn't rerun: nothing on its side changed.

### What the pilot found

Before the full run, a 1-run pilot of the 80 new tasks scored Lean 74/80 and Playwright MCP 79/80. Lean's
six failures were real bugs, all fixed before the full run:

- After a list re-rendered in a new order, an id moved to another row's button. **Lean approved the wrong
  person's leave request.** Ids now follow the row they are in.
- Repeated buttons ("Approve", "Remove") didn't say which row they were in. They now do.
- Obscura reported every ARIA switch as off.
- Sliders couldn't be set, and `fill` claimed "value set" on a slider it never moved.
- Accordion buttons inside headings had no ids.
- Pages with srcdoc or nested iframes stayed on Obscura, which can't drive them.

## Raw data

| Run | Folder |
|---|---|
| `main` after hardening, Lean + Playwright MCP × 3, 100 tasks | `evals/results/20261122-012443-claude-cli/` |
| Its three key-collision tasks rerun with per-run state, Lean × 3 | `evals/results/20261122-015654-claude-cli/` |
| Live suite, 51 tasks, Lean, after the fixes | `evals/results/20261122-012035-claude-cli-live/` |
| Live suite first runs and reruns (before and during the fixes) | `evals/results/20261121-232833-claude-cli-live/`, `20261121-234655-…`, `20261122-000810-…`, `20261122-002129-…` |
| Full run, Lean + Playwright MCP × 3 | `evals/results/20261116-014739-claude-cli/` |
| `hidden-price` rerun after the fixture fix | `evals/results/20261116-021951-claude-cli/` |
| agent-browser × 1, 18 original tasks, sequential (reported) | `evals/results/20261115-021309-claude-cli/` |
| agent-browser 100-task attempt (invalid, not reported) | `evals/results/20261116-022027-claude-cli/` |
| v0.8.0 rerun, Lean × 1, 100 tasks | `evals/results/20261120-032626-claude-cli/` |
| v0.6.0 rerun, Lean × 1, 100 tasks | `evals/results/20261118-040843-claude-cli/` |
| v0.6.0 `waitlist` rerun after the ARIA checkbox fix, Lean × 3 | `evals/results/20261118-041748-claude-cli/` |
| Pilot (80 new tasks × 1) | `evals/results/20261116-012329-claude-cli/` |
| Pilot re-check of the fixed tasks (Lean) | `evals/results/20261116-014650-claude-cli/` |

Each folder has `runs.jsonl` (one line per task run: task, mode, success, reason, tokens, turns, time),
`summary.json`, `report.md` and `meta.json`. Transcripts and traces stay local because they hold full page text.

## Rerun it

```bash
./install.sh --with-eval                                            # also installs both baselines (Node.js 20+)
.venv/bin/python -m evals.claude_driver --runs 3 --jobs 5           # 100 tasks, Lean + Playwright MCP
.venv/bin/python -m evals.claude_driver --modes agent-browser     # sequential only; very token-heavy
.venv/bin/python -m evals.claude_driver --tags safety               # one category
.venv/bin/python -m evals.claude_driver --suite live                # live suite (reported separately)
```

Only a full run (all fixture tasks, 3+ runs) replaces `evals/report.md`.

## What this does and doesn't show

- **It does show** that on these 100 tasks, with this agent, Lean completed everything Playwright MCP did, with
  a bit over a quarter of the tokens and fewer turns: 3 runs each on 2026-11-16 (v0.4.0) and again on 2026-11-22
  (`main` after v0.8.0). Lean's own tokens rose about 2.5% between those runs.
- **It doesn't show** that Lean works on every website. We wrote every task ourselves, on a local fixture site
  built to cover common patterns. Real sites have bot checks, logins and layouts we didn't model.
- A read-only real-site canary (`scripts/canary.py`, weekly in `canary.yml`; see `docs/RELIABILITY.md`)
  checks that about 10 public pages still open and respond on both engines. It is a smoke check, not an
  agent benchmark, and no tokens are counted.
- Both tools reached 100%, so this suite no longer separates them on success. The 51-task live suite is a first
  step toward real sites; tasks written by other people and workflows with sandbox accounts are next (see
  `ROADMAP.md`).
- agent-browser has only the older 18-task, 1-run result. A valid 100-task run needs a sequential run and
  a lot of subscription usage (about 0.15–1M tokens per task).

## Rules for claims

- Quote success with its denominator (`300/300`, not "100%").
- Quote the run count next to each tool. With 3 runs, p95 is close to the maximum.
- Don't compare a fixture number with a live number.
- Re-measure tool-definition tokens with `claude -p` after any schema change. tiktoken undercounts
  Claude tokens by about 2.3×.
