#!/usr/bin/env bash
# Clean-install smoke test (release validation, also run in CI):
#   1. build the wheel from this checkout,
#   2. check what the wheel contains (JS assets in, no top-level evals package),
#   3. install it into a brand-new venv whose path contains a space (no repo on the path, no dev extras),
#   4. leanb --version, leanb setup --yes (pinned Obscura + Chromium; skips pieces already verified),
#   5. leanb doctor (engines, sandbox, MCP round trip) and doctor --json,
#   6. the documented MCP client config: start `leanb mcp`, list tools, open a local page, act on it,
#   7. if pipx is available: pipx install the same wheel and run leanb doctor from it,
#   8. if LEANB_UPGRADE_FROM is set (a tag, e.g. v0.5.0): install that release with pipx, then upgrade it to
#      this wheel, and check the version changed, the config was kept and doctor still passes.
# macOS arm64 and Linux (x86_64, arm64).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$("${PYTHON:-python3}" -c "import sys; print(sys.executable)")"
WORK="$(mktemp -d)"
trap '[ -n "${SRV:-}" ] && kill "$SRV" 2>/dev/null; rm -rf "$WORK"' EXIT

if [ -n "${WHEEL:-}" ]; then
  echo "==> testing the given wheel $WHEEL"   # release workflow: test the exact artifact that gets published
else
  rm -rf "$ROOT/build"   # a stale setuptools build dir would leak old files into the wheel
  echo "==> building wheel"
  "$PY" -m pip wheel --quiet --no-deps -w "$WORK/dist" "$ROOT"
  WHEEL="$(ls "$WORK"/dist/lean_agent_browser-*.whl)"
fi

echo "==> wheel contents"
"$PY" - "$WHEEL" <<'PYEOF'
import sys, zipfile
names = zipfile.ZipFile(sys.argv[1]).namelist()
for need in ("lean_browser/snapshot.js", "lean_browser/extract.js", "lean_browser/blocklist.txt", "lean_browser/cli.py"):
    assert need in names, f"{need} missing from the wheel"
bad = [n for n in names if n.startswith(("evals/", "tests/", "spike/"))]
assert not bad, f"wheel ships non-package folders: {bad[:5]}"
print(f"wheel OK: {len(names)} files")
PYEOF

VENV="$WORK/clean venv"   # a space in the path, as in many home folders
echo "==> fresh venv + pip install $(basename "$WHEEL")"
"$PY" -m venv "$VENV"
"$VENV/bin/pip" install --quiet "$WHEEL"
LEANB="$VENV/bin/leanb"

cd "$WORK"   # nothing from the checkout is importable from here
echo "==> leanb --version"
"$LEANB" --version | grep -q "^leanb [0-9]"
echo "==> leanb setup --yes --client none"
"$LEANB" setup --yes --client none
echo "==> leanb doctor"
"$LEANB" doctor --no-claude | tee "$WORK/doctor.txt"
grep -q "all good" "$WORK/doctor.txt"
"$LEANB" doctor --no-claude --no-mcp --json | "$PY" -c 'import json,sys; d=json.load(sys.stdin); assert d["ok"] and d["install"] == "pip", d; print("doctor --json OK")'

echo "==> MCP round trip"
PORT=$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
"$PY" -I "$ROOT/evals/fixtures/server.py" "$PORT" >/dev/null 2>&1 &
SRV=$!
for _ in $(seq 1 60); do curl -fs "http://127.0.0.1:$PORT/api/state" >/dev/null && break; sleep 0.5; done
curl -fs "http://127.0.0.1:$PORT/api/state" >/dev/null || { echo "fixture server did not start"; exit 1; }
curl -fs "http://127.0.0.1:$PORT/b/faq.html" >/dev/null || { echo "fixture server cannot serve benchmark pages"; exit 1; }
"$VENV/bin/python" -I - "$LEANB" "http://127.0.0.1:$PORT" <<'PYEOF'
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
if command -v pipx >/dev/null; then
  echo "==> pipx install $(basename "$WHEEL")"
  export PIPX_HOME="$WORK/pipx" PIPX_BIN_DIR="$WORK/pipx-bin"
  pipx install --python "$PY" "$WHEEL" >/dev/null
  "$PIPX_BIN_DIR/leanb" --version
  "$PIPX_BIN_DIR/leanb" doctor --no-claude | tee "$WORK/doctor-pipx.txt"
  grep -q "all good" "$WORK/doctor-pipx.txt"
  grep -q "(pipx)" "$WORK/doctor-pipx.txt"
  if [ -n "${LEANB_UPGRADE_FROM:-}" ]; then
    echo "==> upgrade: pipx install $LEANB_UPGRADE_FROM from GitHub, then this wheel"
    export PIPX_HOME="$WORK/pipx-up" PIPX_BIN_DIR="$WORK/pipx-up-bin"
    pipx install --python "$PY" "git+https://github.com/Sanchit-hub/lean-agent-browser@$LEANB_UPGRADE_FROM" >/dev/null
    OLD="$("$PIPX_BIN_DIR/leanb" --version)"
    CFG="$HOME/.lean-browser/config.toml"
    BACKUP="$WORK/config.backup"; [ -f "$CFG" ] && cp "$CFG" "$BACKUP"
    printf '# upgrade-test marker\nblock = true\n' > "$CFG"
    pipx install --force --python "$PY" "$WHEEL" >/dev/null
    NEW="$("$PIPX_BIN_DIR/leanb" --version)"
    echo "$OLD -> $NEW"
    "$PIPX_BIN_DIR/leanb" setup --yes --client none >/dev/null
    grep -q "upgrade-test marker" "$CFG" || { echo "setup overwrote the config during the upgrade"; exit 1; }
    "$PIPX_BIN_DIR/leanb" doctor --no-claude | tail -1 | grep -q "all good"
    if [ -f "$BACKUP" ]; then cp "$BACKUP" "$CFG"; else rm -f "$CFG"; fi
    echo "upgrade OK"
  fi
else
  echo "==> pipx not installed; skipped the pipx install and upgrade checks"
fi
echo "clean install smoke test passed"
