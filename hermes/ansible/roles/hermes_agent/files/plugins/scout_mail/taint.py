"""Taint ledger: which Telegram messages carry mail-derived text, and which sessions saw it.

Stores identifiers and hashes only: message ids of delivered results, 8-byte fingerprints of
the untrusted text that was rendered, and tainted session ids. No mail text, subject or
address. One JSON file per profile (plugin-data), 0600, atomically replaced, bounded by count
and by ``retention_days``. An unreadable file raises ``TaintStoreError``; callers fail closed.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from collections.abc import Callable, Iterable

from .render import FP_WINDOW, MARKER, _fold, fingerprints

MAX_RESULTS = 60
MAX_SESSIONS = 2_000
_HEX16 = frozenset("0123456789abcdef")


class TaintStoreError(RuntimeError):
    """The ledger cannot be read or written; the caller must fail closed."""


class TaintStore:
    """Thread-safe, file-backed ledger. All public methods are safe to call from any thread."""

    def __init__(self, path: Path, retention_days: int, clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._retention = retention_days * 86_400
        self._clock = clock
        self._lock = threading.Lock()

    def _load(self) -> dict:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"version": 1, "results": [], "sessions": {}}
        except OSError as exc:
            raise TaintStoreError("ledger unreadable") from exc
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise TaintStoreError("ledger corrupt") from exc
        if (not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("results"), list)
                or not isinstance(data.get("sessions"), dict)):
            raise TaintStoreError("ledger shape invalid")
        return data

    def _prune(self, data: dict) -> dict:
        floor = self._clock() - self._retention
        data["results"] = [r for r in data["results"] if isinstance(r, dict) and r.get("ts", 0) >= floor][-MAX_RESULTS:]
        sessions = {k: v for k, v in data["sessions"].items() if isinstance(v, (int, float)) and v >= floor}
        if len(sessions) > MAX_SESSIONS:
            sessions = dict(sorted(sessions.items(), key=lambda kv: kv[1])[-MAX_SESSIONS:])
        data["sessions"] = sessions
        return data

    def _save(self, data: dict) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".taint-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, separators=(",", ":"))
                os.chmod(tmp, 0o600)
                os.replace(tmp, self._path)
            except BaseException:
                with _suppress():
                    os.unlink(tmp)
                raise
        except OSError as exc:
            raise TaintStoreError("ledger unwritable") from exc

    def record_result(self, chat_id: str, message_ids: Iterable[str], segments: Iterable[str]) -> None:
        """Remember a delivered result: its Telegram message ids and its fingerprints."""
        fps: set[str] = set()
        for segment in segments:
            fps |= fingerprints(segment)
        with self._lock:
            data = self._prune(self._load())
            data["results"].append({"ts": self._clock(), "chat": str(chat_id),
                                    "ids": sorted({str(m) for m in message_ids if m}), "fp": sorted(fps)})
            self._save(self._prune(data))

    def taint_session(self, session_id: str) -> None:
        if not session_id:
            return
        with self._lock:
            data = self._prune(self._load())
            if session_id not in data["sessions"]:
                data["sessions"][session_id] = self._clock()
                self._save(data)

    def is_session_tainted(self, session_id: str | None) -> bool:
        if not session_id:
            return False
        with self._lock:
            return session_id in self._prune(self._load())["sessions"]

    def is_result_message(self, chat_id: str, message_id: str | None) -> bool:
        if not message_id:
            return False
        with self._lock:
            data = self._prune(self._load())
        return any(r.get("chat") == str(chat_id) and str(message_id) in r.get("ids", []) for r in data["results"])

    def text_is_tainted(self, text: str | None) -> bool:
        """Marker present, or any 48-char folded window equal to a recorded fingerprint."""
        if not text or not isinstance(text, str):
            return False
        if MARKER in text or _fold(MARKER) in _fold(text):
            return True
        folded = _fold(text[:200_000])
        if len(folded) < FP_WINDOW:
            return False
        with self._lock:
            data = self._prune(self._load())
        known: set[str] = set()
        for r in data["results"]:
            known.update(fp for fp in r.get("fp", []) if isinstance(fp, str) and len(fp) == 16 and set(fp) <= _HEX16)
        if not known:
            return False
        return bool(fingerprints(text[:200_000], stride=1) & known)


class _suppress:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: object) -> bool:
        return True
