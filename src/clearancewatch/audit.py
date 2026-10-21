"""Audit a job's subcontractors against the job calendar.

Severity model: things that expose the principal to deeming/penalty risk are
errors (missing or expired clearance, lapsed coverage, expired insurance or
licence); things that are still legal today but will bite soon are warnings
(expiring during the job, renewal horizon).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import List

from .model import Job, Subcontractor, WSIB_DEFAULT_VALID_DAYS


@dataclass(frozen=True)
class Finding:
    severity: str  # error | warn
    code: str
    subject: str   # "job / sub"
    detail: str

    def as_dict(self):
        return {"severity": self.severity, "code": self.code,
                "subject": self.subject, "detail": self.detail}


def _issuer_family(issuer: str) -> str:
    u = (issuer or "").upper()
    if "WSIB" in u:
        return "ON"
    if u.startswith("WCB") or "WORKERS" in u:
        return "AB" if ("AB" in u or "ALBERTA" in u) else "WCB"
    return ""


def _check_clearance(f: List[Finding], sub: Subcontractor, job: Job,
                     on: dt.date, horizon: int, valid_days: int) -> None:
    who = f"{job.name} / {sub.name}"
    c = sub.clearance
    if c is None or (not c.issuer and not c.issued and not c.expires):
        f.append(Finding("error", "clearance_missing", who,
                         "no clearance certificate on file"))
        return

    family = _issuer_family(c.issuer)
    if job.province and family and family not in (job.province, "WCB"):
        f.append(Finding("warn", "issuer_mismatch", who,
                         f"job is in {job.province} but clearance issuer is {c.issuer!r}"))

    if family == "AB" or c.covered_until is not None:
        # Alberta letters: cover work done up to the letter date
        cover = c.covered_until or c.issued
        if cover is None:
            f.append(Finding("error", "clearance_no_coverage_dates", who,
                             "Alberta-style clearance needs issued/covered_until dates"))
            return
        horizon_date = job.end or on
        if horizon_date > cover:
            f.append(Finding("warn", "clearance_cover_lapsed", who,
                             f"letter covers work up to {cover.isoformat()}; work continues past it "
                             "(request a fresh clearance at the next installment)"))
        return

    expiry = c.effective_expiry(valid_days)
    if expiry is None:
        f.append(Finding("error", "clearance_no_expiry", who,
                         "clearance has neither expiry nor issue date"))
        return
    if expiry < on:
        f.append(Finding("error", "clearance_expired", who,
                         f"clearance expired {expiry.isoformat()}"))
    elif job.end and expiry < job.end:
        f.append(Finding("error", "clearance_expires_during_job", who,
                         f"clearance expires {expiry.isoformat()} before job end {job.end.isoformat()}; "
                         "a principal must hold valid clearance for the whole job"))
    elif (expiry - on).days <= horizon:
        f.append(Finding("warn", "renewal_due", who,
                         f"clearance expires {expiry.isoformat()} (within {horizon} days)"))


def _check_insurance(f: List[Finding], sub: Subcontractor, job: Job,
                     on: dt.date, horizon: int) -> None:
    who = f"{job.name} / {sub.name}"
    ins = sub.insurance
    if ins is None or not (ins.provider or ins.policy):
        f.append(Finding("error", "insurance_missing", who, "no insurance on file"))
        return
    if ins.expires is None:
        f.append(Finding("warn", "insurance_no_expiry", who, "insurance has no expiry date recorded"))
        return
    if ins.expires < on:
        f.append(Finding("error", "insurance_expired", who,
                         f"insurance expired {ins.expires.isoformat()}"))
    elif job.end and ins.expires < job.end:
        f.append(Finding("warn", "insurance_expires_during_job", who,
                         f"insurance expires {ins.expires.isoformat()} before job end"))
    elif (ins.expires - on).days <= horizon:
        f.append(Finding("warn", "insurance_renewal_due", who,
                         f"insurance expires {ins.expires.isoformat()} (within {horizon} days)"))


def _check_licences(f: List[Finding], sub: Subcontractor, job: Job, on: dt.date, horizon: int) -> None:
    who = f"{job.name} / {sub.name}"
    for lic in sub.licences:
        label = lic.name or "licence"
        if lic.expires is None:
            f.append(Finding("warn", "licence_no_expiry", who, f"{label}: no expiry recorded"))
            continue
        if lic.expires < on:
            f.append(Finding("error", "licence_expired", who,
                             f"{label} expired {lic.expires.isoformat()}"))
        elif job.end and lic.expires < job.end:
            f.append(Finding("warn", "licence_expires_during_job", who,
                             f"{label} expires {lic.expires.isoformat()} before job end"))
        elif (lic.expires - on).days <= horizon:
            f.append(Finding("warn", "licence_renewal_due", who,
                             f"{label} expires {lic.expires.isoformat()} (within {horizon} days)"))


def audit(job: Job, on: dt.date | None = None, horizon: int = 30,
          valid_days: int = WSIB_DEFAULT_VALID_DAYS) -> List[Finding]:
    """All compliance findings for one job as of ``on`` (default: today)."""
    on = on or dt.date.today()
    out: List[Finding] = []
    for sub in job.subs:
        _check_clearance(out, sub, job, on, horizon, valid_days)
        _check_insurance(out, sub, job, on, horizon)
        _check_licences(out, sub, job, on, horizon)
    return out


def renewals(jobs: List[Job], within: int = 30, on: dt.date | None = None) -> List[Finding]:
    """Everything across jobs that needs a renewal touch within ``within`` days."""
    on = on or dt.date.today()
    out: List[Finding] = []
    for job in jobs:
        out.extend(f for f in audit(job, on=on, horizon=within) if "due" in f.code or "lapsed" in f.code)
    return out
