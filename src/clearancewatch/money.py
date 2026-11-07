"""Parse free-text insurance limits such as ``C$2M`` or ``$2,000,000``.

Deliberately conservative: anything we cannot read with confidence returns
``(None, reason)`` and the caller raises a warning instead of guessing.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple, Union

_AMOUNT = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(million|thousand|m|k)?(?![A-Za-z0-9])", re.I)
_MULT = {"million": 1_000_000, "m": 1_000_000, "thousand": 1_000, "k": 1_000}


def parse_limit(value: Union[str, int, float, None]) -> Tuple[Optional[int], str]:
    """Return ``(dollars, problem)``; exactly one of them is empty."""
    if value is None or value == "":
        return None, "empty"
    if isinstance(value, bool):
        return None, "unreadable"
    if isinstance(value, (int, float)):
        return (int(value), "") if value >= 0 else (None, "unreadable")
    text = str(value)
    up = text.upper()
    if "US$" in up or "USD" in up or "EUR" in up or "GBP" in up:
        return None, "non-CAD currency"
    m = _AMOUNT.search(text)
    if not m:
        return None, "unreadable"
    try:
        num = float(m.group(1).replace(",", ""))
    except ValueError:
        return None, "unreadable"
    mult = _MULT.get((m.group(2) or "").lower(), 1)
    return int(num * mult), ""
