"""Property tests: random but valid-shaped jobs must never crash the auditor or break its promises.

The seeded versions need no extra packages. If hypothesis is installed (CI installs it) the same
properties also run under it.
"""
import datetime as dt
import json
import random
import string

import pytest

from clearancewatch import DataError, Job, audit, renewals
from clearancewatch.cli import ACTIONS, render_csv, render_github, render_ics, render_md, render_text
from clearancewatch.money import MAX_LIMIT, parse_limits
from clearancewatch.safe import clean, csv_cell, md_cell

BASE = dt.date(2026, 3, 1)
SEVERITIES = {"error", "warn", "info"}
ISSUERS = ["WSIB", "WCB-AB", "WCB Alberta", "WCB Manitoba", "WCB-MB", "WCB", "", "Acme Board"]
PROVINCES = ["ON", "AB", "MB", "BC", "", "Ontario", "Manitoba"]
COVERAGE = ["C$2M", "$1,000,000", "1/2M", "$5,000 deductible, 2M", "1M + 1M umbrella", "", "US$2M", "2 000 000", "abc"]
STATUS = ["", "good standing", "deemed worker", "deemed/default", "not in good standing", "???"]
TEXT_BITS = ["a", "Z", " ", "\x1b[31m", "‮", " ", "=cmd", "|", "[x](y)", "\n", ",", '"', "é", "\x00", "<b>"]


def d(rng, lo=-200, hi=400):
    return (BASE + dt.timedelta(days=rng.randint(lo, hi))).isoformat()


def text(rng):
    return "".join(rng.choice(TEXT_BITS) for _ in range(rng.randint(0, 6)))


def clearance(rng):
    c = {"issuer": rng.choice(ISSUERS), "number": rng.choice(["", "1", "2", "A-3"]), "status": rng.choice(STATUS)}
    for k in ("issued", "expires", "covered_until"):
        if rng.random() < 0.5:
            c[k] = d(rng)
    return c


def sub(rng):
    s = {"name": rng.choice(["A", "B", "C", text(rng)])}
    if rng.random() < 0.8:
        s["clearance"] = clearance(rng)
    if rng.random() < 0.3:
        s["clearances"] = [clearance(rng) for _ in range(rng.randint(1, 3))]
    if rng.random() < 0.8:
        s["insurance"] = {"provider": "p", "policy": "q", "coverage": rng.choice(COVERAGE),
                          "expires": d(rng) if rng.random() < 0.8 else "",
                          "additional_insured": rng.choice([True, False, None])}
    if rng.random() < 0.4:
        s["licences"] = [{"name": text(rng), "expires": d(rng) if rng.random() < 0.8 else ""}]
    if rng.random() < 0.2:
        s["start"] = d(rng)
    if rng.random() < 0.1:
        s["supply_only"] = rng.choice([True, False])
    if rng.random() < 0.1:
        s["clearance_exempt"] = text(rng)
    s["trade"] = rng.choice(["", "electrical", "drywall"])
    return s


def job(rng):
    j = {"name": rng.choice(["J1", "J2", text(rng)]), "province": rng.choice(PROVINCES),
         "subs": [sub(rng) for _ in range(rng.randint(0, 4))]}
    if rng.random() < 0.7:
        j["start"] = d(rng, -100, 0)
    if rng.random() < 0.7:
        j["end"] = d(rng, -50, 300)
    if rng.random() < 0.4:
        j["payment_dates"] = [d(rng, -20, 120) for _ in range(rng.randint(1, 3))]
    if rng.random() < 0.5:
        j["requirements"] = {"min_liability": rng.choice([1_000_000, "C$2M", 5_000_000]),
                             "additional_insured": rng.random() < 0.5,
                             "required_licences": rng.choice([{}, {"electrical": "electrician"}])}
    return j


def _load(raw):
    return Job.from_dict(json.loads(json.dumps(raw)))


def check_properties(raw, on):
    found = audit(_load(raw), on=on, horizon=30)
    assert found == audit(_load(raw), on=on, horizon=30)           # deterministic
    for f in found:
        assert f.severity in SEVERITIES and f.code in ACTIONS      # known code and severity, has an action
        assert f.detail and f.subject
    # the order of subs never changes WHAT is found
    flipped = dict(raw, subs=list(reversed(raw["subs"])))
    assert sorted(map(repr, audit(_load(flipped), on=on, horizon=30))) == sorted(map(repr, found))
    # renewals is a filter over audit, never an invention
    job_ = _load(raw)
    assert set(map(repr, renewals([job_], within=30, on=on))) <= set(map(repr, audit(job_, on=on, horizon=30)))
    # every report format renders, without raw control characters or bidi/line-separator characters
    errors = [f for f in found if f.severity == "error"]
    warns = [f for f in found if f.severity == "warn"]
    for out in (render_text(found, errors, warns), render_csv(found), render_md(found, errors, warns),
                render_github(found), render_ics(found, on)):
        assert not [c for c in out if ord(c) < 32 and c not in "\r\n"], out
        assert "‮" not in out and " " not in out


