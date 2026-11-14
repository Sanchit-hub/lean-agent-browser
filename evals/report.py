"""Turn a results folder (runs.jsonl + meta.json) into a markdown report."""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def _fmt(n: float) -> str:
    return f"{n:,.0f}"


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
                  "| Mode | Success | Median total tokens | Mean total tokens | Mean steps | Mean time (s) | Tool schema tokens |",
                  "|---|---|---|---|---|---|---|"]
        for mode, xs in by_mode.items():
            tok = [x["weighted_input"] + x["output_tokens"] if cached else x["total_tokens"] for x in xs]
            succ = sum(x["success"] for x in xs)
            lines.append(f"| {mode} | {succ}/{len(xs)} ({100 * succ / len(xs):.0f}%) | {_fmt(statistics.median(tok))} | "
                         f"{_fmt(statistics.mean(tok))} | {statistics.mean(x['steps'] for x in xs):.1f} | "
                         f"{statistics.mean(x['wall_s'] for x in xs):.1f} | {meta.get('schema_tokens', {}).get(mode, '—')} |")
        lines.append("")

        tasks = list(dict.fromkeys(r["task"] for r in rs))
        modes = list(by_mode)
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
        lines += ["## Failures", "", "| Mode | Task | Run | Stop | Reason | Tool errors |", "|---|---|---|---|---|---|"]
        for r in fails:
            errs = "; ".join(r["errors"][:2]).replace("|", "/")
            lines.append(f"| {r['mode']} | {r['task']} | {r['run']} | {r['stop']} | {r['reason'][:90].replace('|', '/')} | {errs[:120]} |")
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
            "mean_turns": round(statistics.mean(r["steps"] for r in xs), 2),
            "mean_wall_s": round(statistics.mean(r["wall_s"] for r in xs), 2),
            "failures": [{"task": r["task"], "run": r["run"], "reason": r["reason"]} for r in xs if not r["success"]],
        }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    # Only a full run (all 18 tasks, >= 3 runs) replaces the committed evals/report.md;
    # quick or partial runs keep their report inside their own results folder.
    if len(meta["tasks"]) >= 18 and meta["runs"] >= 3:
        latest = out_dir.parent.parent / "report.md"
        latest.write_text("\n".join(lines))
        return latest
    return path


if __name__ == "__main__":
    print(write_report(Path(sys.argv[1])))
