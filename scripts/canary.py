"""Real-site canary: about 10 stable public pages, read-only, through the Python API with default settings.

  .venv/bin/python scripts/canary.py                       # both engines (Obscura only if installed)
  .venv/bin/python scripts/canary.py --engines obscura     # one engine
  .venv/bin/python scripts/canary.py --json out.json --max-failures 2

Fixture results don't prove real sites work; this does, a little. For each site it opens the page, checks
the snapshot has a stable string (title or heading), then runs one harmless read-only action: a
snapshot(find=...), a wait_for on known text, or a click on a same-site link followed by a check that the
page changed. It never types into a field, submits a form or logs in. The private network stays blocked.

Real sites change and flake, so the exit code is 1 only when more than --max-failures sites fail on any
one engine. Each row records the engine that served the page, the fallback reason if Obscura handed the
page to Chromium, the seconds taken and pass/fail.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import platform
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lean_browser import __version__  # noqa: E402
from lean_browser.engine import find_obscura  # noqa: E402
from lean_browser.tools import Config, LeanBrowser  # noqa: E402

# (id, url, text the first snapshot must contain, action)
# action: ("find", query, text the result must contain)
#         ("wait_for", text)
#         ("click", link name, text the new page must contain)   same-site link, read-only navigation
SITES = [
    ("example", "https://example.com/", "Example Domain", ("find", "Learn more", "Learn more")),
    ("wikipedia", "https://en.wikipedia.org/wiki/Web_browser", "Web browser", ("wait_for", "World Wide Web")),
    ("python", "https://www.python.org/", "Python", ("find", "Downloads", "Downloads")),
    ("python-docs", "https://docs.python.org/3/", "documentation", ("click", "Tutorial", "Python Tutorial")),
    ("mdn", "https://developer.mozilla.org/en-US/", "MDN", ("wait_for", "Web")),
    ("hackernews", "https://news.ycombinator.com/", "Hacker News", ("click", "new", "New Links")),
    ("github", "https://github.com/microsoft/playwright", "playwright", ("wait_for", "README")),
    ("rust", "https://www.rust-lang.org/", "Rust", ("find", "Install", "Install")),
    ("httpbin", "https://httpbin.org/html", "Herman Melville", ("wait_for", "Moby-Dick")),
    ("iana", "https://www.iana.org/domains/reserved", "Reserved Domains", ("find", "example", "example")),
]

PER_SITE_TIMEOUT_S = 90


def _link_id(snapshot: str, name: str) -> int | None:
    """Id of the first link whose accessible name is `name` (exact, case-insensitive), else the first that
    starts with it."""
    links = re.findall(r'^\s*(\d+): link "([^"]*)"', snapshot, re.M)
    for i, n in links:
        if n.strip().lower() == name.lower():
            return int(i)
    for i, n in links:
        if n.strip().lower().startswith(name.lower()):
            return int(i)
    return None


async def check_site(b: LeanBrowser, url: str, expect: str, action: tuple) -> str:
    """Raises AssertionError (or LeanBrowserError) with a short reason on failure; returns a note on success."""
    snap = await b.open(url)
    if expect.lower() not in snap.lower():
        raise AssertionError(f"first snapshot lacks {expect!r}: {snap.splitlines()[0] if snap else ''}")
    kind = action[0]
    if kind == "find":
        out = await b.snapshot(find=action[1])
        if action[2].lower() not in out.lower():
            raise AssertionError(f"find({action[1]!r}) lacks {action[2]!r}")
        return f"find {action[1]!r}"
    if kind == "wait_for":
        out = await b.act("wait_for", value=action[1])
        return out.splitlines()[0]
    if kind == "click":
        i = _link_id(snap, action[1])  # ids from the open() snapshot; a repeat snapshot only lists changes
        if i is None:
            raise AssertionError(f"no link named {action[1]!r}")
        before = b.session.cur.page.url
        out = await b.act("click", i)
        after = b.session.cur.page.url
        page = await b.snapshot(mode="full")
        if after == before:
            raise AssertionError(f"click {action[1]!r} did not change the URL ({out.splitlines()[0]})")
        if action[2].lower() not in page.lower():
            raise AssertionError(f"after click, page lacks {action[2]!r}")
        return f"click {action[1]!r} -> {after}"
    raise ValueError(kind)


async def one(engine: str, site: tuple) -> dict:
    sid, url, expect, action = site
    t = time.monotonic()
    row = {"site": sid, "url": url, "requested": engine, "engine": None, "fallback": "", "ok": False, "note": ""}
    try:
        async with LeanBrowser(Config(prefer=engine, allow_private_network=False)) as b:
            try:
                row["note"] = await asyncio.wait_for(check_site(b, url, expect, action), PER_SITE_TIMEOUT_S)
                row["ok"] = True
            except asyncio.TimeoutError:
                row["note"] = f"timed out after {PER_SITE_TIMEOUT_S}s"
            except Exception as e:  # real sites fail in many ways; record and move on
                row["note"] = f"{type(e).__name__}: {str(e).splitlines()[0][:160] if str(e) else ''}"
            if b.session.active >= 0:
                row["engine"] = b.session.cur.tab.engine
                row["fallback"] = b.session.cur.tab.reason
    except Exception as e:
        row["note"] = f"browser failed: {type(e).__name__}: {str(e)[:160]}"
    row["seconds"] = round(time.monotonic() - t, 2)
    return row


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--engines", default="obscura,chromium",
                    help="comma-separated preferred engines (obscura is skipped if not installed)")
    ap.add_argument("--max-failures", type=int, default=2, help="exit 1 if more sites than this fail on any engine")
    ap.add_argument("--sites", help="comma-separated site ids to run (default: all)")
    ap.add_argument("--json", help="write results here")
    a = ap.parse_args()
    engines = [e for e in a.engines.split(",") if e and (e != "obscura" or find_obscura())]
    sites = [s for s in SITES if not a.sites or s[0] in a.sites.split(",")]
    rows = []
    for engine in engines:
        for site in sites:
            r = await one(engine, site)
            rows.append(r)
            print(f"{'PASS' if r['ok'] else 'FAIL'}  {engine:8} {r['site']:12} {r['seconds']:6.2f}s", flush=True)

    print(f"\nlean-agent-browser {__version__}, {platform.system()} {platform.machine()}\n")
    print(f"{'site':12} {'requested':9} {'engine':9} {'result':6} {'secs':>6}  fallback / note")
    for r in rows:
        extra = (f"[{r['fallback']}] " if r["fallback"] else "") + r["note"]
        print(f"{r['site']:12} {r['requested']:9} {str(r['engine']):9} {'pass' if r['ok'] else 'FAIL':6} "
              f"{r['seconds']:6.2f}  {extra[:110]}")
    failures = {e: sum(1 for r in rows if r["requested"] == e and not r["ok"]) for e in engines}
    print("\nfailures per engine:", failures, f"(allowed: {a.max_failures})")
    if a.json:
        Path(a.json).write_text(json.dumps({"version": __version__, "platform": f"{platform.system()} {platform.machine()}",
                                            "max_failures": a.max_failures, "failures": failures, "rows": rows},
                                           indent=1))
    return 1 if not engines or any(n > a.max_failures for n in failures.values()) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
