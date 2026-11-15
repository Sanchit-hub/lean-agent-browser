#!/usr/bin/env bash
# Clean-install smoke test (release validation, also run in CI):
#   1. build the wheel from this checkout,
#   2. install it into a brand-new venv (no repo on the path, no dev extras),
#   3. leanb install (pinned Obscura + Chromium; skips pieces already verified in ~/.lean-browser),
#   4. leanb doctor,
#   5. the documented MCP client config: start `leanb mcp`, list tools, open a local page, act on it.
# macOS arm64 only.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$("${PYTHON:-python3}" -c "import sys; print(sys.executable)")"
WORK="$(mktemp -d)"
trap '[ -n "${SRV:-}" ] && kill "$SRV" 2>/dev/null; rm -rf "$WORK"' EXIT

echo "==> building wheel"
"$PY" -m pip wheel --quiet --no-deps -w "$WORK/dist" "$ROOT"
WHEEL="$(ls "$WORK"/dist/lean_agent_browser-*.whl)"

echo "==> fresh venv + pip install $(basename "$WHEEL")"
"$PY" -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install --quiet "$WHEEL"

cd "$WORK"   # nothing from the checkout is importable from here
echo "==> leanb install"
"$WORK/venv/bin/leanb" install
echo "==> leanb doctor"
"$WORK/venv/bin/leanb" doctor | tee "$WORK/doctor.txt"
grep -q "all good" "$WORK/doctor.txt"

echo "==> MCP round trip"
PORT=$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
"$PY" -I "$ROOT/evals/fixtures/server.py" "$PORT" >/dev/null 2>&1 &
SRV=$!
for _ in $(seq 1 60); do curl -fs "http://127.0.0.1:$PORT/api/state" >/dev/null && break; sleep 0.5; done
curl -fs "http://127.0.0.1:$PORT/api/state" >/dev/null || { echo "fixture server did not start"; exit 1; }
"$WORK/venv/bin/python" -I - "$WORK/venv/bin/leanb" "http://127.0.0.1:$PORT" <<'PYEOF'
import asyncio, re, sys
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

leanb, base = sys.argv[1], sys.argv[2]

async def main():
    params = StdioServerParameters(command=leanb, args=["--allow-private-network", "mcp"])
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        names = sorted(t.name for t in (await s.list_tools()).tools)
        assert names == ["act", "extract", "fill_form", "memory", "open", "screenshot", "snapshot"], names
        out = (await s.call_tool("open", {"url": base + "/order.html"})).content[0].text
        m = re.search(r'(\d+): button "Place order"', out)
        assert m, "open() did not return the order page:\n" + out
        place = int(m.group(1))
        prev = (await s.call_tool("act", {"action": "click", "id": place, "dry_run": True})).content[0].text
        assert '"executed": false' in prev, prev
        res = (await s.call_tool("act", {"action": "click", "id": place})).content[0].text
        assert "status: verified" in res, res
        print("mcp: 7 tools, open + dry_run + verified click OK")

asyncio.run(main())
PYEOF
echo "clean install smoke test passed"
