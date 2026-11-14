"""Dev helper: snapshot timing breakdown on a fixture page.  python scripts/snap_prof.py big.html [obscura|chromium]"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from evals.fixtures.server import serve  # noqa: E402
from lean_browser.engine import BrowserManager  # noqa: E402
from lean_browser.snapshot import SNAPSHOT_JS  # noqa: E402
from tests.test_fixtures import _free_port  # noqa: E402


async def main():
    port = _free_port()
    srv = serve(port)
    async with BrowserManager(allow_private_network=True, prefer=sys.argv[2] if len(sys.argv) > 2 else "obscura") as bm:
        tab = await bm.open(f"http://127.0.0.1:{port}/{sys.argv[1]}")
        d = await tab.page.evaluate(SNAPSHOT_JS, {"mode": "actions"})
        print(tab.engine, d["ms"], d.get("prof"))
    srv.shutdown()


asyncio.run(main())
