"""`leanb install`: fetch the engines for a pip install (the same steps install.sh runs for a checkout).

- Obscura 0.2.6 for macOS arm64: download, check the release SHA256, extract to ~/.lean-browser/bin,
  check both binaries' pinned hashes, clear the quarantine flag.
- Playwright's Chromium into ~/.lean-browser/pw-browsers.
Safe to re-run: verified pieces are skipped.
"""
from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from lean_browser.engine import OBSCURA_VERSION, EngineError, verify_obscura

TARBALL = "obscura-aarch64-macos.tar.gz"
TARBALL_SHA256 = "19faa248ac762f466ddb822dbb03ed4f097312d10d1a4d5b2143e6040a9bebd0"
URL = f"https://github.com/h4ckf0r0day/obscura/releases/download/v{OBSCURA_VERSION}/{TARBALL}"
HOME = Path.home() / ".lean-browser"
BIN = HOME / "bin"
BROWSERS = HOME / "pw-browsers"


def _say(msg: str):
    print(f"==> {msg}", flush=True)


def install_obscura() -> bool:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        _say("Skipping Obscura: only macOS arm64 is supported (Chromium will serve every page)")
        return False
    try:
        verify_obscura(BIN / "obscura")
        _say(f"Obscura {OBSCURA_VERSION} already installed and verified")
        return True
    except EngineError:
        pass
    BIN.mkdir(parents=True, exist_ok=True)
    os.chmod(HOME, 0o700)
    with tempfile.TemporaryDirectory() as td:
        tgz = Path(td) / TARBALL
        _say(f"Downloading Obscura {OBSCURA_VERSION}")
        urllib.request.urlretrieve(URL, tgz)
        got = hashlib.sha256(tgz.read_bytes()).hexdigest()
        if got != TARBALL_SHA256:
            raise SystemExit(f"error: Obscura checksum mismatch: got {got}, want {TARBALL_SHA256}")
        _say("Checksum OK")
        with tarfile.open(tgz) as tf:
            members = [m for m in tf.getmembers() if m.name in ("obscura", "obscura-worker") and m.isfile()]
            if len(members) != 2:
                raise SystemExit("error: release archive does not contain obscura and obscura-worker")
            tf.extractall(td, members=members, filter="data")
        for name in ("obscura", "obscura-worker"):
            dst = BIN / name
            shutil.copyfile(Path(td) / name, dst)
            os.chmod(dst, 0o755)
            subprocess.run(["xattr", "-d", "com.apple.quarantine", str(dst)], capture_output=True)
    verify_obscura(BIN / "obscura")  # raises if the extracted binaries don't match the pinned hashes
    return True


def install_chromium():
    _say(f"Chromium for the fallback engine (into {BROWSERS})")
    env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(BROWSERS)}
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True, env=env)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSERS)


def main() -> int:
    install_obscura()
    install_chromium()
    _say("Done. Check it with: leanb doctor")
    return 0
