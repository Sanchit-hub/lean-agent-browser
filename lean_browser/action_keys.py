"""Caller-supplied action keys for the duplicate guard, kept on disk so they survive new pages, new sessions
and restarts.

File: $LEANB_STATE_DIR/action_keys.json (default ~/.lean-browser/action_keys.json), mode 600, shaped
{key: {"status": ..., "url": ..., "time": unix_seconds}}. Entries older than 24 hours are dropped. Writes are
atomic (temp file + os.replace) under an advisory lock, so two processes can share the file.
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

TTL_S = 24 * 3600
BLOCKING = ("verified", "ambiguous", "timed_out")
IN_PROGRESS = "in_progress"  # claimed by a call that hasn't finished
IN_PROGRESS_TTL_S = 600  # a claim left by a crashed process stops blocking after 10 minutes


def state_dir() -> Path:
    return Path(os.environ.get("LEANB_STATE_DIR") or "~/.lean-browser").expanduser()


class ActionKeys:
    def __init__(self, directory: str | Path | None = None):
        self._dir = Path(directory).expanduser() if directory else None

    @property
    def path(self) -> Path:
        return (self._dir or state_dir()) / "action_keys.json"

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        now = time.time()
        return {k: v for k, v in data.items()
                if isinstance(v, dict) and isinstance(v.get("time"), (int, float)) and now - v["time"] < TTL_S}

    @contextmanager
    def _locked(self):
        d = self.path.parent
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(d / "action_keys.lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def get(self, key: str) -> dict | None:
        """The earlier result for this key, if it is less than 24 hours old."""
        return self._read().get(key)

    def blocking(self, key: str) -> dict | None:
        """The earlier result for this key if it should block a repeat (verified, ambiguous or timed_out)."""
        e = self.get(key)
        return e if e and e.get("status") in BLOCKING else None

    def _write(self, data: dict) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".action_keys.", suffix=".tmp")  # mode 600
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def claim(self, key: str, url: str, repeat: bool = False) -> dict | None:
        """Atomically reserve the key before dispatching. Returns the entry that blocks it (an earlier verified,
        ambiguous or timed_out result, or another call with this key still running), or None once reserved.
        repeat=True skips the check but still reserves. Two processes racing on one key: exactly one wins."""
        with self._locked():
            data = self._read()
            e = data.get(key)
            if not repeat and e and (e.get("status") in BLOCKING or
                                     (e.get("status") == IN_PROGRESS and time.time() - e["time"] < IN_PROGRESS_TTL_S)):
                return e
            data[key] = {"status": IN_PROGRESS, "url": url, "time": time.time(), "prev": e} if e else \
                {"status": IN_PROGRESS, "url": url, "time": time.time()}
            self._write(data)
            return None

    def release(self, key: str) -> None:
        """Undo a claim when nothing was dispatched (restores what was there before the claim)."""
        with self._locked():
            data = self._read()
            e = data.get(key)
            if e and e.get("status") == IN_PROGRESS:
                if e.get("prev"):
                    data[key] = e["prev"]
                else:
                    del data[key]
                self._write(data)

    def record(self, key: str, status: str, url: str) -> None:
        with self._locked():
            data = self._read()
            old = data.get(key)
            if old and old.get("status") == IN_PROGRESS:
                old = old.get("prev")
            # Never let a weaker result (blocked, unverified) erase one that should keep blocking repeats.
            if old and old.get("status") in BLOCKING and status not in BLOCKING:
                data[key] = old
            else:
                data[key] = {"status": status, "url": url, "time": time.time()}
            self._write(data)
