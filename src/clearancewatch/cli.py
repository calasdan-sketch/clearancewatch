"""clearancewatch CLI: audit jobs.json for compliance gaps.

Exit codes: 0 = pass, 1 = findings at/above --fail-on, 2 = bad input or usage,
3 = internal error (a bug in clearancewatch, never a finding) -- so a cron job
can tell "your data is broken" from "a sub is out of compliance". Not legal advice.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import errno
import hashlib
import io
import json
import os
import sys
from typing import Dict, List, Tuple

from . import __copyright__, __version__
from .audit import Finding, audit, check_jobs, renewals
from .importer import ImportError_, rows_to_jobs
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
    "insurance_limit_includes_umbrella": "Check the contract: may umbrella/excess count toward the minimum?",
    "insurance_limit_ambiguous": "Read the certificate and enter the per-occurrence limit as a number",
    "insurance_endorsement_missing": "Ask the broker for the required endorsement",
    "insurance_endorsement_unconfirmed": "Check the endorsement on the certificate and record true or false",
    "licence_missing": "Request a copy of the required licence",
    "clearance_exempt": "Confirm the exemption with the regulator and keep the answer on file",
    "job_has_no_subs": "Add the subcontractors for this job, or remove the job",
    "duplicate_job": "Give each job a different name (reports and --baseline match on the job name)",
    "clearance_after_work_started": "Get the clearance on file now, and add any earlier one to the sub's clearances",
    "clearance_status_deemed_worker": "Add the labour portion of this contract to your payroll estimate",
    "clearance_status_not_good": "Ask the sub to resolve its standing with the board before releasing payment",
    "clearance_status_unrecognised": "Record the letter's status: good standing, deemed worker or deemed/default",
    "clearance_supply_only": "Confirm the sub only supplies material, and keep the confirmation on file",
}
_RANK = {"error": 0, "warn": 1, "info": 2}


def _no_constant(name: str):
    raise ValueError(f"{name} is not valid JSON; use a real number or leave the field out")


def _decode(raw: bytes) -> str:
    """UTF-8 (with or without BOM), or UTF-16 with a BOM.

    Windows PowerShell 5 writes UTF-16 when you run ``clearancewatch template > jobs.json``.
    """
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def _read_json(path: str):
    """Parse a JSON file (or stdin for ``-``), size-capped, BOM-tolerant."""
    if path == "-":
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise OSError(f"input is larger than the {MAX_BYTES} byte limit")
    else:
        size = os.path.getsize(path)
        if size > MAX_BYTES:
            raise OSError(f"{path}: file is {size} bytes (limit {MAX_BYTES})")
        with open(path, "rb") as fh:
            raw = fh.read(MAX_BYTES + 1)
    return json.loads(_decode(raw), parse_constant=_no_constant)


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
    except UnicodeError:
        die(f"{path}: not readable text (save the file as UTF-8)")
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
    out: List[str] = []
    cur, size = "", 0
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
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Calas Automations Inc.//clearancewatch//EN",
             "CALSCALE:GREGORIAN"]
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


_GH_LEVEL = {"error": "error", "warn": "warning", "info": "notice"}


def _gh_escape(text: str, prop: bool = False) -> str:
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return text.replace(":", "%3A").replace(",", "%2C") if prop else text


def render_github(findings) -> str:
    """GitHub Actions workflow commands: findings show as annotations on the run page."""
    lines = [f"::{_GH_LEVEL.get(f.severity, 'warning')} title={_gh_escape(clean(f.code), True)}::"
             f"{_gh_escape(clean(f.subject, 200))}: {_gh_escape(clean(f.detail, 600))}" for f in findings]
    return "\n".join(lines)


def _non_negative(s: str) -> int:
    try:
        v = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a whole number of days, got {s!r}") from None
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
    p.add_argument("--format", choices=["text", "json", "csv", "md", "ics", "github"], default="text")
    p.add_argument("-o", "--output", metavar="FILE",
                   help="write the report to FILE (UTF-8) instead of the screen; the exit code is unchanged")
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
        raise AssertionError  # pragma: no cover
    keys = []
    for f in items:
        if isinstance(f, dict) and "job" not in f and "sub" not in f and isinstance(f.get("subject"), str):
            # clearancewatch 0.1.0 reports have only "job / sub" in `subject`; split it back apart
            job, _, sub = f["subject"].partition(" / ")
            f = dict(f, job=job, sub=sub)
        if not isinstance(f, dict) or not all(isinstance(f.get(k), str) for k in ("code", "job", "sub", "detail")):
            die(f"{path}: a finding is missing code/job/sub/detail")
        keys.append((f["code"], f["job"], f["sub"], f["detail"]))
    return keys


def _key(f: Finding) -> Tuple[str, str, str, str]:
    return (f.code, f.job, f.sub, f.detail)


def _closed_pipe(e: OSError) -> bool:
    """`... | head` is BrokenPipeError on Unix; Windows can report EPIPE or EINVAL instead."""
    return isinstance(e, BrokenPipeError) or e.errno in (errno.EPIPE, errno.EINVAL)


def _drop_stdout() -> None:
    try:
        sys.stdout = open(os.devnull, "w")
    except OSError:  # pragma: no cover
        pass


def _emit(text: str) -> None:
    try:
        print(text)
        sys.stdout.flush()
    except OSError as e:
        if not _closed_pipe(e):
            raise
        _drop_stdout()


def _emit_bytes(data: bytes) -> None:
    """Write bytes untouched (iCalendar needs CRLF, which text mode would double on Windows)."""
    try:
        sys.stdout.flush()
        buf = getattr(sys.stdout, "buffer", None)
        if buf is None:  # stdout replaced by a text-only object
            sys.stdout.write(data.decode("utf-8"))
            return
        buf.write(data)
        buf.flush()
    except OSError as e:
        if not _closed_pipe(e):
            raise
        _drop_stdout()


def _write_output(path: str, data: bytes) -> None:
    """Write the report to a file: UTF-8, no newline translation, replaced in one step."""
    tmp = f"{path}.cwtmp{os.getpid()}"
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        sys.stderr.write(f"clearancewatch: cannot write {clean(path, 200)}: {clean(e.strerror or e, 200)}\n")
        raise SystemExit(2) from None


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

    ic = sub.add_parser("import-csv", help="turn a spreadsheet export (one row per sub) into a jobs file")
    ic.add_argument("csv", help="CSV file; - reads stdin (see the README for the column names)")
    ic.add_argument("-o", "--output", metavar="FILE", help="write the jobs file to FILE (UTF-8) instead of the screen")
    sub.add_parser("about", help="who makes this and under which licence")

    for name, helptext in (("template", "print a starter jobs.json to edit"),
                           ("schema", "print a JSON Schema for the jobs file (for editor validation)")):
        t = sub.add_parser(name, help=helptext)
        t.add_argument("-o", "--output", metavar="FILE", help="write to FILE (UTF-8) instead of the screen")
    return ap


ABOUT = f"clearancewatch {__version__}\n{__copyright__}\nLicence: MIT. Not legal advice."


def _import_csv(args) -> int:
    """Spreadsheet rows to a jobs file; the result is checked with the same loader ``audit`` uses."""
    def die(msg: str):
        sys.stderr.write(f"clearancewatch: import-csv: {clean(msg, 600)}\n")
        raise SystemExit(2)

    try:
        if args.csv == "-":
            raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        else:
            if os.path.getsize(args.csv) > MAX_BYTES:
                die(f"{args.csv}: file is larger than the {MAX_BYTES} byte limit")
            with open(args.csv, "rb") as fh:
                raw = fh.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            die(f"input is larger than the {MAX_BYTES} byte limit")
        text = _decode(raw)
    except FileNotFoundError:
        die(f"not found: {args.csv}")
    except IsADirectoryError:
        die(f"{args.csv} is a folder, not a CSV file")
    except PermissionError:
        die(f"cannot read {args.csv}: permission denied")
    except UnicodeError:
        die(f"{args.csv}: not readable text (save the CSV as UTF-8)")
    except OSError as e:
        die(f"cannot read {args.csv}: {e.strerror or e}")
    try:
        jobs, rows = rows_to_jobs(text)
    except ImportError_ as e:
        die(str(e))
    except csv.Error as e:
        die(f"not a readable CSV: {e}")
    try:
        for i, d in enumerate(jobs):  # same strict checks as audit, so a bad date is caught here
            Job.from_dict(d, f"jobs[{i}]")
    except DataError as e:
        die(str(e))
    out = json.dumps(jobs, indent=2)
    if args.output:
        _write_output(args.output, (out + "\n").encode("utf-8"))
    else:
        _emit(out)
    sys.stderr.write(f"clearancewatch: read {rows} row(s) into {len(jobs)} job(s)\n")
    return 0


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

    dupes = check_jobs(jobs)
    if args.cmd == "audit":
        findings = dupes + [f for job in jobs for f in audit(job, on=on, horizon=args.within,
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
    text = ""
    if fmt == "json":
        doc: Dict[str, object] = {"schema": 1, "version": __version__, "errors": len(errors),
               "warnings": len(warns), "info": len(findings) - len(errors) - len(warns),
               "jobs": len(jobs), "findings": [f.as_dict() for f in findings]}
        if args.baseline:
            doc["baseline"] = {"known_hidden": known, "resolved": resolved}
        if skipped:
            doc["skipped_finished_jobs"] = skipped
        text = json.dumps(doc, indent=2)
    elif fmt == "csv":
        text = render_csv(findings)
    elif fmt == "md":
        text = render_md(findings, errors, warns, extra)
    elif fmt == "ics":
        text = render_ics(findings, on) + "\r\n"
    elif fmt == "github":
        text = render_github(findings)
    else:
        text = render_text(findings, errors, warns, extra)
    if args.output:
        _write_output(args.output, (text if fmt == "ics" else text + "\n").encode("utf-8"))
    elif fmt == "ics":
        _emit_bytes(text.encode("utf-8"))
    elif text or fmt != "github":
        _emit(text)
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
    if args.cmd == "about":
        _emit(ABOUT)
        return 0
    if args.cmd == "import-csv":
        return _import_csv(args)
    if args.cmd in ("template", "schema"):
        text = TEMPLATE if args.cmd == "template" else json.dumps(jobs_schema(), indent=2)
        if args.output:
            _write_output(args.output, (text + "\n").encode("utf-8"))
        else:
            _emit(text)
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
