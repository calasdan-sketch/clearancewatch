"""Parse free-text insurance limits such as ``C$2M`` or ``$2,000,000``.

Deliberately conservative: anything we cannot read with confidence returns
``(None, reason)`` and the caller raises a warning instead of guessing.
Unreadable on purpose: negatives, ``2 000 000`` and ``2.000.000`` (digit
grouping that differs by locale), ``1e6``, other currencies, absurd sizes.
"""
from __future__ import annotations

import re
from functools import lru_cache
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Tuple, Union

MAX_LIMIT = 10 ** 12  # a trillion dollars is a typo, not a policy

# a digit run (ASCII only), then anything up to the next one is inspected by hand
_RUN = re.compile(r"[0-9][0-9,.]*", re.A)
_PLAIN = re.compile(r"^[0-9]+(\.[0-9]+)?$", re.A)
_GROUPED = re.compile(r"^[0-9]{1,3}(,[0-9]{3})+(\.[0-9]+)?$", re.A)
_UNIT = re.compile(r"[ \t]{0,2}(million|thousand|mm|m|k)(?![A-Za-z0-9])", re.I | re.A)
_MULT = {"million": 1_000_000, "mm": 1_000_000, "m": 1_000_000, "thousand": 1_000, "k": 1_000}
_LABEL = r"(per\s+occurrence|each\s+occurrence|occurrence|per\s+claim|each\s+claim)"
_STOP = r"(?:(?!aggregate|agg\b|umbrella|excess)[^0-9]){0,24}?"  # a label past one of these is not ours
_PER_OCC = re.compile(_STOP + _LABEL, re.I | re.A)
_OCC_BEFORE = re.compile(_LABEL + r"[^0-9A-Za-z]{0,6}(c?\$)?\s*$", re.I | re.A)
_SPACE_GROUP = re.compile(r"^[ \t][0-9]{3}(?![0-9])", re.A)
# An amount that is a deductible/retention is not a limit and must never be read as one.
_DED_AFTER = re.compile(r"[ \t]*(?:deductible|deduct\.?|ded\b\.?|retention|sir\b|self[- ]insured)", re.I | re.A)
_DED_BEFORE = re.compile(r"(?:deductible|deduct|retention|sir)[ \t:=]{0,3}(?:c?\$)?[ \t]*$", re.I | re.A)
_EXCESS = re.compile(r"\b(?:umbrella|excess)\b", re.I | re.A)


def mentions_excess(value: object) -> bool:
    """True when free-text coverage mentions an umbrella or excess layer."""
    return isinstance(value, str) and bool(_EXCESS.search(value))


def parse_limits(value: Union[str, int, float, None]) -> Tuple[List[Tuple[int, bool]], str]:
    """Every dollar amount in ``value`` as ``(dollars, labelled_per_occurrence)``.

    Returns ``([], problem)`` when anything in the text cannot be read with
    confidence (a half-readable limit is never compared).
    """
    if value is None or value == "":
        return [], "empty"
    if isinstance(value, bool):
        return [], "unreadable"
    if isinstance(value, (int, float)):
        if value != value or value in (float("inf"), float("-inf")) or value < 0:
            return [], "unreadable"
        if value > MAX_LIMIT:
            return [], "implausibly large"
        return [(int(value), False)], ""
    if not isinstance(value, str):
        return [], "unreadable"
    amounts, problem = _parse_text(value)
    return list(amounts), problem


@lru_cache(maxsize=4096)
def _parse_text(text: str) -> Tuple[Tuple[Tuple[int, bool], ...], str]:
    if len(text) > 2000:
        return (), "too long to read safely"
    up = text.upper()
    if "US$" in up or "USD" in up or "EUR" in up or "GBP" in up or "€" in text or "£" in text:
        return (), "non-CAD currency"
    out: List[Tuple[int, bool]] = []
    prev_end = 0
    for m in _RUN.finditer(text):
        run = m.group(0).rstrip(",.")
        tail = m.group(0)[len(run):]
        before = text[:m.start()].rstrip()
        if before.endswith("-") and (len(before) == 1 or not before[-2].isalnum()):
            return (), "negative or unreadable"
        if not (_PLAIN.match(run) or _GROUPED.match(run)):
            return (), "unreadable (digit grouping is ambiguous)"
        rest = text[m.end() - len(tail):]
        if _SPACE_GROUP.match(rest):
            return (), "unreadable (digit grouping is ambiguous)"
        um = _UNIT.match(rest)
        if um:
            mult, after = _MULT[um.group(1).lower()], rest[um.end():]
        else:
            if rest[:1].isalnum():  # '1e6', '5x'
                return (), "unreadable"
            mult, after = 1, rest
        try:
            amount = int(Decimal(run.replace(",", "")) * mult)
        except InvalidOperation:  # pragma: no cover - guarded by the regexes above
            return (), "unreadable"
        if amount > MAX_LIMIT:
            return (), "implausibly large"
        if _DED_AFTER.match(after) or _DED_BEFORE.search(text[prev_end:m.start()]):
            prev_end = m.end() - len(tail) + (um.end() if um else 0)
            continue  # a deductible or retention, not a limit
        if mult == 1 and amount < 1000 and not before.endswith("$"):
            return (), (f"unreadable (the small number {run} is not a dollar amount; "
                        "shorthand such as 1/2M is ambiguous)")
        after_label = _PER_OCC.match(after)
        labelled = bool(after_label) or bool(_OCC_BEFORE.search(text[prev_end:m.start()]))
        out.append((amount, labelled))
        prev_end = m.end() - len(tail) + (um.end() if um else 0) + (after_label.end() if after_label else 0)
    if not out:
        return (), "unreadable"
    return tuple(out), ""


def parse_limit(value: Union[str, int, float, None]) -> Tuple[Optional[int], str]:
    """Return ``(dollars, problem)``; exactly one of them is empty.

    With several amounts in the text the one labelled per occurrence wins,
    otherwise the first. Use :func:`parse_limits` to see them all.
    """
    amounts, problem = parse_limits(value)
    if not amounts:
        return None, problem
    return primary_limit(amounts), ""


def primary_limit(amounts: List[Tuple[int, bool]]) -> int:
    """The per-occurrence amount if one is labelled, else the first."""
    for amount, labelled in amounts:
        if labelled:
            return amount
    return amounts[0][0]
