"""Verification confusion matrix: every case in evals/bench/verification.py, on both engines, N runs each.

  .venv/bin/python scripts/verification_matrix.py            # 1 run per case per engine
  .venv/bin/python scripts/verification_matrix.py --runs 10  # repeated runs (release evidence)
  .venv/bin/python scripts/verification_matrix.py --json out.json

Exit code 1 if any run reports `verified` for an outcome that did not happen (false verified).
No LLM involved: the fixture pages decide whether the outcome happened.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import platform
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.bench.verification import CASES, CASES_EXPECT, classify, run_case, run_expect_case  # noqa: E402
from evals.fixtures.server import serve  # noqa: E402
from lean_browser import __version__  # noqa: E402
from lean_browser.engine import BrowserManager, find_obscura  # noqa: E402
from lean_browser.session import OBSCURA_DIALOG_SHIM, Session  # noqa: E402
from lean_browser.settle import SETTLE_INIT_JS  # noqa: E402


async def one(base: str, engine: str, c) -> tuple[str, float, str]:
    """c is an action case (7 fields) or an expect= case (8 fields)."""
    urllib.request.urlopen(base + "/api/reset").read()
    bm = BrowserManager(allow_private_network=True, prefer=engine, init_scripts=[SETTLE_INIT_JS],
                        obscura_init_scripts=[OBSCURA_DIALOG_SHIM])
    await bm.start()
    t = time.monotonic()
    try:
        status, out = await (run_expect_case if len(c) == 8 else run_case)(Session(bm), base, c)
    finally:
        await bm.close()
    return status, time.monotonic() - t, out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--engines", default="chromium,obscura")
    ap.add_argument("--json", help="write raw results here")
    a = ap.parse_args()
    engines = [e for e in a.engines.split(",") if e != "obscura" or find_obscura()]
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = serve(port)
    base = f"http://127.0.0.1:{port}"
    rows, matrix = [], collections.Counter()
    try:
        for engine in engines:
            for c in CASES + CASES_EXPECT:
                happened = c[6] if len(c) == 8 else c[5]
                for r in range(a.runs):
                    status, secs, out = await one(base, engine, c)
                    cls = classify(happened, status)
                    matrix[cls] += 1
                    rows.append({"case": c[0], "engine": engine, "run": r + 1, "happened": happened, "status": status,
                                 "class": cls, "seconds": round(secs, 2)})
                    if cls == "FALSE_VERIFIED":
                        print(f"FALSE VERIFIED  {engine:8} {c[0]}: {out.splitlines()[0] if out else ''}")
    finally:
        srv.shutdown()
    by_case = collections.defaultdict(collections.Counter)
    for r in rows:
        by_case[(r["case"], r["engine"])][r["status"]] += 1
    print(f"\nlean-agent-browser {__version__}, {platform.system()} {platform.machine()}, {a.runs} run(s) per case per engine\n")
    print(f"{'case':24} {'engine':9} {'happened':9} statuses")
    for (cid, eng), cnt in by_case.items():
        happened = next(r["happened"] for r in rows if r["case"] == cid)
        print(f"{cid:24} {eng:9} {str(happened):9} {dict(cnt)}")
    print("\nconfusion matrix:", dict(matrix))
    secs = sorted(r["seconds"] for r in rows)
    print(f"action time p50 {secs[len(secs) // 2]:.2f}s, p95 {secs[int(len(secs) * 0.95) - 1]:.2f}s over {len(rows)} runs")
    if a.json:
        Path(a.json).write_text(json.dumps({"version": __version__, "runs": a.runs, "matrix": matrix, "rows": rows}, indent=1))
    return 1 if matrix["FALSE_VERIFIED"] else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
