"""Edge cases the mutation check (bench/mutate.py, third pass) showed nothing was pinning."""
import datetime as dt

import pytest

from clearancewatch import Job, audit
from clearancewatch.money import MAX_LIMIT, parse_limits

ON = dt.date(2026, 6, 1)


def day(offset):
    return (ON + dt.timedelta(days=offset)).isoformat()


def codes(findings):
    return sorted(f.code for f in findings)


def one(subs, **job):
    base = {"name": "J", "province": "ON", "subs": subs}
    base.update(job)
    return Job.from_dict(base)


def wsib(issued, expires=None, number="1"):
    c = {"issuer": "WSIB", "number": number, "issued": issued}
    if expires:
        c["expires"] = expires
    return c


INS = {"provider": "p", "policy": "q", "expires": "2030-01-01"}


# ---- gaps between certificates ---------------------------------------------------------------------------

def gap_job(second_issued_offset, **job):
    first = wsib(day(-100), day(-60), "A")        # covers day -100 .. -60
    second = wsib(day(second_issued_offset), day(second_issued_offset + 30), "B")
    return one([{"name": "S", "clearance": second, "clearances": [first], "insurance": INS}], **job)


def test_consecutive_certificates_leave_no_gap_and_one_missing_day_is_a_gap():
    assert "clearance_gap" not in codes(audit(gap_job(-59), on=ON))      # starts the very next day
    got = [f for f in audit(gap_job(-58), on=ON) if f.code == "clearance_gap"]
    assert len(got) == 1 and day(-59) in got[0].detail                 # exactly one missing day


def test_gap_is_reported_only_when_it_touches_the_job():
    # the gap is days -59..-41
    before = gap_job(-40, start=day(-30), end=day(100))                  # job starts after the gap
    assert "clearance_gap" not in codes(audit(before, on=ON))
    touching = gap_job(-40, start=day(-41), end=day(100))               # job starts on the gap's last day
    assert "clearance_gap" in codes(audit(touching, on=ON))
    after = gap_job(-40, start=day(-100), end=day(-60))                  # job ends the day before the gap
    assert "clearance_gap" not in codes(audit(after, on=ON))
    on_end = gap_job(-40, start=day(-100), end=day(-59))                 # job ends on the gap's first day
    assert "clearance_gap" in codes(audit(on_end, on=ON))


def test_gap_with_issue_date_only_uses_ninety_days_for_wsib_but_not_for_other_boards():
    ontario = one([{"name": "S", "clearance": wsib(day(0)), "clearances": [wsib(day(-300), None, "A")],
                    "insurance": INS}], start=day(-300), end=day(60))
    assert "clearance_gap" in codes(audit(ontario, on=ON))
    other = one([{"name": "S", "clearance": {"issuer": "Acme Board", "issued": day(0), "number": "B"},
                  "clearances": [{"issuer": "Acme Board", "issued": day(-300), "number": "A"}], "insurance": INS}],
                province="BC", start=day(-300), end=day(60))
    assert "clearance_gap" not in codes(audit(other, on=ON))              # no stated expiry: no span, no claim


def test_gap_uses_stated_expiry_for_other_boards():
    sub = {"name": "S", "clearance": {"issuer": "Acme Board", "issued": day(0), "expires": day(30), "number": "B"},
           "clearances": [{"issuer": "Acme Board", "issued": day(-300), "expires": day(-250), "number": "A"}],
           "insurance": INS}
    assert "clearance_gap" in codes(audit(one([sub], province="BC", start=day(-300), end=day(60)), on=ON))


def test_a_one_day_certificate_still_counts_as_cover():
    one_day = wsib(day(-59), day(-59), "A")
    sub = {"name": "S", "clearance": wsib(day(-58), day(30), "B"),
           "clearances": [wsib(day(-100), day(-60), "C"), one_day], "insurance": INS}
    assert "clearance_gap" not in codes(audit(one([sub], start=day(-100), end=day(20)), on=ON))


# ---- certificate sanity ----------------------------------------------------------------------------------

def test_expiry_on_the_issue_day_is_not_inconsistent_but_the_day_before_is():
    same = one([{"name": "S", "clearance": wsib(day(-3), day(-3)), "insurance": INS}])
    assert "clearance_dates_inconsistent" not in codes(audit(same, on=ON))
    earlier = one([{"name": "S", "clearance": wsib(day(-3), day(-4)), "insurance": INS}])
    assert "clearance_dates_inconsistent" in codes(audit(earlier, on=ON))


def test_missing_certificate_number_is_named_as_such():
    j = one([{"name": "S", "clearance": {"issuer": "WSIB", "issued": day(-3), "expires": day(-4)}, "insurance": INS}])
    msg = [f.detail for f in audit(j, on=ON) if f.code == "clearance_dates_inconsistent"][0]
    assert "(no number)" in msg
    j2 = one([{"name": "S", "clearance": wsib(day(-3), day(-4), "77"), "insurance": INS}])
    assert "clearance 77:" in [f.detail for f in audit(j2, on=ON) if f.code == "clearance_dates_inconsistent"][0]


def test_issue_date_today_is_fine_tomorrow_is_a_typo_warning():
    today = dt.date.today()
    ok = one([{"name": "S", "clearance": wsib(today.isoformat(), (today + dt.timedelta(days=60)).isoformat()),
               "insurance": INS}])
    assert "clearance_issued_in_future" not in codes(audit(ok, on=today))
    soon = today + dt.timedelta(days=1)
    bad = one([{"name": "S", "clearance": wsib(soon.isoformat(), (soon + dt.timedelta(days=60)).isoformat()),
                "insurance": INS}])
    assert "clearance_issued_in_future" in codes(audit(bad, on=today))


