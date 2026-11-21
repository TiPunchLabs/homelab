"""Taint ledger: which Telegram messages carry mail-derived text, and which sessions saw it.

Stores identifiers and hashes only: message ids of delivered results, 8-byte fingerprints of
the untrusted text that was rendered, and tainted session ids. No mail text, subject or
address. One JSON file per profile (plugin-data), 0600, atomically replaced.

Nothing is ever forgotten silently: there is no time-based expiry and no eviction, because a
delivered result stays quotable and a tainted transcript stays actionable for as long as it
exists. The ledger has hard capacities instead; reaching one raises ``LedgerFull`` and the
caller fails closed. A result is reserved (fingerprints, one slot) before delivery and its
Telegram ids are attached to that same record afterwards, so the last slot never loses ids.

When a restriction cannot be written, the caller locks the whole feature down with
``lockdown()``: an empty ``taint.lockdown`` file next to the ledger (creating it needs no data
block), or, if even that fails, the ledger renamed to that name. While it exists Scout refuses
every message and tool, across restarts, until the operator retires Scout's sessions and removes
it (runbook). ``probe_writable()`` lets the caller refuse everything from start-up when the
directory accepts no write at all. An unreadable file raises ``TaintStoreError``; callers fail
closed.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path
from collections.abc import Callable, Iterable

from .render import FP_WINDOW, MARKER, _fold, fingerprints

MAX_RESULTS = 20_000
MAX_FINGERPRINTS = 300_000
MAX_SESSIONS = 100_000
_HEX16 = frozenset("0123456789abcdef")


class TaintStoreError(RuntimeError):
    """The ledger cannot be read or written; the caller must fail closed."""


class LedgerFull(TaintStoreError):
    """A capacity is reached; recording would require forgetting provenance, which is refused."""


class TaintStore:
    """Thread-safe, file-backed ledger. All public methods are safe to call from any thread."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._lock_path = path.with_name("taint.lockdown")
        self._clock = clock
        self._lock = threading.Lock()
        self._cache_key: tuple[int, int, int, int] | None = None
        self._cache: tuple[dict, frozenset[str]] | None = None

    def _parse(self, raw: str) -> dict:
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise TaintStoreError("ledger corrupt") from exc
        if (not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("results"), list)
                or not isinstance(data.get("sessions"), dict)):
            raise TaintStoreError("ledger shape invalid")
        return data

    def _load(self) -> dict:
        """Fresh, mutable copy of the ledger (used by writers)."""
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"version": 1, "results": [], "sessions": {}}
        except OSError as exc:
            raise TaintStoreError("ledger unreadable") from exc
        return self._parse(raw)

    def _view(self) -> tuple[dict, frozenset[str]]:
        """Read-only ledger and its fingerprint set, re-parsed only when the file changed."""
        try:
            st = self._path.stat()
        except FileNotFoundError:
            return {"version": 1, "results": [], "sessions": {}}, frozenset()
        except OSError as exc:
            raise TaintStoreError("ledger unreadable") from exc
        key = (st.st_ino, st.st_mtime_ns, st.st_ctime_ns, st.st_size)
        if self._cache is None or self._cache_key != key:
            data = self._load()
            known = frozenset(fp for r in data["results"] if isinstance(r, dict)
                              for fp in r.get("fp", []) if isinstance(fp, str) and len(fp) == 16 and set(fp) <= _HEX16)
            self._cache, self._cache_key = (data, known), key
        return self._cache

    def _save(self, data: dict) -> None:
        self._cache = self._cache_key = None
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

    def record_result(self, chat_id: str, message_ids: Iterable[str], segments: Iterable[str]) -> str:
        """Reserve one record for a result (its fingerprints, and ids if already known).

        Returns the record handle for ``attach_ids``. Raises ``LedgerFull`` instead of dropping
        older provenance, so a result that cannot be reserved is never delivered.
        """
        fps: set[str] = set()
        for segment in segments:
            fps |= fingerprints(segment)
        ids = sorted({str(m) for m in message_ids if m})
        rid = secrets.token_hex(8)
        with self._lock:
            data = self._load()
            stored = sum(len(r.get("fp", [])) for r in data["results"] if isinstance(r, dict))
            if len(data["results"]) >= MAX_RESULTS or stored + len(fps) > MAX_FINGERPRINTS:
                raise LedgerFull("result capacity reached")
            data["results"].append({"ts": self._clock(), "rid": rid, "chat": str(chat_id), "ids": ids,
                                    "fp": sorted(fps)})
            self._save(data)
        return rid

    def attach_ids(self, rid: str, message_ids: Iterable[str]) -> None:
        """Add delivered Telegram ids to the reserved record; takes no new slot."""
        ids = {str(m) for m in message_ids if m}
        with self._lock:
            data = self._load()
            for record in data["results"]:
                if isinstance(record, dict) and record.get("rid") == rid:
                    record["ids"] = sorted(ids | {str(m) for m in record.get("ids", [])})
                    self._save(data)
                    return
        raise TaintStoreError("reserved result missing")

    def lockdown(self) -> None:
        """Persist a feature-wide refusal; raises ``TaintStoreError`` if nothing could be written."""
        with self._lock:
            self._cache = self._cache_key = None
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.close(os.open(self._lock_path, os.O_WRONLY | os.O_CREAT, 0o600))
                return
            except OSError:
                pass
            try:
                os.replace(self._path, self._lock_path)  # a rename needs no new data block
            except OSError as exc:
                raise TaintStoreError("lockdown not persisted") from exc

    def locked(self) -> bool:
        try:
            self._lock_path.stat()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise TaintStoreError("lockdown state unreadable") from exc
        return True

    def probe_writable(self) -> None:
        """Raise ``TaintStoreError`` unless a file can be created and removed beside the ledger."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".probe-")
            os.close(fd)
            os.unlink(tmp)
        except OSError as exc:
            raise TaintStoreError("ledger directory unwritable") from exc

    def taint_session(self, session_id: str) -> None:
        """Mark a session as restricted for good; raises ``LedgerFull`` rather than evicting one."""
        if not session_id:
            return
        with self._lock:
            data = self._load()
            if session_id in data["sessions"]:
                return
            if len(data["sessions"]) >= MAX_SESSIONS:
                raise LedgerFull("session capacity reached")
            data["sessions"][session_id] = self._clock()
            self._save(data)

    def sessions_full(self) -> bool:
        with self._lock:
            return len(self._view()[0]["sessions"]) >= MAX_SESSIONS

    def is_session_tainted(self, session_id: str | None) -> bool:
        if not session_id:
            return False
        with self._lock:
            return session_id in self._view()[0]["sessions"]

    def is_result_message(self, chat_id: str, message_id: str | None) -> bool:
        if not message_id:
            return False
        with self._lock:
            results = self._view()[0]["results"]
        return any(isinstance(r, dict) and r.get("chat") == str(chat_id) and str(message_id) in r.get("ids", [])
                   for r in results)

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
            known = self._view()[1]
        if not known:
            return False
        return bool(fingerprints(text[:200_000], stride=1) & known)


class _suppress:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: object) -> bool:
        return True
