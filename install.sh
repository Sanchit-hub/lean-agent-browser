#!/usr/bin/env bash
# One-command install for Lean Agent Browser (macOS arm64).
#
#   ./install.sh              core: Python env, pinned + checksummed Obscura, Chromium, self-check
#   ./install.sh --with-eval  also installs the pinned Playwright MCP baseline (Node.js >= 20)
#
# Safe to re-run. Nothing is installed outside this folder and ~/.lean-browser/.
set -euo pipefail

OBSCURA_VERSION="0.2.6"
OBSCURA_TARBALL="obscura-aarch64-macos.tar.gz"
OBSCURA_SHA256="19faa248ac762f466ddb822dbb03ed4f097312d10d1a4d5b2143e6040a9bebd0"
PLAYWRIGHT_MCP_VERSION="0.0.83"

HERE="$(cd "$(dirname "$0")" && pwd)"
HOME_DIR="$HOME/.lean-browser"
BIN_DIR="$HOME_DIR/bin"
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
[[ "$(uname -s)" == "Darwin" ]] || fail "only macOS is supported by this installer"
ARCH="$(uname -m)"
[[ -x /usr/bin/sandbox-exec ]] || fail "/usr/bin/sandbox-exec missing (needed to sandbox Obscura)"

# ---------- python ----------
PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null || fail "python3 not found (need 3.12+)"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' || fail "Python 3.12+ required, found $("$PY" -V)"

say "Python environment (.venv, pinned dependencies)"
[[ -d "$HERE/.venv" ]] || "$PY" -m venv "$HERE/.venv"
"$HERE/.venv/bin/pip" install -q --upgrade pip >/dev/null
"$HERE/.venv/bin/pip" install -q -e "$HERE[dev]"

# ---------- obscura ----------
mkdir -p "$BIN_DIR"
chmod 700 "$HOME_DIR"
if [[ "$ARCH" != "arm64" ]]; then
  say "Skipping Obscura: only the arm64 release is pinned (Chromium will be used for every page)"
elif "$HERE/.venv/bin/python" -c "from lean_browser.engine import verify_obscura; from pathlib import Path; verify_obscura(Path('$BIN_DIR/obscura'))" 2>/dev/null; then
  say "Obscura $OBSCURA_VERSION already installed and verified"
else
  say "Downloading Obscura $OBSCURA_VERSION"
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  curl -fsSL --retry 3 -o "$TMP/$OBSCURA_TARBALL" \
    "https://github.com/h4ckf0r0day/obscura/releases/download/v$OBSCURA_VERSION/$OBSCURA_TARBALL"
  GOT="$(shasum -a 256 "$TMP/$OBSCURA_TARBALL" | cut -d' ' -f1)"
  [[ "$GOT" == "$OBSCURA_SHA256" ]] || fail "Obscura checksum mismatch: got $GOT, want $OBSCURA_SHA256"
  say "Checksum OK"
  mkdir -p "$TMP/x"
  tar -xzf "$TMP/$OBSCURA_TARBALL" -C "$TMP/x"
  for f in obscura obscura-worker; do
    [[ -f "$TMP/x/$f" ]] || fail "$f missing from the release archive"
    install -m 755 "$TMP/x/$f" "$BIN_DIR/$f"
    xattr -d com.apple.quarantine "$BIN_DIR/$f" 2>/dev/null || true
  done
  "$HERE/.venv/bin/python" -c "from lean_browser.engine import verify_obscura; from pathlib import Path; verify_obscura(Path('$BIN_DIR/obscura'))" \
    || fail "extracted Obscura binaries do not match the pinned hashes"
fi

# ---------- chromium ----------
say "Chromium for the fallback engine (into $PLAYWRIGHT_BROWSERS_PATH)"
"$HERE/.venv/bin/python" -m playwright install chromium

# ---------- eval baseline ----------
if [[ "$WITH_EVAL" == 1 ]]; then
  command -v node >/dev/null || fail "--with-eval needs Node.js >= 20"
  node -e 'process.exit(+process.versions.node.split(".")[0] >= 20 ? 0 : 1)' || fail "Node.js >= 20 required"
  say "Playwright MCP $PLAYWRIGHT_MCP_VERSION (eval baseline; install scripts disabled)"
  mkdir -p "$HERE/.vendor/playwright-mcp"
  (cd "$HERE/.vendor/playwright-mcp" && npm install --prefix . "@playwright/mcp@$PLAYWRIGHT_MCP_VERSION" \
     --save-exact --ignore-scripts --no-audit --no-fund >/dev/null)
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
