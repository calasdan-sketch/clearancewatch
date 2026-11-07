"""Output hygiene for untrusted document data (names, issuers, free text).

Jobs files come from emails, spreadsheets and sub-supplied PDFs, so any string
may carry terminal escape sequences, bidi overrides (which can make a line
read differently from what it is) or spreadsheet formulas. Everything that
reaches a terminal, CSV or Markdown goes through here.
"""
from __future__ import annotations

import re

# C0/C1 controls (incl. ESC), DEL, zero-width, line/paragraph separators and bidi formatting characters.
_BAD = re.compile(
    "[\u0000-\u001f\u007f-\u009f\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]"
)
MAX_FIELD = 300


def clean(value: object, limit: int = MAX_FIELD) -> str:
    """Printable, single-line, length-capped version of ``value``."""
    text = str(value)

    def esc(m: "re.Match[str]") -> str:
        return "\\u%04x" % ord(m.group(0))

    text = _BAD.sub(esc, text)
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def csv_cell(value: object) -> str:
    """``clean`` plus a guard against spreadsheet formula injection."""
    text = clean(value)
    if text[:1] in ("=", "+", "-", "@"):
        text = "'" + text
    return text


def md_cell(value: object) -> str:
    """``clean`` plus Markdown-table escaping."""
    text = clean(value).replace("\\", "\\\\")
    for ch, rep in (("|", "\\|"), ("`", "\\`"), ("<", "&lt;"), ("[", "\\["), ("]", "\\]")):
        text = text.replace(ch, rep)
    return text
