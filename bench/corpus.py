"""Labelled scenarios for the benchmark: each is a job + audit date + the defect it contains.

Every defect case plants exactly one problem in an otherwise clean job; ``None``
means the job is clean and any finding is a false alarm. Dates are generated
from a fixed seed so anyone can re-run the benchmark and get the same numbers.
"""
from __future__ import annotations

import copy
import datetime as dt
import random

ON = dt.date(2026, 3, 1)


def iso(d):
    return d.isoformat()


def clean_job(rng, i):
    start = ON - dt.timedelta(days=rng.randint(5, 40))
    end = ON + dt.timedelta(days=rng.randint(30, 80))
    issued = ON - dt.timedelta(days=rng.randint(1, 10))
    return {
        "name": f"Job {i}", "province": "ON", "start": iso(start), "end": iso(end),
        "requirements": {"min_liability": 2_000_000},
        "subs": [{
            "name": f"Sub {i}",
            "clearance": {"issuer": "WSIB", "number": f"{1000000 + i}", "issued": iso(issued),
                          "expires": iso(issued + dt.timedelta(days=90))},
            "insurance": {"provider": "Aviva", "policy": f"P-{i}", "coverage": "C$2M",
                          "expires": iso(end + dt.timedelta(days=rng.randint(60, 300)))},
            "licences": [{"name": "Trade licence", "expires": iso(end + dt.timedelta(days=rng.randint(60, 300)))}],
        }],
    }


def _mutate(kind, j, rng):
    s = j["subs"][0]
    start, end = dt.date.fromisoformat(j["start"]), dt.date.fromisoformat(j["end"])
    if kind == "clearance_expired":
        iss = ON - dt.timedelta(days=rng.randint(100, 200))
        s["clearance"].update(issued=iso(iss), expires=iso(iss + dt.timedelta(days=90)))
    elif kind == "clearance_expires_during_job":
        # expires 45-70 days out: past the 30-day renewal horizon, but before the job ends
        j["end"] = iso(ON + dt.timedelta(days=rng.randint(120, 160)))
        s["insurance"]["expires"] = iso(ON + dt.timedelta(days=400))
        s["licences"][0]["expires"] = iso(ON + dt.timedelta(days=400))
        s["clearance"].update(issued=iso(ON - dt.timedelta(days=20)),
                              expires=iso(ON + dt.timedelta(days=rng.randint(45, 70))))
    elif kind == "clearance_missing":
        s.pop("clearance")
    elif kind == "renewal_due":
        j["end"] = iso(ON + dt.timedelta(days=5))
        s["clearance"].update(issued=iso(ON - dt.timedelta(days=70)),
                              expires=iso(ON + dt.timedelta(days=rng.randint(8, 25))))
    elif kind == "clearance_cover_lapsed":
        j["province"] = "AB"
        s["clearance"] = {"issuer": "WCB-AB", "number": "L-1", "issued": iso(ON - dt.timedelta(days=30)),
                          "covered_until": iso(ON - dt.timedelta(days=30))}
    elif kind == "issuer_mismatch":
        s["clearance"]["issuer"] = rng.choice(["WCB-AB", "WCB Alberta"])
    elif kind == "clearance_dates_inconsistent":
        s["clearance"].update(issued=iso(ON - dt.timedelta(days=3)), expires=iso(ON - dt.timedelta(days=93)))
    elif kind == "clearance_term_exceeds_90_days":
        s["clearance"].update(issued=iso(ON - dt.timedelta(days=3)), expires=iso(ON + dt.timedelta(days=362)))
    elif kind == "insurance_below_minimum":
        s["insurance"]["coverage"] = rng.choice(["C$1M", "$500,000", "1 million"])
    elif kind == "insurance_expired":
        s["insurance"]["expires"] = iso(ON - dt.timedelta(days=rng.randint(2, 90)))
    elif kind == "insurance_missing":
        s.pop("insurance")
    elif kind == "licence_expired":
        s["licences"][0]["expires"] = iso(ON - dt.timedelta(days=rng.randint(2, 90)))
    elif kind == "clearance_no_expiry":
        j["province"] = "BC"
        s["clearance"] = {"issuer": "WorkSafeBC", "number": "B-1", "issued": iso(ON - dt.timedelta(days=5))}
    elif kind == "unknown_field":
        s["clearance"]["expiry"] = s["clearance"].pop("expires")  # typo'd key silently dropped by naive tools
    elif kind == "clearance_number_shared":
        other = copy.deepcopy(s)
        other["name"] = "Other Sub"
        j["subs"].append(other)
    elif kind == "clearance_gap":
        j["end"] = iso(ON + dt.timedelta(days=60))
        a_iss = ON - dt.timedelta(days=100)
        b_iss = ON - dt.timedelta(days=5)
        s["clearances"] = [{"issuer": "WSIB", "number": "OLD", "issued": iso(a_iss),
                            "expires": iso(a_iss + dt.timedelta(days=60))}]
        s["clearance"].update(issued=iso(b_iss), expires=iso(b_iss + dt.timedelta(days=90)))
        j["start"] = iso(a_iss)
    else:
        raise ValueError(kind)
    del start, end


DEFECTS = [
    "clearance_expired", "clearance_expires_during_job", "clearance_missing", "renewal_due",
    "clearance_cover_lapsed", "issuer_mismatch", "clearance_dates_inconsistent",
    "clearance_term_exceeds_90_days", "insurance_below_minimum", "insurance_expired", "insurance_missing",
    "licence_expired", "clearance_no_expiry", "unknown_field", "clearance_number_shared", "clearance_gap",
]
PER_DEFECT = 4
CLEAN = 24


def build(seed=20261107):
    rng = random.Random(seed)
    cases = []
    n = 0
    for kind in DEFECTS:
        for _ in range(PER_DEFECT):
            j = clean_job(rng, n)
            _mutate(kind, j, rng)
            cases.append({"id": n, "defect": kind, "job": j, "on": iso(ON)})
            n += 1
    for _ in range(CLEAN):
        cases.append({"id": n, "defect": None, "job": clean_job(rng, n), "on": iso(ON)})
        n += 1
    return cases
