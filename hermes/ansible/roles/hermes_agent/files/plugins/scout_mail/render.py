"""Trusted renderer: fixed French labels around neutralized untrusted text.

The Telegram adapter converts markdown and Telegram itself detects URLs, domains, e-mail
addresses, ``@mentions``, ``#hashtags`` and ``/commands`` in plain text. Untrusted text is
therefore rewritten so that none of these can form: markdown punctuation and the ``@ # $ /``
signs become visually close but inert full-width/look-alike characters, and dots between
letters or digits become a one-dot leader, so ``example.com`` can no longer be a link.
Only text from this module's constants is left unchanged.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

MARKER = "📬 Courriels — contenu externe non fiable"

_CHAR_MAP = str.maketrans({
    "*": "∗", "_": "ˍ", "~": "∼", "`": "ˋ", "|": "ǀ", "[": "⁅", "]": "⁆", "<": "‹", ">": "›",
    "\\": "⧵", "/": "∕", "@": "＠", "#": "＃", "$": "＄", "{": "❴", "}": "❵", "=": "꞊",
})
_DOT_BETWEEN = re.compile(r"(?<=[^\W_])\.(?=[^\W_])")
_SCHEME = re.compile(r"(?i)\b(https?|ftp|mailto|tg|javascript|data|file|intent|sms|tel)\s*:")
_WS = re.compile(r"\s+")

_FOLD_CATEGORIES = frozenset({"Lu", "Ll", "Lo", "Nd"})
FP_WINDOW = 48
FP_STRIDE = 8


def neutralize(text: str) -> str:
    """Make untrusted text inert for Telegram: no link, mention, command or markdown can form."""
    text = _SCHEME.sub(lambda m: m.group(1)[0] + "‧" + m.group(1)[1:] + "꞉", text)
    text = _DOT_BETWEEN.sub("․", text)
    return text.translate(_CHAR_MAP)


def _fold(text: str) -> str:
    """Letters and digits only, case-folded and accent-stripped: the matching alphabet of fingerprints."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if unicodedata.category(c) in _FOLD_CATEGORIES)


def fingerprints(text: str, *, stride: int = FP_STRIDE) -> set[str]:
    """Hashes of folded windows; stored at stride 8, checked at stride 1 (quotes >= 55 chars match)."""
    folded = _fold(text)
    if len(folded) < FP_WINDOW:
        return set()
    return {hashlib.blake2b(folded[i:i + FP_WINDOW].encode(), digest_size=8).hexdigest()
            for i in range(0, len(folded) - FP_WINDOW + 1, stride)}


MAX_PARTS = 3


@dataclass
class Rendered:
    """One or more Telegram messages; every part starts with the trusted marker."""

    parts: list[str]
    untrusted_segments: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(self.parts)


def plain(text: str) -> Rendered:
    """A fixed (trusted, not mail-derived) reply."""
    return Rendered([text])


class Builder:
    """Trusted labels plus neutralized untrusted values, split into at most ``MAX_PARTS`` messages.

    Each part stays under ``max_chars`` (a 300-char reserve is kept for the closing lines) and opens
    with the marker, so a reply to any part is recognised. ``truncated`` tells the caller to name what
    could not be shown.
    """

    def __init__(self, max_chars: int, header: list[str]) -> None:
        self._max = max_chars
        self._header = header
        self._parts: list[list[str]] = [list(header)]
        self.segments: list[str] = []
        self.truncated = False

    def _size(self) -> int:
        return sum(len(line) + 1 for line in self._parts[-1])

    def room(self) -> int:
        """Characters still available in the current part before the reserve."""
        return self._max - 300 - self._size()

    def new_part(self) -> bool:
        """Start the next message if the cap allows; False (and truncated) otherwise."""
        if len(self._parts) >= MAX_PARTS:
            self.truncated = True
            return False
        self._parts.append([self._header[0], "(suite)"])
        return True

    def trusted(self, line: str) -> bool:
        return self._add(line)

    def field(self, label: str, value: str) -> bool:
        safe = neutralize(_WS.sub(" ", value).strip())
        if not safe:
            return True
        self.segments.append(safe)
        return self._add(f"{label} {safe}")

    def footer(self, line: str) -> None:
        """Trusted closing lines; the 300-char reserve kept by ``_add`` guarantees they fit."""
        self._parts[-1].append(line)

    def _add(self, line: str) -> bool:
        if self.truncated:
            return False
        if len(line) + 1 > self.room() and not self.new_part():
            return False
        if len(line) + 1 > self.room():  # a single line longer than a whole part: cut it
            line = line[: max(0, self.room() - 1)]
        self._parts[-1].append(line)
        return True

    def build(self) -> Rendered:
        return Rendered(["\n".join(lines) for lines in self._parts], self.segments)
