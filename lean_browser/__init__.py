"""Lean Agent Browser: a token-lean browser for AI agents (Obscura first, Chromium fallback)."""
import os
from pathlib import Path

__version__ = "0.4.0"


def _default_browsers_path() -> None:
    """Point Playwright at the Chromium that install.sh downloaded, unless the user chose one."""
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    for p in (Path.home() / ".lean-browser/pw-browsers", Path(__file__).resolve().parent.parent / ".vendor/pw-browsers"):
        if p.is_dir():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(p)
            return


_default_browsers_path()


__all__ = ["LeanBrowser", "LeanBrowserError", "Config"]


def __getattr__(name):  # lazy, so importing a submodule doesn't pull in everything
    if name in __all__:
        from lean_browser import tools
        return getattr(tools, name)
    raise AttributeError(name)
