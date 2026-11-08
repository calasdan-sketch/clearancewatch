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
from functools import lru_cache
from typing import Dict, List, Optional

from .model import Clearance, Job, Subcontractor, WSIB_DEFAULT_VALID_DAYS
from .money import mentions_excess, parse_limits, primary_limit


@dataclass(frozen=True)
class Finding:
    severity: str  # error | warn | info (info = a note for a human; never fails a run)
    code: str
    subject: str   # "job / sub"
    detail: str
    job: str = ""
    sub: str = ""
    due: Optional[dt.date] = None  # the date a renewal/expiry falls on, when the finding has one

    def as_dict(self):
        out = {"severity": self.severity, "code": self.code,
               "subject": self.subject, "detail": self.detail,
               "job": self.job, "sub": self.sub}
        if self.due is not None:
            out["due"] = self.due.isoformat()
        return out


_PROVINCES = {"ON": "ON", "ONTARIO": "ON", "AB": "AB", "ALBERTA": "AB", "MB": "MB", "MANITOBA": "MB"}
_LETTER_PROVINCES = ("AB", "MB")  # boards whose clearance is a dated letter, not a certificate with an expiry
_BOARD = {"AB": "WCB Alberta", "MB": "WCB Manitoba"}


@lru_cache(maxsize=1024)
def _province(value: str) -> str:
    """Normalised province for the two modelled jurisdictions, else upper-cased text."""
    v = (value or "").strip().upper()
    return _PROVINCES.get(v, v)


@lru_cache(maxsize=1024)
def _issuer_family(issuer: str) -> str:
    """ON (WSIB), AB (WCB Alberta), MB (WCB Manitoba), WCB (some other/unspecified WCB), or ''.

    Matches whole words, so 'WCB Labrador' is not mistaken for Alberta.
    """
    words = set(re.findall(r"[A-Z]+", (issuer or "").upper()))
    if "WSIB" in words:
        return "ON"
    if "WCB" in words or "WORKERS" in words:
        if {"AB", "ALBERTA", "WCBAB"} & words:
            return "AB"
        return "MB" if ({"MB", "MANITOBA", "WCBMB"} & words) else "WCB"
    if "WCBAB" in words:
        return "AB"
    if "WCBMB" in words:
        return "MB"
    return ""


def _eff_family(c: Clearance, prov: str) -> str:
    """The board a certificate belongs to. A bare "WCB" (or no issuer) on an Alberta/Manitoba job
    with no stated expiry is read as that province's letter; anything else keeps what the issuer says."""
    fam = _issuer_family(c.issuer)
    if fam in ("", "WCB") and prov in _LETTER_PROVINCES and c.expires is None:
        return prov
    return fam


def _is_letter(c: Clearance, prov: str) -> bool:
    return _eff_family(c, prov) in _LETTER_PROVINCES or c.covered_until is not None


def _status_kind(status: str) -> str:
    """'' (not given), good, deemed_worker, not_good (deemed/default or negated) or unknown."""
    n = re.sub(r"[^a-z]+", " ", (status or "").lower()).strip()
    if not n:
        return ""
    if "default" in n or re.search(r"\b(not|no|without)\b", n):
        return "not_good"
    if "deemed" in n:
        return "deemed_worker"
    if "good standing" in n:
        return "good"
    return "unknown"


def _names(names: List[str], limit: int = 5) -> str:
    shown = ", ".join(names[:limit])
    return shown + (f" and {len(names) - limit} more" if len(names) > limit else "")


@lru_cache(maxsize=4096)
def _norm_number(n: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (n or "").upper())


class _Ctx:
    def __init__(self, job: Job, sub: Subcontractor, out: List[Finding]):
        self.job, self.sub, self.out = job, sub, out
        self.who = f"{job.name} / {sub.name}"

    def add(self, severity: str, code: str, detail: str, due: Optional[dt.date] = None) -> None:
        self.out.append(Finding(severity, code, self.who, detail, self.job.name, self.sub.name, due))


def _expiry(c: Clearance, prov: str, valid_days: int) -> Optional[dt.date]:
    """Stated expiry, or issued + 90 days only where that is a WSIB rule (never for other boards)."""
    family = _issuer_family(c.issuer)
    if family == "ON" or (family == "" and prov in ("", "ON")):
        return c.effective_expiry(valid_days)
    return c.expires or c.covered_until


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
    prov = _province(x.job.province)
    for c in certs:
        exp = _expiry(c, prov, valid_days)
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


