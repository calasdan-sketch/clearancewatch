"""clearancewatch CLI: audit jobs.json for compliance gaps.

Exit codes: 0 = pass, 1 = findings at/above --fail-on, 2 = bad input or usage,
3 = internal error (a bug in clearancewatch, never a finding) -- so a cron job
can tell "your data is broken" from "a sub is out of compliance". Not legal advice.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import os
import sys
from typing import Dict, List, Tuple

from . import __version__
from .audit import Finding, audit, renewals
from .model import DataError, Job, parse_date
from .safe import clean, csv_cell, md_cell
from .schema import TEMPLATE, jobs_schema

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
    "clearance_not_valid_at_payment": "Request a clearance that covers the payment date before releasing payment",
    "insurance_limit_ambiguous": "Read the certificate and enter the per-occurrence limit as a number",
    "insurance_endorsement_missing": "Ask the broker for the required endorsement",
    "insurance_endorsement_unconfirmed": "Check the endorsement on the certificate and record true or false",
    "licence_missing": "Request a copy of the required licence",
    "clearance_exempt": "Confirm the exemption with the regulator and keep the answer on file",
}
_RANK = {"error": 0, "warn": 1, "info": 2}


def _read_json(path: str):
    """Parse a JSON file (or stdin for ``-``), size-capped, BOM-tolerant."""
    if path == "-":
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise OSError(f"input is larger than the {MAX_BYTES} byte limit")
        return json.loads(raw.decode("utf-8-sig"))
    size = os.path.getsize(path)
    if size > MAX_BYTES:
        raise OSError(f"{path}: file is {size} bytes (limit {MAX_BYTES})")
    with open(path, encoding="utf-8-sig") as fh:  # utf-8-sig tolerates Excel/Notepad BOMs
        return json.load(fh)


def load_jobs(path: str) -> Tuple[List[Job], int]:
    """Read and validate a jobs file. Raises SystemExit(2) with a clear message."""
    def die(msg: str):
        sys.stderr.write(f"clearancewatch: {clean(msg, 600)}\n")
        raise SystemExit(2)

    try:
        data = _read_json(path)
    except FileNotFoundError:
        die(f"not found: {path}")
    except IsADirectoryError:
        die(f"{path} is a folder, not a JSON file")
    except PermissionError:
        die(f"cannot read {path}: permission denied")
    except UnicodeDecodeError:
        die(f"{path}: not UTF-8 text (save the file as UTF-8)")
    except ValueError as e:  # JSONDecodeError, and Python's own limit on absurdly long integers
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


def render_text(findings, errors, warns, extra: str = "") -> str:
    lines = [f"{f.severity.upper():5} {f.code:28} {clean(f.subject)}: {clean(f.detail, 600)}" for f in findings]
    notes = len(findings) - len(errors) - len(warns)
    tail = f", {notes} note(s)" if notes else ""
    lines.append(f"\n{len(errors)} error(s), {len(warns)} warning(s){tail} — {'FAIL' if errors else 'PASS'}{extra}")
    return "\n".join(lines)


def render_csv(findings) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["severity", "code", "job", "sub", "detail", "action"])
    for f in findings:
        w.writerow([f.severity, f.code, csv_cell(f.job), csv_cell(f.sub), csv_cell(f.detail),
                    ACTIONS.get(f.code, "")])
    return buf.getvalue().rstrip("\n")


def render_md(findings, errors, warns, extra: str = "") -> str:
    """A chase list grouped by sub, ready to paste into an email or ticket."""
    out = ["# Subcontractor compliance chase list", "",
           f"{len(errors)} error(s), {len(warns)} warning(s){md_cell(extra)}. Not legal advice.", ""]
    for who, items in _group(findings).items():
        out += [f"## {md_cell(who)}", "", "| Severity | Issue | What to do |", "|---|---|---|"]
        for f in sorted(items, key=lambda f: (_RANK.get(f.severity, 9), f.code)):
            out.append(f"| {f.severity} | {md_cell(f.detail)} | {md_cell(ACTIONS.get(f.code, ''))} |")
        out.append("")
    if not findings:
        out.append("Nothing to chase.")
    return "\n".join(out).rstrip()


def _ics_text(value: object) -> str:
    """RFC 5545 TEXT escaping on top of the terminal-safe cleaning."""
    return (clean(value, 400).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,"))


def _ics_fold(line: str) -> str:
    """Fold at 75 octets without splitting a UTF-8 character (RFC 5545 section 3.1)."""
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > (75 if not out else 74):
            out.append(cur)
            cur, size = "", 0
        cur += ch
        size += n
    out.append(cur)
    return "\r\n ".join(out)


def render_ics(findings, on: dt.date) -> str:
    """One all-day event per upcoming expiry, with a 14-day reminder. Only findings that carry a date."""
    stamp = f"{on:%Y%m%d}T000000Z"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//clearancewatch//EN", "CALSCALE:GREGORIAN"]
    for f in findings:
        if f.due is None or f.severity == "info":
            continue
        uid = hashlib.sha256("\x1f".join((f.code, f.job, f.sub, f.due.isoformat())).encode("utf-8")).hexdigest()[:32]
        action = ACTIONS.get(f.code, "")
        lines += ["BEGIN:VEVENT", f"UID:{uid}@clearancewatch.invalid", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{f.due:%Y%m%d}",
                  f"SUMMARY:{_ics_text(f.code)}: {_ics_text(f.subject)}",
                  f"DESCRIPTION:{_ics_text(f.detail)} {_ics_text(action)}".rstrip(),
                  "BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:-P14D",
                  f"DESCRIPTION:{_ics_text(f.code)}", "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_ics_fold(x) for x in lines)


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
    p.add_argument("jobs", help="jobs JSON file (list, or {\"jobs\": [...]}); - reads stdin")
    p.add_argument("--on", metavar="YYYY-MM-DD", type=_date_arg, help="audit date (default: today)")
    p.add_argument("--within", type=_non_negative, default=within_default,
                   help=f"renewal horizon in days (default {within_default})")
    p.add_argument("--json", action="store_true", help="same as --format json")
    p.add_argument("--format", choices=["text", "json", "csv", "md", "ics"], default="text")
    p.add_argument("--fail-on", choices=["error", "warn", "never"], default="error",
                   help="lowest severity that makes the exit code 1 (default error)")
    p.add_argument("--active-only", action="store_true",
                   help="skip jobs whose end date is before the audit date")
    p.add_argument("--payment-on", metavar="YYYY-MM-DD", type=_date_arg, action="append", default=[],
                   help="also check every sub's clearance against a planned payment date (repeatable)")
    p.add_argument("--baseline", metavar="PREV.json",
                   help="a previous --format json report: show only findings that are new since then")
    p.add_argument("--strict-whole-job", action="store_true",
                   help="keep 'clearance expires during job' an error even when the job is longer "
                        "than one 90-day clearance")


def load_baseline(path: str) -> List[Tuple[str, str, str, str]]:
    """Keys of the findings in a previous ``--format json`` report."""
    def die(msg: str):
        sys.stderr.write(f"clearancewatch: --baseline: {clean(msg, 600)}\n")
        raise SystemExit(2)

    try:
        data = _read_json(path)
    except (OSError, ValueError, RecursionError) as e:
        die(f"cannot read {path}: {e}")
    items = data.get("findings") if isinstance(data, dict) else None
    if not isinstance(items, list):
        die(f"{path} is not a clearancewatch --format json report")
    keys = []
    for f in items:
        if not isinstance(f, dict) or not all(isinstance(f.get(k), str) for k in ("code", "job", "sub", "detail")):
            die(f"{path}: a finding is missing code/job/sub/detail")
        keys.append((f["code"], f["job"], f["sub"], f["detail"]))
    return keys


def _key(f: Finding) -> Tuple[str, str, str, str]:
    return (f.code, f.job, f.sub, f.detail)


def _emit(text: str) -> None:
    try:
        print(text)
        sys.stdout.flush()
    except BrokenPipeError:  # `... | head`
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:  # pragma: no cover
            pass


def _emit_bytes(data: bytes) -> None:
    """Write bytes untouched (iCalendar needs CRLF, which text mode would double on Windows)."""
    try:
        sys.stdout.flush()
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    except BrokenPipeError:
        sys.stdout = open(os.devnull, "w")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="clearancewatch",
        description="Audit subcontractor clearance/insurance/licence coverage against job calendars. "
                    "Not legal advice. Exit 0 pass, 1 findings, 2 bad input, 3 internal error.",
    )
    ap.add_argument("--version", action="version", version=f"clearancewatch {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("audit", help="full audit; exit 1 when any error-severity finding exists")
    _common(a, 30)

    r = sub.add_parser("renewals", help="only what's due soon (exit 0 unless --fail-on warn/error says otherwise)")
    _common(r, 30)
    r.add_argument("--include-during-job", action="store_true",
                   help="also list documents that expire before the job ends, however far out")

    sub.add_parser("template", help="print a starter jobs.json to edit")
    sub.add_parser("schema", help="print a JSON Schema for the jobs file (for editor validation)")
    return ap


def _run(args) -> int:
    jobs, _n = load_jobs(args.jobs)
    on = args.on or dt.date.today()
    skipped = 0
    if args.active_only:
        kept = [j for j in jobs if not (j.end and j.end < on)]
        skipped, jobs = len(jobs) - len(kept), kept
    if args.payment_on:
        for j in jobs:
            j.payment_dates = sorted(set(j.payment_dates) | set(args.payment_on))

    if args.cmd == "audit":
        findings = [f for job in jobs for f in audit(job, on=on, horizon=args.within,
                                                     strict_whole_job=args.strict_whole_job)]
    else:
        findings = renewals(jobs, within=args.within, on=on, include_during_job=args.include_during_job,
                            strict_whole_job=args.strict_whole_job)

    known = resolved = 0
    if args.baseline:
        old = load_baseline(args.baseline)
        old_set = set(old)
        new = [f for f in findings if _key(f) not in old_set]
        now = {_key(f) for f in findings}
        known = len(findings) - len(new)
        resolved = len([k for k in old_set if k not in now])
        findings = new

    errors = [f for f in findings if f.severity == "error"]
    warns = [f for f in findings if f.severity == "warn"]
    bits = []
    if args.baseline:
        bits.append(f"{known} already in baseline hidden, {resolved} in baseline no longer found")
    if skipped:
        bits.append(f"{skipped} finished job(s) skipped")
    extra = f" ({'; '.join(bits)})" if bits else ""
    fmt = "json" if args.json else args.format
    if fmt == "json":
        doc = {"errors": len(errors), "warnings": len(warns), "info": len(findings) - len(errors) - len(warns),
               "jobs": len(jobs), "findings": [f.as_dict() for f in findings]}
        if args.baseline:
            doc["baseline"] = {"known_hidden": known, "resolved": resolved}
        if skipped:
            doc["skipped_finished_jobs"] = skipped
        _emit(json.dumps(doc, indent=2))
    elif fmt == "csv":
        _emit(render_csv(findings))
    elif fmt == "md":
        _emit(render_md(findings, errors, warns, extra))
    elif fmt == "ics":
        _emit_bytes((render_ics(findings, on) + "\r\n").encode("utf-8"))
    else:
        _emit(render_text(findings, errors, warns, extra))
    if args.fail_on == "never":
        return 0
    if args.fail_on == "warn":
        return 1 if (errors or warns) else 0
    return 1 if errors else 0


def main(argv: "list[str] | None" = None) -> int:
    args = build_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # a legacy console must not turn a finding into a crash
        try:
            stream.reconfigure(errors="backslashreplace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    if args.cmd == "template":
        _emit(TEMPLATE)
        return 0
    if args.cmd == "schema":
        _emit(json.dumps(jobs_schema(), indent=2))
        return 0
    try:
        return _run(args)
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as e:  # a bug here must never look like "a sub is out of compliance" (exit 1)
        if os.environ.get("CLEARANCEWATCH_DEBUG"):
            raise
        sys.stderr.write(f"clearancewatch: internal error ({type(e).__name__}: {clean(e, 300)}); "
                         "this is a bug, not a finding. Set CLEARANCEWATCH_DEBUG=1 for the traceback.\n")
        return 3


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
