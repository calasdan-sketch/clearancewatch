"""Reproducible benchmark: defect catch rate vs a plain date-column tracker, plus speed.

    python bench/run.py            # prints a table; exits 1 if clearancewatch misses a planted defect

The baseline is a deliberately simple stand-in for "a spreadsheet with an expiry-date column and a
conditional-format rule": it flags a document only when an explicit expiry date is already past or
within the renewal horizon. It is NOT a measurement of any commercial product (Avetta, TrustLayer,
myCOI, ...); those were not run, and nothing here says how they behave.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from corpus import build, clean_job  # noqa: E402

from clearancewatch import Job, audit  # noqa: E402

HORIZON = 30


def baseline_flags(job: dict, on: dt.date) -> bool:
    """True if a date-column tracker would flag anything on this job."""
    limit = on + dt.timedelta(days=HORIZON)
    for sub in job["subs"]:
        docs = [sub.get("clearance") or {}, sub.get("insurance") or {}] + list(sub.get("licences") or [])
        for d in docs:
            exp = d.get("expires")
            if exp and dt.date.fromisoformat(exp) <= limit:
                return True
    return False


def evaluate(cases):
    rows = {"cw": [0, 0], "base": [0, 0]}  # [caught defects, defects]
    fp = {"cw": 0, "base": 0}
    clean_n = 0
    per = {}
    for c in cases:
        on = dt.date.fromisoformat(c["on"])
        found = {f.code for f in audit(Job.from_dict(c["job"]), on=on, horizon=HORIZON)}
        cw_flag = bool(found)
        base_flag = baseline_flags(c["job"], on)
        if c["defect"] is None:
            clean_n += 1
            fp["cw"] += cw_flag
            fp["base"] += base_flag
            continue
        cw_hit = c["defect"] in found or (c["defect"] == "unknown_field" and "unknown_field" in found)
        p = per.setdefault(c["defect"], [0, 0, 0])
        p[0] += 1
        p[1] += cw_hit
        p[2] += base_flag
        rows["cw"][0] += cw_hit
        rows["cw"][1] += 1
        rows["base"][0] += base_flag
        rows["base"][1] += 1
    return rows, fp, clean_n, per


def speed(n_jobs=20000, subs=5):
    jobs = []
    for i in range(n_jobs):
        j = clean_job(__import__("random").Random(i), i)
        j["subs"] = [dict(j["subs"][0], name=f"S{k}") for k in range(subs)]
        jobs.append(Job.from_dict(j))
    t = time.perf_counter()
    for j in jobs:
        audit(j, on=dt.date(2026, 3, 1))
    dt_s = time.perf_counter() - t
    return n_jobs * subs, dt_s


def main() -> int:
    cases = build()
    rows, fp, clean_n, per = evaluate(cases)
    d = rows["cw"][1]
    print(f"corpus: {d} planted defects ({len(per)} kinds x {d // len(per)}), {clean_n} clean jobs, seed fixed\n")
    print(f"{'defect kind':34} {'clearancewatch':>15} {'date-column tracker':>20}")
    for k, (n, cw, base) in per.items():
        print(f"{k:34} {cw:>8}/{n:<6} {base:>13}/{n}")
    print(f"\ncatch rate      clearancewatch {rows['cw'][0]}/{d} = {rows['cw'][0] / d:.0%}   "
          f"date-column tracker {rows['base'][0]}/{d} = {rows['base'][0] / d:.0%}")
    print(f"false alarms    clearancewatch {fp['cw']}/{clean_n}   date-column tracker {fp['base']}/{clean_n}")
    n_subs, secs = speed()
    print(f"speed           {n_subs} sub audits in {secs:.2f}s = {n_subs / secs:,.0f} subs/s (one core)")
    return 0 if rows["cw"][0] == d and fp["cw"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