def _check_status(x: _Ctx, c: Clearance) -> None:
    """The standing WCB Manitoba prints on a clearance letter (good standing / deemed worker / deemed/default)."""
    kind = _status_kind(c.status)
    if kind == "deemed_worker":
        x.add("warn", "clearance_status_deemed_worker",
              f"status {c.status!r}: WCB Manitoba treats this firm as your worker, so you report the labour "
              "portion of its contract in your payroll and report its injuries (you may not deduct that cost from it)")
    elif kind == "not_good":
        x.add("error", "clearance_status_not_good",
              f"status {c.status!r}: the firm is not in good standing with its workers' compensation board; "
              "you may be liable for its assessments. Resolve before more work or payment")
    elif kind == "unknown":
        x.add("warn", "clearance_status_unrecognised",
              f"status {c.status!r} is not one of: good standing, deemed worker, deemed/default (read the letter)")


def _check_started_before_clearance(x: _Ctx, certs: List[Clearance], prov: str) -> None:
    """WCB Alberta and WCB Manitoba both say to get the clearance before work starts."""
    start = x.sub.start
    if start is None or not (prov in _LETTER_PROVINCES or any(_is_letter(c, prov) for c in certs)):
        return
    dated = [c.issued for c in certs if c.issued]
    if dated and min(dated) > start:
        x.add("warn", "clearance_after_work_started",
              f"work started {start.isoformat()} but the earliest clearance on file is dated {min(dated).isoformat()}; "
              "the regulators say to get a clearance before work starts (if an earlier one exists, add it to "
              "clearances)")


def _check_clearance(x: _Ctx, on: dt.date, horizon: int, valid_days: int, strict_whole_job: bool = False) -> None:
    job, sub = x.job, x.sub
    certs = sub.all_clearances()
    if not certs:
        if sub.supply_only:
            x.add("info", "clearance_supply_only",
                  "recorded as supplying material only. WCB Manitoba says clearance letters are not required for "
                  "those firms; confirm that is true for this sub and province before relying on it")
            return
        if sub.clearance_exempt:
            x.add("info", "clearance_exempt",
                  f"no clearance on file; recorded as not needed because: {sub.clearance_exempt}. "
                  "Confirm that with the regulator, not with the sub")
            return
        x.add("error", "clearance_missing", "no clearance certificate on file")
        return
    c = _latest(certs, valid_days)
    prov = _province(job.province)

    family = _issuer_family(c.issuer)
    wanted = prov if prov in ("ON", "AB", "MB") else ""
    if wanted and family and family != wanted and not (wanted in _LETTER_PROVINCES and family == "WCB"):
        x.add("warn", "issuer_mismatch",
              f"job is in {job.province} but clearance issuer is {c.issuer!r}")
    elif not wanted and prov:
        x.add("warn", "province_not_modelled",
              f"no clearance rules are modelled for {job.province!r}; only the dates you entered are checked")

    for cert in certs:
        _check_dates_sane(x, cert, _issuer_family(cert.issuer), on, valid_days)
    _check_gaps(x, certs, on, valid_days)
    _check_status(x, c)
    _check_started_before_clearance(x, certs, prov)

    if _is_letter(c, prov):
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
        # No 90-day WSIB clearance, even one requested today, can span the rest of a longer job,
        # so an error would stay unresolvable until the last certificate: warn instead
        # (strict_whole_job restores the error).
        impossible = not strict_whole_job and default_ok and (job.end - on).days > valid_days
        if impossible and (expiry - on).days <= horizon:
            x.add("warn", "renewal_due", f"clearance expires {expiry.isoformat()} (within {horizon} days)", expiry)
        elif impossible:
            x.add("warn", "clearance_expires_during_job",
                  f"clearance expires {expiry.isoformat()} before job end {job.end.isoformat()}; the job is "
                  f"longer than one {valid_days}-day clearance, so plan a renewal before that date", expiry)
        else:
            x.add("error", "clearance_expires_during_job",
                  f"clearance expires {expiry.isoformat()} before job end {job.end.isoformat()}; "
                  "house policy: hold a valid clearance for the whole job", expiry)
    elif (expiry - on).days <= horizon:
        x.add("warn", "renewal_due", f"clearance expires {expiry.isoformat()} (within {horizon} days)", expiry)


