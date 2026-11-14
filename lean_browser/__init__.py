"""Lean Agent Browser: a token-lean browser for AI agents (Obscura first, Chromium fallback)."""
import os
from pathlib import Path


def _default_browsers_path() -> None:
    """Point Playwright at the Chromium that install.sh downloaded, unless the user chose one."""
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    for p in (Path.home() / ".lean-browser/pw-browsers", Path(__file__).resolve().parent.parent / ".vendor/pw-browsers"):
        if p.is_dir():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(p)
            return


_default_browsers_path()
