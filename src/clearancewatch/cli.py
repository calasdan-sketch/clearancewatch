"""clearancewatch CLI: audit jobs.json for compliance gaps.

Exit codes: 0 = pass, 1 = findings at/above --fail-on, 2 = bad input or usage
(so a cron job can tell "your data is broken" from "a sub is out of
compliance"). Not legal advice.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import sys
from typing import Dict, List, Tuple

from . import __version__
from .audit import Finding, audit, renewals
from .model import DataError, Job, parse_date
from .safe import clean, csv_cell, md_cell

MAX_BYTES = 20 * 1024 * 1024  # a jobs file bigger than this is almost certainly wrong

# What to ask the sub for, per finding code (shown in --format md).
ACTIONS = {
    "clearance_missing": "Request a clearance certificate from the sub's workers'-comp board",
    "clearance_expired": "Request a fresh clearance before any further payment",
    "clearance_expires_during_job": "Request a renewed clearance; diarise it before the expiry date",
    "renewal_due": "Request a renewed clearance now",
    "clearance_cover_lapsed": "Request a fresh clearance letter before the next payment",
    "clearance_gap": "Ask the sub for the certificate that covers the gap, or note the gap in the file",
    "clearance_no_expiry": "Enter the expiry date from the certificate",
    "clearance_no_coverage_dates": "Enter issued/covered_until from the letter",
    "clearance_dates_inconsistent": "Re-check the dates against the certificate",
    "clearance_term_exceeds_90_days": "Re-check the dates against the certificate",
    "clearance_issued_in_future": "Re-check the issue date",
    "clearance_number_shared": "Verify each sub's own certificate number",
    "issuer_mismatch": "Confirm this is the right board for the job's province",
    "province_not_modelled": "Check this province's rules yourself; only dates were checked",
    "insurance_missing": "Request a certificate of insurance",
    "insurance_expired": "Request a current certificate of insurance",
    "insurance_expires_during_job": "Request a renewal certificate",
    "insurance_renewal_due": "Request a renewal certificate",
    "insurance_below_minimum": "Ask for higher limits or an exception from the project owner",
    "insurance_limit_unreadable": "Enter the limit as a number, e.g. 2000000",
    "insurance_no_expiry": "Enter the policy expiry date",
    "licence_expired": "Request the renewed licence",
    "licence_expires_during_job": "Request the renewed licence",
    "licence_renewal_due": "Request the renewed licence",
    "licence_no_expiry": "Enter the licence expiry date",
    "job_dates_invalid": "Fix the job start/end dates",
    "duplicate_sub": "Merge or rename the duplicate entry",
    "unknown_field": "Fix the field name; the value was not used",
}


def load_jobs(path: str) -> Tuple[List[Job], int]:
    """Read and validate a jobs file. Raises SystemExit(2) with a clear message."""
    def die(msg: str):
        sys.stderr.write(f"clearancewatch: {clean(msg, 600)}\n")
        raise SystemExit(2)

    try:
        size = os.path.getsize(path)
        if size > MAX_BYTES:
            die(f"{path}: file is {size} bytes (limit {MAX_BYTES})")
        with open(path, encoding="utf-8-sig") as fh:  # utf-8-sig tolerates Excel/Notepad BOMs
            data = json.load(fh)
    except FileNotFoundError:
        die(f"not found: {path}")
    except IsADirectoryError:
        die(f"{path} is a folder, not a JSON file")
    except PermissionError:
        die(f"cannot read {path}: permission denied")
    except UnicodeDecodeError:
        die(f"{path}: not UTF-8 text (save the file as UTF-8)")
    except json.JSONDecodeError as e:
        die(f"invalid JSON: {e}")
    except RecursionError:
        die(f"{path}: JSON is nested too deeply")
    except OSError as e:
        die(f"cannot read {path}: {e.strerror or e}")
    if isinstance(data, dict):
        if "jobs" not in data and not ({"name", "subs", "subcontractors"} & set(data)):
            die("expected a job object (name, subs...) or {\"jobs\": [...]}; this looks like something else")
        data = data.get("jobs", [data])
    if not isinstance(data, list):
        die("expected a list of jobs or {\"jobs\": [...]}")
    if not data:
        die("no jobs in file (an empty file would silently pass; add at least one job)")
    try:
        return [Job.from_dict(d, f"jobs[{i}]") for i, d in enumerate(data)], len(data)
    except DataError as e:
        die(str(e))
    raise AssertionError  # pragma: no cover


def _group(findings: List[Finding]) -> Dict[str, List[Finding]]:
    out: Dict[str, List[Finding]] = {}
    for f in findings:
        out.setdefault(f.subject, []).append(f)
    return out


def render_text(findings, errors, warns) -> str:
    lines = [f"{f.severity.upper():5} {f.code:28} {clean(f.subject)}: {clean(f.detail, 600)}" for f in findings]
    lines.append(f"\n{len(errors)} error(s), {len(warns)} warning(s) — {'FAIL' if errors else 'PASS'}")
    return "\n".join(lines)


def render_csv(findings) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["severity", "code", "job", "sub", "detail", "action"])
    for f in findings:
        w.writerow([f.severity, f.code, csv_cell(f.job), csv_cell(f.sub), csv_cell(f.detail),
                    ACTIONS.get(f.code, "")])
    return buf.getvalue().rstrip("\n")


def render_md(findings, errors, warns) -> str:
    """A chase list grouped by sub, ready to paste into an email or ticket."""
    out = ["# Subcontractor compliance chase list", "",
           f"{len(errors)} error(s), {len(warns)} warning(s). Not legal advice.", ""]
    for who, items in _group(findings).items():
        out += [f"## {md_cell(who)}", "", "| Severity | Issue | What to do |", "|---|---|---|"]
        for f in sorted(items, key=lambda f: (f.severity != "error", f.code)):
            out.append(f"| {f.severity} | {md_cell(f.detail)} | {md_cell(ACTIONS.get(f.code, ''))} |")
        out.append("")
    if not findings:
        out.append("Nothing to chase.")
    return "\n".join(out).rstrip()


def _non_negative(s: str) -> int:
    v = int(s)
    if v < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return v


def _date_arg(s: str) -> dt.date:
    try:
        return parse_date(s, "--on")  # type: ignore[return-value]
    except DataError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def _common(p: argparse.ArgumentParser, within_default: int) -> None:
    p.add_argument("jobs", help="jobs JSON file (list, or {\"jobs\": [...]})")
    p.add_argument("--on", metavar="YYYY-MM-DD", type=_date_arg, help="audit date (default: today)")
    p.add_argument("--within", type=_non_negative, default=within_default,
                   help=f"renewal horizon in days (default {within_default})")
    p.add_argument("--json", action="store_true", help="same as --format json")
    p.add_argument("--format", choices=["text", "json", "csv", "md"], default="text")


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(
        prog="clearancewatch",
        description="Audit subcontractor clearance/insurance/licence coverage against job calendars. "
                    "Not legal advice. Exit 0 pass, 1 findings, 2 bad input.",
    )
    ap.add_argument("--version", action="version", version=f"clearancewatch {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("audit", help="full audit; exit 1 when any error-severity finding exists")
    _common(a, 30)
    a.add_argument("--fail-on", choices=["error", "warn", "never"], default="error",
                   help="lowest severity that makes the exit code 1 (default error)")

    r = sub.add_parser("renewals", help="only what's due soon (exit 0 unless --fail-on warn/error says otherwise)")
    _common(r, 30)
    r.add_argument("--fail-on", choices=["error", "warn", "never"], default="error")
    r.add_argument("--include-during-job", action="store_true",
                   help="also list documents that expire before the job ends, however far out")

    args = ap.parse_args(argv)
    jobs, _n = load_jobs(args.jobs)

    if args.cmd == "audit":
        findings = [f for job in jobs for f in audit(job, on=args.on, horizon=args.within)]
    else:
        findings = renewals(jobs, within=args.within, on=args.on, include_during_job=args.include_during_job)

    errors = [f for f in findings if f.severity == "error"]
    warns = [f for f in findings if f.severity == "warn"]
    fmt = "json" if args.json else args.format
    if fmt == "json":
        print(json.dumps({"errors": len(errors), "warnings": len(warns), "jobs": len(jobs),
                          "findings": [f.as_dict() for f in findings]}, indent=2))
    elif fmt == "csv":
        print(render_csv(findings))
    elif fmt == "md":
        print(render_md(findings, errors, warns))
    else:
        print(render_text(findings, errors, warns))
    if args.fail_on == "never":
        return 0
    if args.fail_on == "warn":
        return 1 if findings else 0
    return 1 if errors else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
