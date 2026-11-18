# Importing the package points Playwright at the Chromium that install.sh downloaded
# (~/.lean-browser/pw-browsers, or .vendor/pw-browsers in a dev checkout).
import lean_browser  # noqa: F401

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_action_keys(tmp_path_factory, monkeypatch):
    """No test writes the user's real ~/.lean-browser/action_keys.json (a key left there blocks real submits for
    24 hours). Tests that need their own store set LEANB_STATE_DIR again."""
    monkeypatch.setenv("LEANB_STATE_DIR", str(tmp_path_factory.mktemp("lean-state")))
