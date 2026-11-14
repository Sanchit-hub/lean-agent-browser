"""Dev helper: print lean snapshots of fixture pages.  python scripts/snap.py login.html,apply.html [obscura|chromium] [mode]"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from evals.fixtures.server import serve  # noqa: E402
from lean_browser.engine import BrowserManager  # noqa: E402
from lean_browser.snapshot import Snapshotter  # noqa: E402
from tests.test_fixtures import _free_port  # noqa: E402


async def main():
    port = _free_port()
    srv = serve(port)
    base = f"http://127.0.0.1:{port}"
    pages = sys.argv[1].split(",")
    prefer = sys.argv[2] if len(sys.argv) > 2 else "obscura"
    mode = sys.argv[3] if len(sys.argv) > 3 else "actions"
    async with BrowserManager(allow_private_network=True, prefer=prefer) as bm:
        for p in pages:
            tab = await bm.open(p if p.startswith("http") else base + "/" + p)
            sn = Snapshotter()
            s = await sn.take(tab.page, mode=mode, engine=tab.header)
            print(f"===== {p} ({s.ms} ms)")
            print(sn.render(s))
    srv.shutdown()


asyncio.run(main())