def _check_payments(x: _Ctx, on: dt.date, valid_days: int) -> None:
    """Planned payment dates vs the clearance on file (WCB Alberta and Manitoba: get one before paying)."""
    certs = x.sub.all_clearances()
    if not certs or not x.job.payment_dates:
        return
    prov = _province(x.job.province)
    for pay in sorted(set(x.job.payment_dates)):
        if pay < on:
            continue  # already paid: nothing left to act on
        ok = False
        latest_cover: Optional[dt.date] = None
        board = ""
        for c in certs:
            if _is_letter(c, prov):
                cover = c.covered_until or c.issued
                if cover is not None and (latest_cover is None or cover > latest_cover):
                    latest_cover = cover
                    board = _BOARD.get(_eff_family(c, prov), "the board")
                if cover is not None and cover >= pay:
                    ok = True
            else:
                exp = _expiry(c, prov, valid_days)
                if exp is not None and exp >= pay and (c.issued is None or c.issued <= pay):
                    ok = True
        if not ok:
            extra = (f" (latest letter is dated {latest_cover.isoformat()}; {board} does not state how long "
                     "a letter stays good, so request a fresh one before paying)") if latest_cover else ""
            x.add("warn", "clearance_not_valid_at_payment",
                  f"planned payment {pay.isoformat()} is after the clearance on file stops covering it{extra}")


def _check_insurance(x: _Ctx, on: dt.date, horizon: int) -> None:
    job, ins = x.job, x.sub.insurance
    if ins is None or not (ins.provider or ins.policy):
        x.add("error", "insurance_missing", "no insurance on file")
        return
    minimum = job.requirements.min_liability
    if minimum is not None:
        amounts, problem = parse_limits(ins.coverage)
        amount = primary_limit(amounts) if amounts else None
        if amount is None:
            x.add("warn", "insurance_limit_unreadable",
                  f"cannot check the C${minimum:,} minimum: coverage {ins.coverage!r} is {problem}")
        elif amount < minimum:
            labelled = any(lab for _, lab in amounts)
            if len(amounts) > 1 and not labelled and any(a >= minimum for a, _ in amounts):
                x.add("warn", "insurance_limit_ambiguous",
                      f"coverage {ins.coverage!r} lists several amounts and the first (C${amount:,}) is below the "
                      f"C${minimum:,} minimum; cannot tell which is the per-occurrence limit. Read the certificate")
            elif mentions_excess(ins.coverage):
                x.add("warn", "insurance_limit_includes_umbrella",
                      f"coverage {ins.coverage!r} (primary C${amount:,}) is below the C${minimum:,} minimum but "
                      "mentions an umbrella/excess layer; the tool does not add layers together. Check whether "
                      "your contract lets umbrella or excess count toward the minimum")
            else:
                x.add("error", "insurance_below_minimum",
                      f"coverage {ins.coverage!r} (C${amount:,}) is below the job minimum C${minimum:,}")
    req = job.requirements
    for attr, label in (("additional_insured", "additional insured"),
                        ("waiver_of_subrogation", "waiver of subrogation"),
                        ("primary_noncontributory", "primary and non-contributory wording")):
        if getattr(req, attr):
            got = getattr(ins, attr)
            if got is False:
                x.add("error", "insurance_endorsement_missing", f"contract requires {label}; certificate says no")
            elif got is None:
                x.add("warn", "insurance_endorsement_unconfirmed",
                      f"contract requires {label}; nothing recorded for this certificate (read the endorsement)")
    if ins.expires is None:
        x.add("warn", "insurance_no_expiry", "insurance has no expiry date recorded")
        return
    if ins.expires < on:
        x.add("error", "insurance_expired", f"insurance expired {ins.expires.isoformat()}")
    elif job.end and ins.expires < job.end:
        x.add("warn", "insurance_expires_during_job", f"insurance expires {ins.expires.isoformat()} before job end",
              ins.expires)
    elif (ins.expires - on).days <= horizon:
        x.add("warn", "insurance_renewal_due",
              f"insurance expires {ins.expires.isoformat()} (within {horizon} days)", ins.expires)


