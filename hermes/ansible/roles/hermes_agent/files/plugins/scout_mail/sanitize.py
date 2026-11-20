"""Bounded conversion of untrusted mail fields to plain text.

Everything here is a supplementary defense: it bounds sizes and removes invisible or
structural tricks, but it never decides what is safe. No resource is ever fetched: the HTML
parser is the standard library's tokenizer, which only sees the string it is given, and
nothing is decoded recursively (no base64/quoted-printable/URL decoding of attacker text).
"""

from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser

# Bidi controls, zero-width characters, soft hyphen, BOM, tag characters and other invisible format chars.
_INVISIBLE = re.compile("[­͏؜ᅟᅠ឴឵᠎​-‏‪-‮"
                        "⁠-⁯ㅤ︀-️﻿ﾠ\U000e0000-\U000e007f]")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_SPACES = re.compile(r"[ \t   -   　]+")
_BLANK_LINES = re.compile(r"\n{3,}")

_SKIP_TAGS = frozenset({"script", "style", "head", "title", "noscript", "template", "svg", "math",
                        "iframe", "object", "embed", "canvas", "audio", "video", "picture", "select",
                        "button", "form", "textarea"})
_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
                   "source", "track", "wbr"})
_BLOCK = frozenset({"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul",
                    "ol", "blockquote", "section", "article", "header", "footer", "hr", "pre"})
_HIDDEN_STYLE = re.compile(r"(display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|"
                           r"opacity\s*:\s*0(\.0+)?\s*(;|$)|max-height\s*:\s*0|height\s*:\s*0)", re.I)


def clean_text(value: object, max_chars: int, *, single_line: bool = False) -> tuple[str, bool]:
    """Return ``(text, truncated)``: NFC, invisible/control chars removed, whitespace collapsed."""
    if not isinstance(value, str):
        return "", False
    # Bound the work before normalising: NFC can expand, so cut generously first.
    text = value[: max_chars * 4 + 16]
    text = unicodedata.normalize("NFC", text)
    text = _INVISIBLE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub(" ", text)
    if single_line:
        text = text.replace("\n", " ")
    text = _SPACES.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _BLANK_LINES.sub("\n\n", text).strip()
    truncated = len(value) > max_chars * 4 + 16 or len(text) > max_chars
    if len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return text, truncated


class _TextExtractor(HTMLParser):
    """Collect visible text; drop scripts, styles, media, forms and elements styled as hidden."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_stack: list[str] = []
        self.hidden_dropped = 0
        self.images = 0

    def _is_hidden(self, attrs: list[tuple[str, str | None]]) -> bool:
        for name, value in attrs:
            name = (name or "").lower()
            if name in ("hidden",) or (name == "aria-hidden" and (value or "").lower() == "true"):
                return True
            if name == "style" and value and _HIDDEN_STYLE.search(value):
                return True
        return False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "img":
            self.images += 1
        if tag in _VOID:
            if tag in ("br", "hr") and not self._skip_stack:
                self.parts.append("\n")
            return
        if self._skip_stack or tag in _SKIP_TAGS or self._is_hidden(attrs):
            if not self._skip_stack and tag not in _SKIP_TAGS:
                self.hidden_dropped += 1
            self._skip_stack.append(tag)
            return
        if tag in _BLOCK:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "img":
            self.images += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._skip_stack:
            # Pop up to the matching open tag; tolerate malformed nesting without leaking hidden text.
            if tag in self._skip_stack:
                while self._skip_stack:
                    if self._skip_stack.pop() == tag:
                        break
            return
        if tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_stack:
            self.parts.append(data)


def html_to_text(html: object, max_input_chars: int) -> tuple[str, dict[str, int]]:
    """Visible text of an HTML body with counters; input is cut to ``max_input_chars`` first."""
    stats = {"hidden_dropped": 0, "images": 0, "input_truncated": 0}
    if not isinstance(html, str) or not html:
        return "", stats
    if len(html) > max_input_chars:
        html = html[:max_input_chars]
        stats["input_truncated"] = 1
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # malformed markup: keep what was collected, never raise into the handler
        pass
    stats["hidden_dropped"] = parser.hidden_dropped
    stats["images"] = parser.images
    return "".join(parser.parts), stats