def test_newest_certificate_by_expiry_decides_even_if_issued_earlier():
    long_one = wsib(day(-80), day(200), "A")        # issued earlier, expires later
    short_one = wsib(day(-5), day(-1), "B")         # issued later, already expired
    j = one([{"name": "S", "clearance": short_one, "clearances": [long_one], "insurance": INS}])
    assert "clearance_expired" not in codes(audit(j, on=ON))


def test_other_board_with_only_an_issue_date_says_no_rule_is_modelled_and_with_nothing_says_so():
    issued_only = one([{"name": "S", "clearance": {"issuer": "Acme Board", "issued": day(-3)}, "insurance": INS}],
                      province="BC")
    msg = [f.detail for f in audit(issued_only, on=ON) if f.code == "clearance_no_expiry"][0]
    assert "no rule is modelled" in msg
    nothing = one([{"name": "S", "clearance": {"issuer": "Acme Board", "number": "1"}, "insurance": INS}],
                  province="BC")
    msg2 = [f.detail for f in audit(nothing, on=ON) if f.code == "clearance_no_expiry"][0]
    assert "neither expiry nor issue date" in msg2


def test_work_start_check_applies_when_the_letter_is_albertan_even_if_the_job_province_is_not():
    j = one([{"name": "S", "start": day(-30), "clearance": {"issuer": "WCB-AB", "issued": day(-10)},
              "insurance": INS}], province="BC")
    assert "clearance_after_work_started" in codes(audit(j, on=ON))


# ---- the "job is longer than one 90-day clearance" rule --------------------------------------------------

@pytest.mark.parametrize("job_end,expect", [(90, "error"), (91, "warn")])
def test_long_job_rule_switches_at_exactly_ninety_days(job_end, expect):
    j = one([{"name": "S", "clearance": wsib(day(-20), day(40)), "insurance": INS}], end=day(job_end))
    f = [x for x in audit(j, on=ON) if x.code == "clearance_expires_during_job"]
    assert len(f) == 1 and f[0].severity == expect


@pytest.mark.parametrize("exp_off,code", [(30, "renewal_due"), (31, "clearance_expires_during_job")])
def test_on_a_long_job_the_renewal_label_applies_up_to_the_horizon_day(exp_off, code):
    j = one([{"name": "S", "clearance": wsib(day(exp_off - 60), day(exp_off)), "insurance": INS}], end=day(200))
    got = [x.code for x in audit(j, on=ON, horizon=30) if x.code in ("renewal_due", "clearance_expires_during_job")]
    assert got == [code]


# ---- payments --------------------------------------------------------------------------------------------

def test_certificate_expiring_on_the_payment_day_covers_it_and_the_day_after_does_not():
    for pay_off, bad in ((30, False), (31, True)):
        j = one([{"name": "S", "clearance": wsib(day(-5), day(30)), "insurance": INS}], payment_dates=[day(pay_off)])
        assert ("clearance_not_valid_at_payment" in codes(audit(j, on=ON))) == bad


def test_certificate_issued_after_the_payment_day_does_not_cover_it():
    j = one([{"name": "S", "clearance": wsib(day(10), day(100)), "insurance": INS}], payment_dates=[day(5)])
    assert "clearance_not_valid_at_payment" in codes(audit(j, on=ON))
    j2 = one([{"name": "S", "clearance": wsib(day(5), day(100)), "insurance": INS}], payment_dates=[day(5)])
    assert "clearance_not_valid_at_payment" not in codes(audit(j2, on=ON))


# ---- job dates -------------------------------------------------------------------------------------------

def test_a_one_day_job_is_valid_and_an_end_before_the_start_is_not():
    assert "job_dates_invalid" not in codes(audit(one([], start=day(0), end=day(0)), on=ON))
    assert "job_dates_invalid" in codes(audit(one([], start=day(1), end=day(0)), on=ON))


# ---- the limit parser's edges ----------------------------------------------------------------------------

def test_empty_and_none_are_reported_as_empty_not_unreadable():
    assert parse_limits(None) == ([], "empty") and parse_limits("") == ([], "empty")


def test_numeric_limits_zero_negative_and_the_ceiling():
    assert parse_limits(0) == ([(0, False)], "")
    assert parse_limits(-1)[0] == [] and parse_limits(float("nan"))[0] == []
    assert parse_limits(MAX_LIMIT) == ([(MAX_LIMIT, False)], "")
    assert parse_limits(MAX_LIMIT + 1) == ([], "implausibly large")
    assert parse_limits("1000000000000") == ([(MAX_LIMIT, False)], "")
    assert parse_limits("1000000000001") == ([], "implausibly large")


def test_text_length_ceiling():
    assert parse_limits("2M" + " " * 1998)[0] == [(2_000_000, False)]
    assert parse_limits("2M" + " " * 1999) == ([], "too long to read safely")


def test_hyphen_is_a_label_after_a_letter_but_a_minus_sign_otherwise():
    assert parse_limits("CGL-2M") == ([(2_000_000, False)], "")
    assert parse_limits("-2M")[0] == [] and parse_limits("x -2M")[0] == []


def test_bare_numbers_below_a_thousand_are_not_dollar_amounts_but_a_thousand_is():
    assert parse_limits("1000") == ([(1000, False)], "")
    assert parse_limits("999")[0] == []
    assert parse_limits("$999") == ([(999, False)], "")