def _check_licences(x: _Ctx, on: dt.date, horizon: int) -> None:
    job = x.job
    needle = job.requirements.required_licences.get(x.sub.trade.strip().casefold())
    if needle and not any(needle in (lic.name or "").casefold() for lic in x.sub.licences):
        x.add("error", "licence_missing", f"trade {x.sub.trade!r} needs a licence matching {needle!r}; none on file")
    for lic in x.sub.licences:
        label = lic.name or "licence"
        if lic.expires is None:
            x.add("warn", "licence_no_expiry", f"{label}: no expiry recorded")
            continue
        if lic.expires < on:
            x.add("error", "licence_expired", f"{label} expired {lic.expires.isoformat()}")
        elif job.end and lic.expires < job.end:
            x.add("warn", "licence_expires_during_job", f"{label} expires {lic.expires.isoformat()} before job end",
                  lic.expires)
        elif (lic.expires - on).days <= horizon:
            x.add("warn", "licence_renewal_due", f"{label} expires {lic.expires.isoformat()} (within {horizon} days)",
                  lic.expires)


def _check_job(job: Job, out: List[Finding]) -> None:
    for note in job.notes:
        out.append(Finding("warn", "unknown_field", job.name, note, job.name, ""))
    if job.start and job.end and job.end < job.start:
        out.append(Finding("error", "job_dates_invalid", job.name,
                           f"job ends {job.end.isoformat()} before it starts {job.start.isoformat()}",
                           job.name, ""))
    if not job.subs:
        out.append(Finding("info", "job_has_no_subs", job.name, "no subcontractors listed, so nothing was checked",
                           job.name, ""))
    seen_names: Dict[str, int] = {}
    seen_numbers: Dict[str, Dict[str, None]] = {}
    for sub in job.subs:
        key = sub.name.strip().casefold()
        seen_names[key] = seen_names.get(key, 0) + 1
        for c in sub.all_clearances():
            n = _norm_number(c.number)
            if n:
                seen_numbers.setdefault(n, {})[sub.name] = None
    for key, count in seen_names.items():
        if count > 1:
            name = next(s.name for s in job.subs if s.name.strip().casefold() == key)
            out.append(Finding("warn", "duplicate_sub", f"{job.name} / {name}",
                               f"{count} subs share this name; one may be a duplicate entry",
                               job.name, name))
    for n, names in seen_numbers.items():
        if len(names) > 1:
            out.append(Finding("warn", "clearance_number_shared", job.name,
                               f"clearance number {n} appears on different subs: {_names(sorted(names))} "
                               "(copy-paste error, or a sub using someone else's certificate)",
                               job.name, ""))


def check_jobs(jobs: List[Job]) -> List[Finding]:
    """Checks that need the whole file: two jobs with one name make reports and baselines ambiguous."""
    counts: Dict[str, int] = {}
    for j in jobs:
        counts[j.name.strip().casefold()] = counts.get(j.name.strip().casefold(), 0) + 1
    out: List[Finding] = []
    for key, n in counts.items():
        if n > 1:
            name = next(j.name for j in jobs if j.name.strip().casefold() == key)
            out.append(Finding("warn", "duplicate_job", name, f"{n} jobs share this name, so findings and --baseline "
                               "cannot tell them apart", name, ""))
    return out


def audit(job: Job, on: Optional[dt.date] = None, horizon: int = 30,
          valid_days: int = WSIB_DEFAULT_VALID_DAYS, strict_whole_job: bool = False) -> List[Finding]:
    """All compliance findings for one job as of ``on`` (default: today).

    ``strict_whole_job`` keeps "clearance expires during the job" an error even when the
    job is longer than one 90-day clearance could ever cover (default: a warning then).
    """
    on = on or dt.date.today()
    out: List[Finding] = []
    _check_job(job, out)
    for sub in job.subs:
        x = _Ctx(job, sub, out)
        _check_clearance(x, on, horizon, valid_days, strict_whole_job)
        _check_payments(x, on, valid_days)
        _check_insurance(x, on, horizon)
        _check_licences(x, on, horizon)
    return out


_DURING = {"clearance_expires_during_job", "insurance_expires_during_job", "licence_expires_during_job"}


def renewals(jobs: List[Job], within: int = 30, on: Optional[dt.date] = None,
             include_during_job: bool = False, strict_whole_job: bool = False) -> List[Finding]:
    """Everything across jobs that needs a renewal touch within ``within`` days.

    ``include_during_job`` also lists documents that expire before the job ends
    even when that is further out than ``within`` (off by default for
    backward compatibility).
    """
    on = on or dt.date.today()
    out: List[Finding] = []
    for job in jobs:
        found = audit(job, on=on, horizon=within, strict_whole_job=strict_whole_job)
        out.extend(f for f in found
                   if "due" in f.code or "lapsed" in f.code or f.code == "clearance_not_valid_at_payment"
                   or (include_during_job and f.code in _DURING))
    return out
