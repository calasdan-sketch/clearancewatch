"""Date boundaries, checked against a small independent oracle.

Found by the mutation check (bench/mutate.py): flipping `<` to `<=` in the expiry logic went unnoticed
because no test sat exactly on the day. These do: every expiry kind x job end x days-to-expiry.
"""
import datetime as dt

import pytest

from clearancewatch import Job, audit

ON = dt.date(2026, 6, 1)
HORIZON = 30


def day(offset):
    return (ON + dt.timedelta(days=offset)).isoformat()


def oracle(exp_off, end_off):
    """What should be reported for a document that expires exp_off days from the audit date."""
    if exp_off < 0:
        return "expired"
    if end_off is not None and exp_off < end_off:
        return "during_job"
    if exp_off <= HORIZON:
        return "renewal_due"
    return None


def job_for(kind, exp_off, end_off):
    sub = {"name": "S"}
    if kind != "clearance":
        sub["clearance"] = {"issuer": "WSIB", "issued": day(-5), "expires": day(80)}
    if kind != "insurance":
        sub["insurance"] = {"provider": "p", "policy": "q", "expires": day(400)}
    if kind == "clearance":
        sub["clearance"] = {"issuer": "WSIB", "number": "1", "issued": day(exp_off - 60), "expires": day(exp_off)}
    elif kind == "insurance":
        sub["insurance"] = {"provider": "p", "policy": "q", "expires": day(exp_off)}
    else:
        sub["licences"] = [{"name": "L", "expires": day(exp_off)}]
    j = {"name": "J", "province": "ON", "subs": [sub]}
    if end_off is not None:
        j["end"] = day(end_off)
    return Job.from_dict(j)


NAMES = {
    "clearance": {"expired": "clearance_expired", "during_job": "clearance_expires_during_job",
                  "renewal_due": "renewal_due"},
    "insurance": {"expired": "insurance_expired", "during_job": "insurance_expires_during_job",
                  "renewal_due": "insurance_renewal_due"},
    "licence": {"expired": "licence_expired", "during_job": "licence_expires_during_job",
                "renewal_due": "licence_renewal_due"},
}
ALL_OF_KIND = {k: set(v.values()) for k, v in NAMES.items()}


@pytest.mark.parametrize("kind", ["clearance", "insurance", "licence"])
@pytest.mark.parametrize("end_off", [None, 20, 60])
@pytest.mark.parametrize("exp_off", [-2, -1, 0, 1, 19, 20, 21, 29, 30, 31, 59, 60, 61])
def test_expiry_boundaries_match_the_oracle(kind, end_off, exp_off):
    got = {f.code for f in audit(job_for(kind, exp_off, end_off), on=ON, horizon=HORIZON)} & ALL_OF_KIND[kind]
    want = oracle(exp_off, end_off)
    assert got == ({NAMES[kind][want]} if want else set()), (kind, exp_off, end_off)


@pytest.mark.parametrize("kind", ["clearance", "insurance", "licence"])
def test_the_due_date_travels_with_the_finding(kind):
    f = [x for x in audit(job_for(kind, 10, None), on=ON, horizon=HORIZON) if x.code == NAMES[kind]["renewal_due"]]
    assert len(f) == 1 and f[0].due == ON + dt.timedelta(days=10)


@pytest.mark.parametrize("horizon,exp_off,due", [(0, 0, True), (0, 1, False), (7, 7, True), (7, 8, False)])
def test_within_days_is_inclusive(horizon, exp_off, due):
    got = {f.code for f in audit(job_for("insurance", exp_off, None), on=ON, horizon=horizon)}
    assert ("insurance_renewal_due" in got) == due


def test_alberta_and_manitoba_letters_on_the_day():
    for prov, issuer in (("AB", "WCB-AB"), ("MB", "WCB Manitoba")):
        for cover_off, end_off, lapsed in ((10, 10, False), (10, 11, True), (9, 10, True), (11, 10, False)):
            j = Job.from_dict({"name": "J", "province": prov, "end": day(end_off), "subs": [
                {"name": "S", "clearance": {"issuer": issuer, "issued": day(-3), "covered_until": day(cover_off)},
                 "insurance": {"provider": "p", "policy": "q", "expires": day(400)}}]})
            got = {f.code for f in audit(j, on=ON)}
            assert ("clearance_cover_lapsed" in got) == lapsed, (prov, cover_off, end_off)


def test_payment_on_the_last_covered_day_is_fine_and_the_day_after_is_not():
    for pay_off, bad in ((10, False), (11, True)):
        j = Job.from_dict({"name": "J", "province": "MB", "payment_dates": [day(pay_off)], "subs": [
            {"name": "S", "clearance": {"issuer": "WCB Manitoba", "issued": day(-3), "covered_until": day(10)},
             "insurance": {"provider": "p", "policy": "q", "expires": day(400)}}]})
        assert ("clearance_not_valid_at_payment" in {f.code for f in audit(j, on=ON)}) == bad


def test_payment_dates_in_the_past_are_ignored_but_today_counts():
    for pay_off, bad in ((-1, False), (0, True)):
        j = Job.from_dict({"name": "J", "province": "MB", "payment_dates": [day(pay_off)], "subs": [
            {"name": "S", "clearance": {"issuer": "WCB Manitoba", "issued": day(-30), "covered_until": day(-10)},
             "insurance": {"provider": "p", "policy": "q", "expires": day(400)}}]})
        assert ("clearance_not_valid_at_payment" in {f.code for f in audit(j, on=ON)}) == bad


def test_wsib_clearance_issue_to_expiry_term_boundary():
    for term, flagged in ((89, False), (90, False), (91, True)):
        j = Job.from_dict({"name": "J", "province": "ON", "subs": [
            {"name": "S", "clearance": {"issuer": "WSIB", "number": "1", "issued": day(-5),
                                        "expires": day(-5 + term)},
             "insurance": {"provider": "p", "policy": "q", "expires": day(400)}}]})
        assert ("clearance_term_exceeds_90_days" in {f.code for f in audit(j, on=ON)}) == flagged


def test_default_wsib_expiry_is_issue_plus_90_days_exactly():
    for issued_off, expired in ((-90, False), (-91, True)):
        j = Job.from_dict({"name": "J", "province": "ON", "subs": [
            {"name": "S", "clearance": {"issuer": "WSIB", "issued": day(issued_off)},
             "insurance": {"provider": "p", "policy": "q", "expires": day(400)}}]})
        assert ("clearance_expired" in {f.code for f in audit(j, on=ON)}) == expired
