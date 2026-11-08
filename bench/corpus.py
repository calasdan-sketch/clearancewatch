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
    j = {
        "name": f"Job {i}", "province": "ON", "start": iso(start), "end": iso(end),
        "requirements": {"min_liability": 2_000_000, "additional_insured": True,
                         "required_licences": {"electrical": "trade licence"}},
        "payment_dates": [iso(ON + dt.timedelta(days=20))],
        "subs": [{
            "name": f"Sub {i}", "trade": "electrical",
            "clearance": {"issuer": "WSIB", "number": f"{1000000 + i}", "issued": iso(issued),
                          "expires": iso(issued + dt.timedelta(days=90))},
            "insurance": {"provider": "Aviva", "policy": f"P-{i}",
                          # every fourth job carries a deductible in the text: it must never be read as the limit
                          "coverage": ("C$2M per occurrence, $5,000 deductible" if i % 4 == 2
                                       else "C$2M per occurrence, C$4M aggregate"),
                          "additional_insured": True,
                          "expires": iso(end + dt.timedelta(days=rng.randint(60, 300)))},
            "licences": [{"name": "Trade licence", "expires": iso(end + dt.timedelta(days=rng.randint(60, 300)))}],
        }],
    }
    if i % 3 == 1:  # an ongoing job (no end date) and two more subs, each with its own certificate
        j["end"] = None
        for k in (1, 2):
            other = copy.deepcopy(j["subs"][0])
            other["name"] = f"Sub {i}-{k}"
            other["clearance"]["number"] = f"{2000000 + i * 10 + k}"
            j["subs"].append(other)
        # no end date: insurance/licence cannot run out "during the job"
    return j


def clean_mb_job(rng, i):
    """A clean Manitoba job: dated WCB Manitoba letters that cover the whole job and predate the work."""
    j = clean_job(rng, i)
    j["province"] = "MB"
    j["end"] = j["end"] or iso(ON + dt.timedelta(days=60))
    for k, s in enumerate(j["subs"]):
        issued = ON - dt.timedelta(days=rng.randint(1, 10))
        s["clearance"] = {"issuer": "WCB Manitoba", "number": f"MB-{i}-{k}", "issued": iso(issued),
                          "covered_until": j["end"], "status": "good standing"}
        s["start"] = iso(issued)
    return j


def _mb(j):
    """Turn a clean job into a clean Manitoba one (in place) and return its first sub."""
    s = j["subs"][0]
    j["province"] = "MB"
    j["end"] = j["end"] or iso(ON + dt.timedelta(days=60))
    issued = ON - dt.timedelta(days=5)
    s["clearance"] = {"issuer": "WCB Manitoba", "number": "MB-1", "issued": iso(issued),
                      "covered_until": j["end"], "status": "good standing"}
    s["start"] = iso(issued)
    return s


def _mutate(kind, j, rng):
    s = j["subs"][0]
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
    elif kind == "insurance_endorsement_missing":
        s["insurance"]["additional_insured"] = False
    elif kind == "insurance_endorsement_unconfirmed":
        s["insurance"].pop("additional_insured")
    elif kind == "licence_missing":
        s["licences"] = []
    elif kind == "clearance_not_valid_at_payment":
        j["payment_dates"] = [iso(ON + dt.timedelta(days=rng.randint(100, 200)))]
    elif kind == "insurance_limit_ambiguous":
        s["insurance"]["coverage"] = rng.choice(["C$1M / C$2M aggregate", "$1,000,000 + $5M umbrella"])
    elif kind == "clearance_status_not_good":
        _mb(j)["clearance"]["status"] = rng.choice(["deemed/default", "Deemed / Defaulted", "not in good standing"])
    elif kind == "clearance_status_deemed_worker":
        _mb(j)["clearance"]["status"] = rng.choice(["deemed worker", "Deemed Worker"])
    elif kind == "clearance_after_work_started":
        s = _mb(j)
        s["start"] = iso(ON - dt.timedelta(days=rng.randint(10, 30)))
    elif kind == "insurance_limit_includes_umbrella":
        s["insurance"]["coverage"] = rng.choice(["C$1M + C$1M umbrella", "C$1M primary, C$500,000 excess"])
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


DEFECTS = [
    "clearance_expired", "clearance_expires_during_job", "clearance_missing", "renewal_due",
    "clearance_cover_lapsed", "issuer_mismatch", "clearance_dates_inconsistent",
    "clearance_term_exceeds_90_days", "insurance_below_minimum", "insurance_expired", "insurance_missing",
    "licence_expired", "clearance_no_expiry", "unknown_field", "clearance_number_shared", "clearance_gap",
    "insurance_endorsement_missing", "licence_missing", "clearance_not_valid_at_payment",
    "insurance_limit_ambiguous", "insurance_endorsement_unconfirmed",
    "clearance_status_not_good", "clearance_status_deemed_worker", "clearance_after_work_started",
    "insurance_limit_includes_umbrella",
]
# The severity each planted defect must be reported at (a defect found at the wrong severity is a miss).
SEVERITY = {
    "clearance_expired": "error",
    "clearance_expires_during_job": "warn",  # the corpus job outlasts one 90-day clearance
    "clearance_missing": "error", "renewal_due": "warn", "clearance_cover_lapsed": "warn",
    "issuer_mismatch": "warn", "clearance_dates_inconsistent": "error", "clearance_term_exceeds_90_days": "warn",
    "insurance_below_minimum": "error", "insurance_expired": "error", "insurance_missing": "error",
    "licence_expired": "error", "clearance_no_expiry": "error", "unknown_field": "warn",
    "clearance_number_shared": "warn", "clearance_gap": "warn", "insurance_endorsement_missing": "error",
    "licence_missing": "error", "clearance_not_valid_at_payment": "warn", "insurance_limit_ambiguous": "warn",
    "insurance_endorsement_unconfirmed": "warn",
    "clearance_status_not_good": "error", "clearance_status_deemed_worker": "warn",
    "clearance_after_work_started": "warn", "insurance_limit_includes_umbrella": "warn",
}
PER_DEFECT = 4
CLEAN = 30
CLEAN_MB = 6


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
    for _ in range(CLEAN_MB):
        cases.append({"id": n, "defect": None, "job": clean_mb_job(rng, n), "on": iso(ON)})
        n += 1
    return cases
