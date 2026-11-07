"""Data model: jobs, subcontractors, and the documents that keep them legal."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

WSIB_DEFAULT_VALID_DAYS = 90  # WSIB: clearance certificates valid up to 90 days

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class DataError(ValueError):
    """The jobs data is malformed. The message names the offending field."""


def parse_date(value: Any, path: str = "date") -> Optional[dt.date]:
    """Strict YYYY-MM-DD (rejects numbers, '20260101', week dates, impossible days)."""
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not _ISO.match(value.strip()):
        raise DataError(f"{path}: expected a date like 2026-03-31, got {value!r}")
    try:
        d = dt.date.fromisoformat(value.strip())
    except ValueError:
        raise DataError(f"{path}: not a real calendar date: {value!r}") from None
    if not 1900 <= d.year <= 2200:  # also keeps date arithmetic away from the min/max overflow edge
        raise DataError(f"{path}: year {d.year} is implausible (expected 1900-2200): {value!r}")
    return d


def _obj(d: Any, path: str) -> Dict[str, Any]:
    if not isinstance(d, dict):
        raise DataError(f"{path}: expected an object, got {type(d).__name__}")
    return d


def _text(d: Dict[str, Any], key: str, path: str, default: str = "") -> str:
    v = d.get(key, default)
    if v is None:
        return default
    if isinstance(v, (dict, list, bool)):
        raise DataError(f"{path}.{key}: expected text, got {type(v).__name__}")
    return str(v)


def _flag(d: Dict[str, Any], key: str, path: str) -> Optional[bool]:
    """Strict true/false/absent. 'yes'/'no' text is rejected: say true or false."""
    v = d.get(key)
    if v is None or v == "":
        return None
    if not isinstance(v, bool):
        raise DataError(f"{path}.{key}: expected true or false, got {v!r}")
    return v


def _unknown(d: Dict[str, Any], known: set, path: str, notes: List[str]) -> None:
    for k in d:
        if k not in known:
            notes.append(f"{path}: unrecognised field {k!r} was ignored (typo?)")


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

    _KEYS = {"issuer", "number", "issued", "expires", "covered_until"}

    @classmethod
    def from_dict(cls, d: Dict[str, Any], path: str = "clearance",
                  notes: Optional[List[str]] = None) -> "Clearance":
        d = _obj(d, path)
        if notes is not None:
            _unknown(d, cls._KEYS, path, notes)
        return cls(issuer=_text(d, "issuer", path), number=_text(d, "number", path),
                   issued=parse_date(d.get("issued"), f"{path}.issued"),
                   expires=parse_date(d.get("expires"), f"{path}.expires"),
                   covered_until=parse_date(d.get("covered_until"), f"{path}.covered_until"))

    def is_blank(self) -> bool:
        return not (self.issuer or self.issued or self.expires or self.covered_until)

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
    # Endorsements as read off the certificate: True / False / None (not recorded).
    additional_insured: Optional[bool] = None
    waiver_of_subrogation: Optional[bool] = None
    primary_noncontributory: Optional[bool] = None

    _KEYS = {"provider", "policy", "coverage", "expires", "additional_insured",
             "waiver_of_subrogation", "primary_noncontributory"}

    @classmethod
    def from_dict(cls, d: Dict[str, Any], path: str = "insurance",
                  notes: Optional[List[str]] = None) -> "Insurance":
        d = _obj(d, path)
        if notes is not None:
            _unknown(d, cls._KEYS, path, notes)
        return cls(provider=_text(d, "provider", path), policy=_text(d, "policy", path),
                   coverage=_text(d, "coverage", path),
                   expires=parse_date(d.get("expires"), f"{path}.expires"),
                   additional_insured=_flag(d, "additional_insured", path),
                   waiver_of_subrogation=_flag(d, "waiver_of_subrogation", path),
                   primary_noncontributory=_flag(d, "primary_noncontributory", path))


@dataclass
class Licence:
    name: str = ""              # e.g. "309A electrical"
    number: str = ""
    authority: str = ""         # e.g. "TSSA", "ESA"
    expires: Optional[dt.date] = None

    _KEYS = {"name", "number", "authority", "expires"}

    @classmethod
    def from_dict(cls, d: Dict[str, Any], path: str = "licence",
                  notes: Optional[List[str]] = None) -> "Licence":
        d = _obj(d, path)
        if notes is not None:
            _unknown(d, cls._KEYS, path, notes)
        return cls(name=_text(d, "name", path), number=_text(d, "number", path),
                   authority=_text(d, "authority", path),
                   expires=parse_date(d.get("expires"), f"{path}.expires"))


@dataclass
class Subcontractor:
    name: str
    province: str = ""
    trade: str = ""
    clearance: Optional[Clearance] = None
    insurance: Optional[Insurance] = None
    licences: List[Licence] = field(default_factory=list)
    # Earlier/other certificates (renewal history). ``clearance`` stays the primary one.
    clearances: List[Clearance] = field(default_factory=list)
    # Why no clearance is needed (e.g. "sole proprietor, no workers"). Reported as a note
    # for a human to confirm; it only applies while no clearance is on file.
    clearance_exempt: str = ""

    _KEYS = {"name", "province", "trade", "clearance", "clearances", "insurance", "licences",
             "clearance_exempt"}

    @classmethod
    def from_dict(cls, d: Dict[str, Any], path: str = "sub",
                  notes: Optional[List[str]] = None) -> "Subcontractor":
        d = _obj(d, path)
        if notes is not None:
            _unknown(d, cls._KEYS, path, notes)
        hist_raw = d.get("clearances") or []
        if not isinstance(hist_raw, list):
            raise DataError(f"{path}.clearances: expected a list")
        hist = [Clearance.from_dict(x, f"{path}.clearances[{i}]", notes) for i, x in enumerate(hist_raw)]
        lic_raw = d.get("licences") or []
        if not isinstance(lic_raw, list):
            raise DataError(f"{path}.licences: expected a list")
        primary = Clearance.from_dict(d["clearance"], f"{path}.clearance", notes) if d.get("clearance") else None
        return cls(
            name=_text(d, "name", path, "unnamed sub") or "unnamed sub",
            province=_text(d, "province", path),
            trade=_text(d, "trade", path),
            clearance=primary,
            insurance=Insurance.from_dict(d["insurance"], f"{path}.insurance", notes) if d.get("insurance") else None,
            licences=[Licence.from_dict(x, f"{path}.licences[{i}]", notes) for i, x in enumerate(lic_raw)],
            clearances=hist,
            clearance_exempt=_text(d, "clearance_exempt", path).strip(),
        )

    def all_clearances(self) -> List[Clearance]:
        out = ([self.clearance] if self.clearance else []) + list(self.clearances)
        return [c for c in out if not c.is_blank()]


@dataclass
class Requirements:
    """Contract requirements the principal sets for every sub on a job."""

    min_liability: Optional[int] = None   # CAD dollars; parsed from 2000000 or "C$2M"
    additional_insured: bool = False
    waiver_of_subrogation: bool = False
    primary_noncontributory: bool = False
    # trade -> text that must appear in one of the sub's licence names, e.g. {"electrical": "electrician"}
    required_licences: Dict[str, str] = field(default_factory=dict)

    _KEYS = {"min_liability", "additional_insured", "waiver_of_subrogation", "primary_noncontributory",
             "required_licences"}

    @classmethod
    def from_dict(cls, d: Any, path: str = "requirements",
                  notes: Optional[List[str]] = None) -> "Requirements":
        from .money import parse_limit
        d = _obj(d, path)
        if notes is not None:
            _unknown(d, cls._KEYS, path, notes)
        out = cls(additional_insured=bool(_flag(d, "additional_insured", path)),
                  waiver_of_subrogation=bool(_flag(d, "waiver_of_subrogation", path)),
                  primary_noncontributory=bool(_flag(d, "primary_noncontributory", path)))
        lic = d.get("required_licences")
        if lic not in (None, {}):
            lic = _obj(lic, f"{path}.required_licences")
            for trade, needle in lic.items():
                if not isinstance(needle, str) or not needle.strip() or not str(trade).strip():
                    raise DataError(f"{path}.required_licences[{trade!r}]: expected a non-empty licence name")
                out.required_licences[str(trade).strip().casefold()] = needle.strip().casefold()
        raw = d.get("min_liability")
        if raw in (None, ""):
            return out
        amount, problem = parse_limit(raw)
        if amount is None:
            raise DataError(f"{path}.min_liability: cannot read {raw!r} ({problem})")
        out.min_liability = amount
        return out


@dataclass
class Job:
    name: str
    province: str = ""
    start: Optional[dt.date] = None
    end: Optional[dt.date] = None  # None = ongoing
    subs: List[Subcontractor] = field(default_factory=list)
    requirements: Requirements = field(default_factory=Requirements)
    notes: List[str] = field(default_factory=list)  # load-time schema warnings
    payment_dates: List[dt.date] = field(default_factory=list)  # planned draws / releases of payment

    _KEYS = {"name", "province", "start", "end", "subs", "subcontractors", "requirements", "payment_dates"}

    @classmethod
    def from_dict(cls, d: Dict[str, Any], path: str = "job") -> "Job":
        d = _obj(d, path)
        notes: List[str] = []
        _unknown(d, cls._KEYS, path, notes)
        subs_raw = d.get("subs", d.get("subcontractors", [])) or []
        if not isinstance(subs_raw, list):
            raise DataError(f"{path}.subs: expected a list")
        pay_raw = d.get("payment_dates") or []
        if not isinstance(pay_raw, list):
            raise DataError(f"{path}.payment_dates: expected a list of dates")
        if len(pay_raw) > 500:
            raise DataError(f"{path}.payment_dates: {len(pay_raw)} dates is more than the limit of 500")
        pays = [parse_date(x, f"{path}.payment_dates[{i}]") for i, x in enumerate(pay_raw)]
        return cls(
            payment_dates=[p for p in pays if p is not None],
            name=_text(d, "name", path, "unnamed job") or "unnamed job",
            province=_text(d, "province", path),
            start=parse_date(d.get("start"), f"{path}.start"),
            end=parse_date(d.get("end"), f"{path}.end"),
            subs=[Subcontractor.from_dict(s, f"{path}.subs[{i}]", notes) for i, s in enumerate(subs_raw)],
            requirements=Requirements.from_dict(d.get("requirements") or {}, f"{path}.requirements", notes),
            notes=notes,
        )
