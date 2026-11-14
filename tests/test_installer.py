"""leanb install: skips verified installs, refuses a tampered download (offline)."""
import pytest

from lean_browser import installer
from lean_browser.engine import find_obscura


@pytest.mark.skipif(find_obscura() is None, reason="obscura not installed")
def test_skips_when_already_verified(monkeypatch, tmp_path):
    src = find_obscura().parent
    monkeypatch.setattr(installer, "BIN", src)
    monkeypatch.setattr(installer, "HOME", tmp_path)
    monkeypatch.setattr(installer.urllib.request, "urlretrieve", lambda *a: pytest.fail("must not download"))
    assert installer.install_obscura() is True


def test_rejects_bad_checksum(monkeypatch, tmp_path):
    monkeypatch.setattr(installer, "BIN", tmp_path / "bin")
    monkeypatch.setattr(installer, "HOME", tmp_path)
    monkeypatch.setattr(installer.urllib.request, "urlretrieve", lambda url, dst: open(dst, "wb").write(b"not the release"))
    with pytest.raises(SystemExit, match="checksum mismatch"):
        installer.install_obscura()
    assert not (tmp_path / "bin" / "obscura").exists()
