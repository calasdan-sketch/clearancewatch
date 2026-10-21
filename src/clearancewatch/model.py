"""Data model: jobs, subcontractors, and the documents that keep them legal."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

WSIB_DEFAULT_VALID_DAYS = 90  # WSIB: clearance certificates valid up to 90 days


def parse_date(value: Optional[str]) -> Optional[dt.date]:
    if value in (None, ""):
        return None
    return dt.date.fromisoformat(str(value))


@dataclass
class Clearance:
    """A workers'-compensation clearance certificate.

    Ontario (WSIB): has a real expiry — ``expires``, defaulting to issued +
    90 days when not stated.
    Alberta (WCB): a clearance letter covers work done UP TO the date of the
    letter — model that as ``covered_until`` (defaults to ``issued``).
    """

    issuer: str = ""            # e.g. "WSIB", "WCB-AB"
    number: str = ""
    issued: Optional[dt.date] = None
    expires: Optional[dt.date] = None
    covered_until: Optional[dt.date] = None  # Alberta-style letter coverage

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Clearance":
        return cls(issuer=d.get("issuer", ""), number=d.get("number", ""),
                   issued=parse_date(d.get("issued")), expires=parse_date(d.get("expires")),
                   covered_until=parse_date(d.get("covered_until")))

    def effective_expiry(self, valid_days: int = WSIB_DEFAULT_VALID_DAYS) -> Optional[dt.date]:
        if self.expires:
            return self.expires
        if self.issued and self.covered_until is None:
            return self.issued + dt.timedelta(days=valid_days)
        return self.covered_until or self.expires


@dataclass
class Insurance:
    provider: str = ""
    policy: str = ""
    coverage: str = ""          # e.g. "C$2M liability"
    expires: Optional[dt.date] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Insurance":
        return cls(provider=d.get("provider", ""), policy=d.get("policy", ""),
                   coverage=d.get("coverage", ""), expires=parse_date(d.get("expires")))


@dataclass
class Licence:
    name: str = ""              # e.g. "309A electrical"
    number: str = ""
    authority: str = ""         # e.g. "TSSA", "ESA"
    expires: Optional[dt.date] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Licence":
        return cls(name=d.get("name", ""), number=d.get("number", ""),
                   authority=d.get("authority", ""), expires=parse_date(d.get("expires")))


@dataclass
class Subcontractor:
    name: str
    province: str = ""
    trade: str = ""
    clearance: Optional[Clearance] = None
    insurance: Optional[Insurance] = None
    licences: List[Licence] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Subcontractor":
        return cls(
            name=d.get("name", "unnamed sub"),
            province=d.get("province", ""),
            trade=d.get("trade", ""),
            clearance=Clearance.from_dict(d["clearance"]) if d.get("clearance") else None,
            insurance=Insurance.from_dict(d["insurance"]) if d.get("insurance") else None,
            licences=[Licence.from_dict(x) for x in d.get("licences", [])],
        )


@dataclass
class Job:
    name: str
    province: str = ""
    start: Optional[dt.date] = None
    end: Optional[dt.date] = None  # None = ongoing
    subs: List[Subcontractor] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Job":
        return cls(
            name=d.get("name", "unnamed job"),
            province=d.get("province", ""),
            start=parse_date(d.get("start")),
            end=parse_date(d.get("end")),
            subs=[Subcontractor.from_dict(s) for s in d.get("subs", d.get("subcontractors", []))],
        )
