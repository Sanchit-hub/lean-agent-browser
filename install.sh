#!/usr/bin/env bash
# One-command install for Lean Agent Browser (macOS arm64; Linux x86_64 and arm64).
#
#   ./install.sh              core: Python env, pinned + checksummed Obscura, Chromium, self-check
#   ./install.sh --with-eval  also installs the pinned Playwright MCP and agent-browser baselines (Node.js >= 20)
#
# Safe to re-run. Nothing is installed outside this folder and ~/.lean-browser/.
set -euo pipefail

PLAYWRIGHT_MCP_VERSION="0.0.83"
AGENT_BROWSER_VERSION="0.41.0"

HERE="$(cd "$(dirname "$0")" && pwd)"
HOME_DIR="$HOME/.lean-browser"
export PLAYWRIGHT_BROWSERS_PATH="$HOME_DIR/pw-browsers"

say()  { printf '\033[1m==> %s\033[0m\n' "$*"; }
fail() { printf '\033[31merror: %s\033[0m\n' "$*" >&2; exit 1; }

WITH_EVAL=0
for a in "$@"; do
  case "$a" in
    --with-eval) WITH_EVAL=1 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) fail "unknown option $a" ;;
  esac
done

# ---------- platform ----------
OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS" in
  Darwin) [[ -x /usr/bin/sandbox-exec ]] || fail "/usr/bin/sandbox-exec missing (needed to sandbox Obscura)" ;;
  Linux)  command -v bwrap >/dev/null || say "Note: bubblewrap (bwrap) not found. Obscura only runs sandboxed, so until you
     install it (sudo apt install bubblewrap) Chromium will serve every page." ;;
  *) fail "unsupported OS $OS (macOS and Linux are supported)" ;;
esac

# ---------- python ----------
PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null || fail "python3 not found (need 3.12+)"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' || fail "Python 3.12+ required, found $("$PY" -V)"

say "Python environment (.venv, pinned dependencies)"
[[ -d "$HERE/.venv" ]] || "$PY" -m venv "$HERE/.venv"
"$HERE/.venv/bin/pip" install -q --upgrade pip >/dev/null
"$HERE/.venv/bin/pip" install -q -e "$HERE[dev]"

# ---------- engines ----------
# Pinned + checksummed Obscura for this platform, then Playwright's Chromium (lean_browser/installer.py;
# the pinned hashes live in lean_browser/engine.py, one place for install.sh, leanb install and every launch).
"$HERE/.venv/bin/leanb" install

# ---------- eval baseline ----------
if [[ "$WITH_EVAL" == 1 ]]; then
  command -v node >/dev/null || fail "--with-eval needs Node.js >= 20"
  node -e 'process.exit(+process.versions.node.split(".")[0] >= 20 ? 0 : 1)' || fail "Node.js >= 20 required"
  say "Playwright MCP $PLAYWRIGHT_MCP_VERSION (eval baseline; install scripts disabled)"
  mkdir -p "$HERE/.vendor/playwright-mcp"
  (cd "$HERE/.vendor/playwright-mcp" && npm install --prefix . "@playwright/mcp@$PLAYWRIGHT_MCP_VERSION" \
     --save-exact --ignore-scripts --no-audit --no-fund >/dev/null)
  say "Vercel agent-browser $AGENT_BROWSER_VERSION (eval baseline; install scripts disabled, uses our Chromium)"
  mkdir -p "$HERE/.vendor/agent-browser"
  (cd "$HERE/.vendor/agent-browser" && npm install --prefix . "agent-browser@$AGENT_BROWSER_VERSION" \
     --save-exact --ignore-scripts --no-audit --no-fund >/dev/null)
  chmod +x "$HERE"/.vendor/agent-browser/node_modules/agent-browser/bin/agent-browser-* 2>/dev/null || true
fi

# ---------- self-check ----------
say "Self-check"
"$HERE/.venv/bin/leanb" doctor

cat <<EOF

Done. Try:
  $HERE/.venv/bin/leanb open https://news.ycombinator.com/

Add to Claude Code:
  claude mcp add lean-browser -- $HERE/.venv/bin/leanb mcp
EOF
