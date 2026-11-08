"""Turn a spreadsheet export (CSV) into a jobs file.

A clerk usually keeps this in Excel: one row per subcontractor. ``import-csv`` reads
that, groups rows by job, and writes the JSON that ``audit`` reads. Nothing is guessed:
an unknown column, a date that is not YYYY-MM-DD or a yes/no that is not clear stops
the import with the row number.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any, Dict, List, Tuple

MAX_ROWS = 100_000

_JOB = ("job", "province", "start", "end")
_SUB = ("sub", "trade", "sub_start", "supply_only", "clearance_exempt")
_CLR = ("clearance_issuer", "clearance_number", "clearance_issued", "clearance_expires",
        "clearance_covered_until", "clearance_status")
_INS = ("insurance_provider", "insurance_policy", "insurance_coverage", "insurance_expires",
        "insurance_additional_insured", "insurance_waiver_of_subrogation", "insurance_primary_noncontributory")
_LIC = ("licence_name", "licence_number", "licence_authority", "licence_expires")
_REQ = ("min_liability", "require_additional_insured", "require_waiver_of_subrogation",
        "require_primary_noncontributory")
COLUMNS = _JOB + _SUB + _CLR + _INS + _LIC + _REQ
_BOOLS = {"supply_only", "insurance_additional_insured", "insurance_waiver_of_subrogation",
          "insurance_primary_noncontributory", "require_additional_insured", "require_waiver_of_subrogation",
          "require_primary_noncontributory"}
_YES = {"true", "yes", "y", "1"}
_NO = {"false", "no", "n", "0"}


class ImportError_(ValueError):
    """A problem with the spreadsheet, in plain words, naming the row."""


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", h.strip().lower()).strip("_")


def _flag(value: str, col: str, row: int) -> bool:
    v = value.strip().lower()
    if v in _YES:
        return True
    if v in _NO:
        return False
    raise ImportError_(f"row {row}, column {col}: expected yes or no, got {value!r}")


def rows_to_jobs(text: str) -> Tuple[List[Dict[str, Any]], int]:
    """Parse CSV text; return (jobs as plain dicts, number of data rows)."""
    reader = csv.reader(io.StringIO(text))
    try:
        header_raw = next(reader)
    except StopIteration:
        raise ImportError_("the CSV file is empty") from None
    header = [_norm(h) for h in header_raw]
    unknown = [h for h in header if h and h not in COLUMNS]
    if unknown:
        raise ImportError_("unknown column(s): " + ", ".join(repr(h) for h in unknown[:8])
                           + ". Allowed columns: " + ", ".join(COLUMNS))
    dupes = sorted({h for h in header if h and header.count(h) > 1})
    if dupes:
        raise ImportError_("column(s) appear twice: " + ", ".join(dupes))
    for need in ("job", "sub"):
        if need not in header:
            raise ImportError_(f"the CSV needs a {need!r} column")
    jobs: Dict[str, Dict[str, Any]] = {}
    subs: Dict[Tuple[str, str], Dict[str, Any]] = {}
    n = 0
    for n, raw in enumerate(reader, start=2):
        if n - 1 > MAX_ROWS:
            raise ImportError_(f"more than {MAX_ROWS} rows")
        if not any(c.strip() for c in raw):
            continue
        if len(raw) > len(header):
            raise ImportError_(f"row {n}: {len(raw)} cells but the header has {len(header)}")
        r = {h: (raw[i].strip() if i < len(raw) else "") for i, h in enumerate(header) if h}
        jname, sname = r.get("job", ""), r.get("sub", "")
        if not jname or not sname:
            raise ImportError_(f"row {n}: both job and sub must be filled in")
        job = jobs.get(jname)
        if job is None:
            job = {"name": jname, "subs": []}
            for k in ("province", "start", "end"):
                if r.get(k):
                    job[k] = r[k]
            req: Dict[str, Any] = {}
            if r.get("min_liability"):
                req["min_liability"] = r["min_liability"]
            for k in ("additional_insured", "waiver_of_subrogation", "primary_noncontributory"):
                if r.get("require_" + k):
                    req[k] = _flag(r["require_" + k], "require_" + k, n)
            if req:
                job["requirements"] = req
            jobs[jname] = job
        else:
            for k in ("province", "start", "end", "min_liability"):
                if r.get(k) and r[k] != (job.get(k) if k != "min_liability" else job.get("requirements", {}).get(k)):
                    raise ImportError_(f"row {n}: {k} {r[k]!r} differs from the earlier row for job {jname!r}")
        key = (jname, sname)
        clr = {k[len("clearance_"):]: r[k] for k in _CLR if r.get(k)}
        lic = {k[len("licence_"):]: r[k] for k in _LIC if r.get(k)}
        sub = subs.get(key)
        if sub is None:
            sub = {"name": sname}
            for src, dst in (("trade", "trade"), ("sub_start", "start"), ("clearance_exempt", "clearance_exempt")):
                if r.get(src):
                    sub[dst] = r[src]
            if r.get("supply_only"):
                sub["supply_only"] = _flag(r["supply_only"], "supply_only", n)
            if clr:
                sub["clearance"] = clr
            ins = {k[len("insurance_"):]: r[k] for k in _INS if r.get(k)}
            for k in ("additional_insured", "waiver_of_subrogation", "primary_noncontributory"):
                if k in ins:
                    ins[k] = _flag(ins[k], "insurance_" + k, n)  # type: ignore[assignment]
            if ins:
                sub["insurance"] = ins
            subs[key] = sub
            job["subs"].append(sub)
        elif clr:  # a later row for the same sub carries an earlier certificate (renewal history)
            if "clearance" not in sub:
                sub["clearance"] = clr
            else:
                sub.setdefault("clearances", []).append(clr)
        if lic:
            sub.setdefault("licences", []).append(lic)
    if not jobs:
        raise ImportError_("the CSV has a header but no rows")
    return list(jobs.values()), n - 1
