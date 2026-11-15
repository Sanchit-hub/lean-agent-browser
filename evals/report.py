"""Turn a results folder (runs.jsonl + meta.json) into a markdown report."""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


def _fmt(n: float) -> str:
    return f"{n:,.0f}"


def p95(xs) -> float:
    """Nearest-rank 95th percentile (with few runs this is close to the max; say so when reporting)."""
    xs = sorted(xs)
    return xs[max(0, -(-95 * len(xs) // 100) - 1)] if xs else 0


def failure_category(r: dict) -> str | None:
    """Why a run failed, so failures are counted by kind and not only as pass/fail."""
    if r["success"]:
        return None
    reason, stop = (r.get("reason") or "").lower(), (r.get("stop") or "").lower()
    if "timeout" in stop:
        return "timeout"
    if "max" in stop and ("step" in stop or "turn" in stop):
        return "step_limit"
    if any(e.startswith("Error") or "error" in e.lower() for e in r.get("errors", []) if not e.startswith("cost_usd")):
        return "tool_error"
    if "no submission" in reason or "not submitted" in reason:
        return "task_not_completed"
    if "answer" in reason or reason.startswith("want"):
        return "wrong_answer"
    return "other"


GROUPS = {"form": "forms", "multi-step": "multi-step flows", "extract": "reading & extraction", "read": "reading & extraction",
          "pagination": "reading & extraction", "scroll": "reading & extraction", "navigate": "navigation & tabs",
          "tabs": "navigation & tabs", "widget": "widgets", "custom-widget": "widgets", "contenteditable": "widgets",
          "dialog": "dialogs & overlays", "modal": "dialogs & overlays", "overlay": "dialogs & overlays",
          "banner": "dialogs & overlays", "iframe": "frames & shadow DOM", "shadow-dom": "frames & shadow DOM",
          "dynamic": "dynamic pages", "spa": "dynamic pages", "safety": "safety & honesty",
          "reliability": "safety & honesty", "security": "safety & honesty"}


def category_of(task_id: str) -> str:
    """The task's category, from its first tag in evals.tasks (forms, widgets, safety & honesty, ...)."""
    try:
        from evals.tasks import BY_ID
        t = BY_ID.get(task_id)
        return GROUPS.get(t.tags[0], t.tags[0]) if t and t.tags else "other"
    except Exception:
        return "other"


def _category_table(rs: list[dict], modes: list[str], tasks: list[str], title: str) -> list[str]:
    """Success by task category, plus pass^k: tasks solved in every run (consistency, not just luck)."""
    cats = defaultdict(list)
    for t in tasks:
        cats[category_of(t)].append(t)
    if len(cats) < 2:
        return []
    out = [f"### By category — {title}", "", "| Category | Tasks | " + " | ".join(f"{m} runs | {m} all runs" for m in modes) + " |",
           "|---|---|" + "---|---|" * len(modes)]
    for c in sorted(cats, key=lambda c: (-len(cats[c]), c)):
        cells = []
        for m in modes:
            xs = [r for r in rs if r["mode"] == m and r["task"] in cats[c]]
            solid = sum(all(r["success"] for r in xs if r["task"] == t) and any(r["task"] == t for r in xs) for t in cats[c])
            cells.append(f"{sum(r['success'] for r in xs)}/{len(xs)} | {solid}/{len(cats[c])}")
        out.append(f"| {c} | {len(cats[c])} | " + " | ".join(cells) + " |")
    return out + [""]


def write_report(out_dir: Path) -> Path:
    meta = json.loads((out_dir / "meta.json").read_text())
    runs = [json.loads(l) for l in (out_dir / "runs.jsonl").read_text().splitlines() if l.strip()]
    lines = [f"# Eval report — {out_dir.name}", "",
             f"Model `{meta['config']['model']}`, effort `{meta['config']['effort']}`, "
             f"{len(meta['tasks'])} tasks × {meta['runs']} run(s). Success is verified by the fixture server.", ""]

    for cached in sorted({r["cached"] for r in runs}):
        rs = [r for r in runs if r["cached"] == cached]
        by_mode = defaultdict(list)
        for r in rs:
            by_mode[r["mode"]].append(r)
        title = "Prompt caching ON (cost-weighted input)" if cached else "Raw tokens (prompt caching OFF)"
        lines += [f"## Summary — {title}", "",
                  "| Mode | Success | Median total tokens | p95 total tokens | Mean steps | Median time (s) | p95 time (s) | Tool schema tokens |",
                  "|---|---|---|---|---|---|---|---|"]
        for mode, xs in by_mode.items():
            tok = [x["weighted_input"] + x["output_tokens"] if cached else x["total_tokens"] for x in xs]
            succ = sum(x["success"] for x in xs)
            wall = [x["wall_s"] for x in xs]
            lines.append(f"| {mode} | {succ}/{len(xs)} ({100 * succ / len(xs):.0f}%) | {_fmt(statistics.median(tok))} | "
                         f"{_fmt(p95(tok))} | {statistics.mean(x['steps'] for x in xs):.1f} | "
                         f"{statistics.median(wall):.1f} | {p95(wall):.1f} | {meta.get('schema_tokens', {}).get(mode, '—')} |")
        lines.append("")

        tasks = list(dict.fromkeys(r["task"] for r in rs))
        modes = list(by_mode)
        lines += _category_table(rs, modes, tasks, title)
        lines += [f"### Per task — {title}", "", "| Task | " + " | ".join(modes) + " |",
                  "|---|" + "---|" * len(modes)]
        for t in tasks:
            cells = []
            for m in modes:
                xs = [r for r in rs if r["task"] == t and r["mode"] == m]
                if not xs:
                    cells.append("—")
                    continue
                tok = [x["weighted_input"] + x["output_tokens"] if cached else x["total_tokens"] for x in xs]
                s = sum(x["success"] for x in xs)
                rng = f" ({_fmt(min(tok))}–{_fmt(max(tok))})" if len(tok) > 1 else ""
                cells.append(f"{'✅' if s == len(xs) else ('⚠️' if s else '❌')} {s}/{len(xs)} · {_fmt(statistics.mean(tok))}{rng}")
            lines.append(f"| {t} | " + " | ".join(cells) + " |")
        lines.append("")

    fails = [r for r in runs if not r["success"]]
    if fails:
        lines += ["## Failures", "", "| Mode | Task | Run | Category | Stop | Reason | Tool errors |", "|---|---|---|---|---|---|---|"]
        for r in fails:
            errs = "; ".join(r["errors"][:2]).replace("|", "/")
            lines.append(f"| {r['mode']} | {r['task']} | {r['run']} | {failure_category(r)} | {r['stop']} | "
                         f"{r['reason'][:90].replace('|', '/')} | {errs[:120]} |")
        lines.append("")

    path = out_dir / "report.md"
    path.write_text("\n".join(lines))
    # machine-readable summary for leanb bench consumers
    summary = {"run": out_dir.name, "model": meta["config"]["model"], "tasks": meta["tasks"], "runs": meta["runs"], "modes": {}}
    for mode in dict.fromkeys(r["mode"] for r in runs):
        xs = [r for r in runs if r["mode"] == mode]
        summary["modes"][mode] = {
            "success": sum(r["success"] for r in xs), "attempts": len(xs),
            "median_total_tokens": statistics.median(r["total_tokens"] for r in xs),
            "p95_total_tokens": p95([r["total_tokens"] for r in xs]),
            "median_wall_s": round(statistics.median(r["wall_s"] for r in xs), 2),
            "p95_wall_s": round(p95([r["wall_s"] for r in xs]), 2),
            "failure_categories": dict(Counter(failure_category(r) for r in xs if not r["success"])),
            "tasks_solved_every_run": sum(all(r["success"] for r in xs if r["task"] == t)
                                          for t in dict.fromkeys(r["task"] for r in xs)),
            "mean_turns": round(statistics.mean(r["steps"] for r in xs), 2),
            "mean_wall_s": round(statistics.mean(r["wall_s"] for r in xs), 2),
            "failures": [{"task": r["task"], "run": r["run"], "category": failure_category(r), "reason": r["reason"]}
                         for r in xs if not r["success"]],
        }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    # Only a full run (all fixture tasks, >= 3 runs) replaces the committed evals/report.md;
    # quick or partial runs keep their report inside their own results folder.
    from evals.tasks import TASKS
    if len(meta["tasks"]) >= len(TASKS) and meta["runs"] >= 3:
        latest = out_dir.parent.parent / "report.md"
        latest.write_text("\n".join(lines))
        return latest
    return path


if __name__ == "__main__":
    print(write_report(Path(sys.argv[1])))
