"""Per-job ledger of vacancies already alerted (plugin-owned, one JSON file per job, 0600).

Entries are keyed by a 16-hex hash of the normalized URL (scheme and host lowercased, fragment and
tracking parameters dropped, remaining parameters sorted, trailing slash removed), with the date and
a short title. Entries older than ``days`` are pruned; beyond ``max_entries`` the oldest go first.
Files are written atomically. A corrupt file raises ``LedgerError``: the caller reports it, it is
never silently reset (a reset would re-send every vacancy).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# Only parameters that never identify a vacancy: some boards carry the offer id in `ref` or `src`.
_TRACKING = re.compile(r"^(utm_[a-z_]*|gclid|fbclid|msclkid|mc_[a-z]+|_hs[a-z]+|trk|trkid)$", re.IGNORECASE)
_lock = threading.Lock()


class LedgerError(RuntimeError):
    """The ledger cannot be read or written."""


def normalize_url(url: str) -> str:
    """Canonical form used for deduplication; raises ValueError for a non-http(s) URL."""
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise ValueError("not an http(s) URL")
    host = parts.netloc.lower()
    host = host.removeprefix("www.")
    query = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False) if not _TRACKING.match(k))
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, urlencode(query), ""))


def url_key(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:16]


class Ledger:
    """File-backed ledger for one profile home."""

    def __init__(self, directory: Path, days: int, max_entries: int) -> None:
        self.directory = directory
        self.days = days
        self.max_entries = max_entries

    def _path(self, job_id: str) -> Path:
        if not _JOB_ID.match(str(job_id)):
            raise LedgerError("invalid job id")
        return self.directory / f"{job_id}.json"

    def _load(self, job_id: str) -> dict:
        path = self._path(job_id)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"version": 1, "entries": {}}
        except OSError as exc:
            raise LedgerError("ledger unreadable") from exc
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise LedgerError("ledger corrupt") from exc
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("entries"), dict):
            raise LedgerError("ledger shape invalid")
        return data

    def _save(self, job_id: str, data: dict) -> None:
        path = self._path(job_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".ledger-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, separators=(",", ":"), ensure_ascii=False)
                os.chmod(tmp, 0o600)
                os.replace(tmp, path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except OSError as exc:
            raise LedgerError("ledger unwritable") from exc

    def _prune(self, entries: dict, today: date) -> dict:
        cutoff = (today - timedelta(days=self.days)).isoformat()
        kept = {k: v for k, v in entries.items() if isinstance(v, dict) and str(v.get("d", "")) >= cutoff}
        if len(kept) > self.max_entries:
            ordered = sorted(kept.items(), key=lambda kv: str(kv[1].get("d", "")))
            kept = dict(ordered[len(kept) - self.max_entries:])
        return kept

    def check(self, job_id: str, urls: list[str], today: date) -> dict:
        """Split URLs into already alerted (with date and title) and new; invalid URLs listed apart."""
        with _lock:
            entries = self._prune(self._load(job_id)["entries"], today)
        seen, new, invalid = [], [], []
        for url in urls:
            try:
                key = url_key(url)
            except ValueError:
                invalid.append(url)
                continue
            if key in entries:
                seen.append({"url": url, "alerted_on": entries[key].get("d"), "title": entries[key].get("t")})
            else:
                new.append(url)
        return {"already_alerted": seen, "new": new, "invalid": invalid}

    def mark(self, job_id: str, items: list[dict], today: date) -> dict:
        """Record vacancies as alerted today; returns counts."""
        with _lock:
            data = self._load(job_id)
            entries = self._prune(data["entries"], today)
            added, invalid = 0, []
            for item in items:
                url = str(item.get("url") or "")
                try:
                    key = url_key(url)
                except ValueError:
                    invalid.append(url)
                    continue
                if key not in entries:
                    added += 1
                entries[key] = {"d": today.isoformat(), "t": " ".join(str(item.get("title") or "").split())[:120]}
            data["entries"] = self._prune(entries, today)
            self._save(job_id, data)
        return {"recorded": added, "invalid": invalid, "total": len(data["entries"])}

    def count(self, job_id: str, today: date) -> int:
        with _lock:
            return len(self._prune(self._load(job_id)["entries"], today))

    def delete(self, job_id: str) -> bool:
        with _lock:
            try:
                self._path(job_id).unlink()
                return True
            except FileNotFoundError:
                return False
            except OSError as exc:
                raise LedgerError("ledger not removable") from exc