def test_random_jobs_hold_their_promises_seeded():
    for seed in range(300):
        rng = random.Random(seed)
        check_properties(job(rng), BASE + dt.timedelta(days=rng.randint(-30, 60)))


def test_stated_wsib_expiry_in_the_past_is_an_error_exactly_when_past():
    for seed in range(200):
        rng = random.Random(seed)
        exp = BASE + dt.timedelta(days=rng.randint(-300, 300))
        on = BASE + dt.timedelta(days=rng.randint(-60, 60))
        j = Job.from_dict({"name": "J", "province": "ON", "subs": [{"name": "S", "clearance": {
            "issuer": "WSIB", "issued": (exp - dt.timedelta(days=60)).isoformat(), "expires": exp.isoformat()}}]})
        got = [f.code for f in audit(j, on=on)]
        assert ("clearance_expired" in got) == (exp < on), (exp, on)


def test_insurance_expiry_boundary_is_exact():
    for delta in (-2, -1, 0, 1, 2):
        j = Job.from_dict({"name": "J", "subs": [{"name": "S", "insurance": {
            "provider": "p", "policy": "q", "expires": (BASE + dt.timedelta(days=delta)).isoformat()}}]})
        assert ("insurance_expired" in [f.code for f in audit(j, on=BASE)]) == (delta < 0)


def test_limit_parser_never_raises_and_stays_in_range_seeded():
    alphabet = string.digits + "$,. MmKk-+/()CcUuSsDdeE −" + "perccurnce aggregate deductible"
    for seed in range(3000):
        rng = random.Random(seed)
        s = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 30)))
        amounts, problem = parse_limits(s)
        assert bool(amounts) != bool(problem)
        assert all(0 <= a <= MAX_LIMIT for a, _ in amounts)


def test_clean_functions_never_leave_control_characters_seeded():
    for seed in range(1000):
        rng = random.Random(seed)
        s = "".join(chr(rng.choice([rng.randint(0, 0x2fff), rng.randint(0, 127)])) for _ in range(rng.randint(0, 40)))
        for fn in (clean, csv_cell, md_cell):
            out = fn(s)
            assert not [c for c in out if ord(c) < 32 or 0x7f <= ord(c) <= 0x9f]
            assert "‮" not in out and " " not in out and "﻿" not in out


def test_garbage_shapes_give_dataerror_never_another_exception():
    rng = random.Random(5)
    junk = [None, 1, 1.5, True, "x", [], {}, [1], {"a": 1}, "2026-02-30", 20260101]
    for _ in range(500):
        raw = job(rng)
        key = rng.choice(["name", "province", "start", "end", "subs", "requirements", "payment_dates"])
        raw[key] = rng.choice(junk)
        subs = raw.get("subs")
        if isinstance(subs, list) and subs and isinstance(subs[0], dict) and rng.random() < 0.5:
            inner = rng.choice(["clearance", "insurance", "licences", "start", "supply_only", "name"])
            subs[0][inner] = rng.choice(junk)
        try:
            audit(Job.from_dict(raw), on=BASE)
        except DataError:
            pass


hypothesis = pytest.importorskip("hypothesis", reason="hypothesis not installed; the seeded tests above still ran")
from hypothesis import given, settings, strategies as st  # noqa: E402


@settings(max_examples=150, deadline=None)
@given(st.integers(min_value=0, max_value=10 ** 9), st.integers(min_value=-30, max_value=60))
def test_hypothesis_random_jobs_hold_their_promises(seed, offset):
    rng = random.Random(seed)
    check_properties(job(rng), BASE + dt.timedelta(days=offset))


@settings(max_examples=300, deadline=None)
@given(st.text(max_size=60))
def test_hypothesis_limit_parser_is_total(s):
    amounts, problem = parse_limits(s)
    assert bool(amounts) != bool(problem)


@settings(max_examples=300, deadline=None)
@given(st.text(max_size=80))
def test_hypothesis_clean_is_single_line_printable(s):
    out = clean(s)
    assert "\n" not in out and "\r" not in out and "\x1b" not in out
