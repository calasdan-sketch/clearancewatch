"""Audit a job's subcontractors against the job calendar.

Severity model: things that expose the principal to deeming/penalty risk are
errors (missing or expired clearance, lapsed coverage, expired insurance or
licence); things that are still legal today but will bite soon are warnings
(expiring during the job, renewal horizon).

Not legal advice. Two rules are verified against the regulator's own pages
(WSIB: clearance valid up to 90 days; WCB Alberta: get a clearance before
hiring and before releasing payment). The stricter house rules built on them
("valid for the whole job", "Alberta letter covers work only up to its date")
are conservative policy, not quoted law: see the README.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from .model import Clearance, Job, Subcontractor, WSIB_DEFAULT_VALID_DAYS
from .money import parse_limit


@dataclass(frozen=True)
class Finding:
    severity: str  # error | warn
    code: str
    subject: str   # "job / sub"
    detail: str
    job: str = ""
    sub: str = ""

    def as_dict(self):
        return {"severity": self.severity, "code": self.code,
                "subject": self.subject, "detail": self.detail,
                "job": self.job, "sub": self.sub}


_PROVINCES = {"ON": "ON", "ONTARIO": "ON", "AB": "AB", "ALBERTA": "AB"}


def _province(value: str) -> str:
    """Normalised province for the two modelled jurisdictions, else upper-cased text."""
    v = (value or "").strip().upper()
    return _PROVINCES.get(v, v)


def _issuer_family(issuer: str) -> str:
    """ON (WSIB), AB (WCB Alberta), WCB (some other/unspecified WCB), or ''.

    Matches whole words, so 'WCB Labrador' is not mistaken for Alberta.
    """
    words = set(re.findall(r"[A-Z]+", (issuer or "").upper()))
    if "WSIB" in words:
        return "ON"
    if "WCB" in words or "WORKERS" in words:
        return "AB" if ({"AB", "ALBERTA", "WCBAB"} & words) else "WCB"
    if "WCBAB" in words:
        return "AB"
    return ""


def _norm_number(n: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (n or "").upper())


class _Ctx:
    def __init__(self, job: Job, sub: Subcontractor, out: List[Finding]):
        self.job, self.sub, self.out = job, sub, out
        self.who = f"{job.name} / {sub.name}"

    def add(self, severity: str, code: str, detail: str) -> None:
        self.out.append(Finding(severity, code, self.who, detail, self.job.name, self.sub.name))


def _latest(certs: List[Clearance], valid_days: int) -> Clearance:
    floor = dt.date.min

    def key(c: Clearance):
        return (c.effective_expiry(valid_days) or c.issued or floor, c.issued or floor)

    return max(certs, key=key)


def _check_dates_sane(x: _Ctx, c: Clearance, family: str, on: dt.date, valid_days: int) -> None:
    label = f"clearance {c.number or '(no number)'}"
    if c.issued and c.expires and c.expires < c.issued:
        x.add("error", "clearance_dates_inconsistent",
              f"{label}: expires {c.expires.isoformat()} is before issued {c.issued.isoformat()} (typo?)")
    elif family == "ON" and c.issued and c.expires and (c.expires - c.issued).days > valid_days:
        x.add("warn", "clearance_term_exceeds_90_days",
              f"{label}: {(c.expires - c.issued).days} days from issue to expiry; WSIB says clearances "
              f"are valid up to {valid_days} days (check the dates were copied correctly)")
    today = dt.date.today()  # real clock: a typo detector, independent of --on
    if c.issued and c.issued > today:
        x.add("warn", "clearance_issued_in_future",
              f"{label}: issued {c.issued.isoformat()} is in the future (typo?)")


def _check_gaps(x: _Ctx, certs: List[Clearance], on: dt.date, valid_days: int) -> None:
    """Dated stretches inside the job window with no valid certificate on file."""
    spans = []
    for c in certs:
        exp = c.effective_expiry(valid_days)
        if c.issued and exp and exp >= c.issued:
            spans.append((c.issued, exp))
    spans.sort()
    if len(spans) < 2:
        return
    win_start = x.job.start or dt.date.min
    win_end = x.job.end or on
    reach = spans[0][1]
    for s, e in spans[1:]:
        if s > reach + dt.timedelta(days=1):
            gap_a, gap_b = reach + dt.timedelta(days=1), s - dt.timedelta(days=1)
            if gap_b >= win_start and gap_a <= win_end:
                x.add("warn", "clearance_gap",
                      f"no valid clearance on file from {gap_a.isoformat()} to {gap_b.isoformat()}")
        reach = max(reach, e)


def _check_clearance(x: _Ctx, on: dt.date, horizon: int, valid_days: int) -> None:
    job, sub = x.job, x.sub
    certs = sub.all_clearances()
    if not certs:
        x.add("error", "clearance_missing", "no clearance certificate on file")
        return
    c = _latest(certs, valid_days)
    prov = _province(job.province)

    family = _issuer_family(c.issuer)
    wanted = prov if prov in ("ON", "AB") else ""
    if wanted and family and family != wanted and not (wanted == "AB" and family == "WCB"):
        x.add("warn", "issuer_mismatch",
              f"job is in {job.province} but clearance issuer is {c.issuer!r}")
    elif not wanted and prov:
        x.add("warn", "province_not_modelled",
              f"no clearance rules are modelled for {job.province!r}; only the dates you entered are checked")

    for cert in certs:
        _check_dates_sane(x, cert, _issuer_family(cert.issuer), on, valid_days)
    _check_gaps(x, certs, on, valid_days)

    if family == "AB" or c.covered_until is not None:
        # Alberta letters: cover work done up to the letter date
        cover = c.covered_until or c.issued
        if cover is None:
            x.add("error", "clearance_no_coverage_dates",
                  "Alberta-style clearance needs issued/covered_until dates")
            return
        horizon_date = job.end or on
        if horizon_date > cover:
            x.add("warn", "clearance_cover_lapsed",
                  f"letter covers work up to {cover.isoformat()}; work continues past it "
                  "(request a fresh clearance at the next installment)")
        return

    # The 90-day default is a WSIB rule; do not silently apply it to other boards.
    default_ok = family == "ON" or (family == "" and prov in ("", "ON"))
    expiry = c.expires or (c.effective_expiry(valid_days) if default_ok else None)
    if expiry is None:
        if c.issued and not default_ok:
            x.add("error", "clearance_no_expiry",
                  f"issuer {c.issuer!r}: no expiry given and no rule is modelled for it; enter the expiry")
        else:
            x.add("error", "clearance_no_expiry", "clearance has neither expiry nor issue date")
        return
    if expiry < on:
        x.add("error", "clearance_expired", f"clearance expired {expiry.isoformat()}")
    elif job.end and expiry < job.end:
        x.add("error", "clearance_expires_during_job",
              f"clearance expires {expiry.isoformat()} before job end {job.end.isoformat()}; "
              "a principal must hold valid clearance for the whole job")
    elif (expiry - on).days <= horizon:
        x.add("warn", "renewal_due", f"clearance expires {expiry.isoformat()} (within {horizon} days)")


def _check_insurance(x: _Ctx, on: dt.date, horizon: int) -> None:
    job, ins = x.job, x.sub.insurance
    if ins is None or not (ins.provider or ins.policy):
        x.add("error", "insurance_missing", "no insurance on file")
        return
    minimum = job.requirements.min_liability
    if minimum is not None:
        amount, problem = parse_limit(ins.coverage)
        if amount is None:
            x.add("warn", "insurance_limit_unreadable",
                  f"cannot check the C${minimum:,} minimum: coverage {ins.coverage!r} is {problem}")
        elif amount < minimum:
            x.add("error", "insurance_below_minimum",
                  f"coverage {ins.coverage!r} (C${amount:,}) is below the job minimum C${minimum:,}")
    if ins.expires is None:
        x.add("warn", "insurance_no_expiry", "insurance has no expiry date recorded")
        return
    if ins.expires < on:
        x.add("error", "insurance_expired", f"insurance expired {ins.expires.isoformat()}")
    elif job.end and ins.expires < job.end:
        x.add("warn", "insurance_expires_during_job", f"insurance expires {ins.expires.isoformat()} before job end")
    elif (ins.expires - on).days <= horizon:
        x.add("warn", "insurance_renewal_due",
              f"insurance expires {ins.expires.isoformat()} (within {horizon} days)")


def _check_licences(x: _Ctx, on: dt.date, horizon: int) -> None:
    job = x.job
    for lic in x.sub.licences:
        label = lic.name or "licence"
        if lic.expires is None:
            x.add("warn", "licence_no_expiry", f"{label}: no expiry recorded")
            continue
        if lic.expires < on:
            x.add("error", "licence_expired", f"{label} expired {lic.expires.isoformat()}")
        elif job.end and lic.expires < job.end:
            x.add("warn", "licence_expires_during_job", f"{label} expires {lic.expires.isoformat()} before job end")
        elif (lic.expires - on).days <= horizon:
            x.add("warn", "licence_renewal_due", f"{label} expires {lic.expires.isoformat()} (within {horizon} days)")


def _check_job(job: Job, out: List[Finding]) -> None:
    for note in job.notes:
        out.append(Finding("warn", "unknown_field", job.name, note, job.name, ""))
    if job.start and job.end and job.end < job.start:
        out.append(Finding("error", "job_dates_invalid", job.name,
                           f"job ends {job.end.isoformat()} before it starts {job.start.isoformat()}",
                           job.name, ""))
    seen_names: Dict[str, int] = {}
    seen_numbers: Dict[str, List[str]] = {}
    for sub in job.subs:
        key = sub.name.strip().casefold()
        seen_names[key] = seen_names.get(key, 0) + 1
        for c in sub.all_clearances():
            n = _norm_number(c.number)
            if n and sub.name not in seen_numbers.setdefault(n, []):
                seen_numbers[n].append(sub.name)
    for key, count in seen_names.items():
        if count > 1:
            name = next(s.name for s in job.subs if s.name.strip().casefold() == key)
            out.append(Finding("warn", "duplicate_sub", f"{job.name} / {name}",
                               f"{count} subs share this name; one may be a duplicate entry",
                               job.name, name))
    for n, names in seen_numbers.items():
        if len(names) > 1:
            out.append(Finding("warn", "clearance_number_shared", job.name,
                               f"clearance number {n} appears on different subs: {', '.join(names)} "
                               "(copy-paste error, or a sub using someone else's certificate)",
                               job.name, ""))


def audit(job: Job, on: Optional[dt.date] = None, horizon: int = 30,
          valid_days: int = WSIB_DEFAULT_VALID_DAYS) -> List[Finding]:
    """All compliance findings for one job as of ``on`` (default: today)."""
    on = on or dt.date.today()
    out: List[Finding] = []
    _check_job(job, out)
    for sub in job.subs:
        x = _Ctx(job, sub, out)
        _check_clearance(x, on, horizon, valid_days)
        _check_insurance(x, on, horizon)
        _check_licences(x, on, horizon)
    return out


_DURING = {"clearance_expires_during_job", "insurance_expires_during_job", "licence_expires_during_job"}


def renewals(jobs: List[Job], within: int = 30, on: Optional[dt.date] = None,
             include_during_job: bool = False) -> List[Finding]:
    """Everything across jobs that needs a renewal touch within ``within`` days.

    ``include_during_job`` also lists documents that expire before the job ends
    even when that is further out than ``within`` (off by default for
    backward compatibility).
    """
    on = on or dt.date.today()
    out: List[Finding] = []
    for job in jobs:
        out.extend(f for f in audit(job, on=on, horizon=within)
                   if "due" in f.code or "lapsed" in f.code or (include_during_job and f.code in _DURING))
    return out
