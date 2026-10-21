"""clearancewatch CLI: audit jobs.json for compliance gaps."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import List

from . import __version__
from .audit import audit, renewals
from .model import Job


def load_jobs(path: str) -> List[Job]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise SystemExit(f"clearancewatch: not found: {path}")
    except json.JSONDecodeError as e:
        raise SystemExit(f"clearancewatch: invalid JSON: {e}")
    if isinstance(data, dict):
        data = data.get("jobs", [data])
    return [Job.from_dict(d) for d in data]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="clearancewatch",
        description="Audit subcontractor clearance/insurance/licence coverage against job calendars.",
    )
    ap.add_argument("--version", action="version", version=f"clearancewatch {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("audit", help="full audit; exit 1 when any error-severity finding exists")
    a.add_argument("jobs", help="jobs JSON file (list, or {\"jobs\": [...]})")
    a.add_argument("--on", metavar="YYYY-MM-DD", help="audit date (default: today)")
    a.add_argument("--within", type=int, default=30, help="renewal horizon in days (default 30)")
    a.add_argument("--json", action="store_true")

    r = sub.add_parser("renewals", help="only what's due soon; exit 1 if anything is due")
    r.add_argument("jobs")
    r.add_argument("--within", type=int, default=30)
    r.add_argument("--on", metavar="YYYY-MM-DD")
    r.add_argument("--json", action="store_true")

    args = ap.parse_args(argv)
    on = dt.date.fromisoformat(args.on) if args.on else None
    jobs = load_jobs(args.jobs)

    if args.cmd == "audit":
        findings = [f for job in jobs for f in audit(job, on=on, horizon=args.within)]
    else:
        findings = renewals(jobs, within=args.within, on=on)

    errors = [f for f in findings if f.severity == "error"]
    warns = [f for f in findings if f.severity == "warn"]
    if args.json:
        print(json.dumps({"errors": len(errors), "warnings": len(warns),
                          "findings": [f.as_dict() for f in findings]}, indent=2))
    else:
        for f in findings:
            print(f"{f.severity.upper():5} {f.code:28} {f.subject}: {f.detail}")
        print(f"\n{len(errors)} error(s), {len(warns)} warning(s) — "
              f"{'FAIL' if errors else 'PASS'}")
    return 1 if errors else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
