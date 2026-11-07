"""Tests added after the expert deep-dive: bad data, hostile text, new checks."""
import csv
import datetime as dt
import io
import json

import pytest

from clearancewatch.audit import _issuer_family, audit, renewals
from clearancewatch.cli import main as _main
from clearancewatch.model import Clearance, DataError, Insurance, Job, Subcontractor, parse_date
from clearancewatch.money import parse_limit
from clearancewatch.safe import clean, csv_cell

D = dt.date.fromisoformat


def main(argv):
    """Exit code, whether main() returns it or raises SystemExit (bad input does)."""
    try:
        return _main(argv)
    except SystemExit as e:
        return e.code


def job_dict(**kw):
    base = {"name": "J", "province": "ON", "start": "2026-02-01", "end": "2026-03-30",
            "subs": [{"name": "S", "clearance": {"issuer": "WSIB", "number": "1", "issued": "2026-01-10",
                                                 "expires": "2026-04-10"},
                      "insurance": {"provider": "A", "policy": "P", "coverage": "C$2M", "expires": "2026-12-31"}}]}
    base.update(kw)
    return base


def codes(job, on="2026-02-15", **kw):
    return [f.code for f in audit(Job.from_dict(job), on=D(on), **kw)]


def write(tmp, data, name="jobs.json"):
    p = tmp / name
    p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return str(p)


# ---- input robustness -------------------------------------------------

@pytest.mark.parametrize("bad", ["2026-13-01", "20260101", "2026-1-5", 20260101, "tomorrow", "2026-02-30", True,
                                 "9999-12-31", "0001-01-01"])
def test_strict_dates_reject_garbage(bad):
    with pytest.raises(DataError):
        parse_date(bad, "x")


def test_bad_date_names_the_field(tmp_path, capsys):
    j = job_dict()
    j["subs"][0]["clearance"]["expires"] = "04/10/2026"
    assert main(["audit", write(tmp_path, [j])]) == 2
    err = capsys.readouterr().err
    assert "jobs[0].subs[0].clearance.expires" in err and "Traceback" not in err


@pytest.mark.parametrize("payload", ["[1, 2]", '"text"', "[]", "{}", "[{\"subs\": 5}]", '[{"subs": [3]}]',
                                     '[{"name": {"a": 1}}]', "[" * 5000 + "]" * 5000, "\u0000"],
                         ids=["list-of-ints", "string", "empty-list", "empty-object", "subs-not-list",
                              "sub-not-object", "name-is-object", "deep-nesting", "nul-byte"])
def test_malformed_files_exit_2_not_traceback(tmp_path, payload, capsys):
    assert main(["audit", write(tmp_path, payload)]) == 2
    assert "Traceback" not in capsys.readouterr().err


def test_bom_and_missing_and_folder(tmp_path):
    p = tmp_path / "b.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps([job_dict()]).encode())
    assert main(["audit", str(p), "--on", "2026-02-15"]) == 0
    assert main(["audit", str(tmp_path / "nope.json")]) == 2
    assert main(["audit", str(tmp_path)]) == 2


def test_non_utf8_exits_2(tmp_path):
    p = tmp_path / "l.json"
    p.write_bytes(b"[\xff\xfe]")
    assert main(["audit", str(p)]) == 2


def test_empty_file_does_not_silently_pass(tmp_path):
    assert main(["audit", write(tmp_path, "[]")]) == 2


def test_bad_flags_exit_2(tmp_path):
    p = write(tmp_path, [job_dict()])
    for argv in (["audit", p, "--on", "nonsense"], ["audit", p, "--within", "-5"]):
        assert main(argv) == 2


def test_typo_field_is_reported():
    assert "unknown_field" in codes(job_dict(subs=[{"name": "S", "clearence": {}}]))


# ---- jurisdiction rules -----------------------------------------------

@pytest.mark.parametrize("issuer,family", [("WSIB", "ON"), ("WCB-AB", "AB"), ("WCB Alberta", "AB"),
                                           ("WCB Labrador", "WCB"), ("WCB-NL", "WCB"), ("WorkSafeBC", ""),
                                           ("Workers' Compensation Board of Alberta", "AB"), ("", "")])
def test_issuer_family_whole_words(issuer, family):
    assert _issuer_family(issuer) == family


def test_ninety_day_default_not_applied_to_other_boards():
    j = job_dict(province="BC")
    j["subs"][0]["clearance"] = {"issuer": "WorkSafeBC", "issued": "2026-01-10"}
    found = codes(j)
    assert "clearance_no_expiry" in found and "province_not_modelled" in found


def test_province_names_normalised():
    sub = {"name": "S", "clearance": {"issuer": "WCB-AB", "issued": "2026-01-10"}}
    assert "issuer_mismatch" in codes(job_dict(province="ontario", subs=[sub]))


def test_generic_wcb_on_ontario_job_warns():
    j = job_dict(subs=[{"name": "S", "clearance": {"issuer": "WCB", "issued": "2026-01-10",
                                                   "expires": "2026-04-10"}}])
    assert "issuer_mismatch" in codes(j)


# ---- document QA --------------------------------------------------------

def test_expiry_before_issue_is_error():
    j = job_dict()
    j["subs"][0]["clearance"].update(issued="2026-04-10", expires="2026-01-10")
    assert "clearance_dates_inconsistent" in codes(j)


def test_wsib_term_over_90_days_flagged():
    j = job_dict()
    j["subs"][0]["clearance"].update(issued="2026-01-01", expires="2026-12-31")
    assert "clearance_term_exceeds_90_days" in codes(j)


def test_future_issue_date_flagged():
    j = job_dict()
    j["subs"][0]["clearance"].update(issued="2100-01-01", expires="2100-03-01")
    assert "clearance_issued_in_future" in codes(j)


def test_shared_clearance_number_and_duplicate_sub():
    s = job_dict()["subs"][0]
    j = job_dict(subs=[dict(s, name="A"), dict(s, name="B"), dict(s, name="b")])
    found = codes(j)
    assert "clearance_number_shared" in found and found.count("duplicate_sub") == 1


def test_job_end_before_start():
    assert "job_dates_invalid" in codes(job_dict(start="2026-05-01", end="2026-04-01"))


def test_gap_between_certificates_inside_job():
    s = {"name": "S", "insurance": {"provider": "A", "coverage": "C$2M", "expires": "2026-12-31"},
         "clearances": [{"issuer": "WSIB", "number": "1", "issued": "2026-01-01", "expires": "2026-03-31"},
                        {"issuer": "WSIB", "number": "2", "issued": "2026-04-20", "expires": "2026-07-18"}]}
    j = job_dict(end="2026-07-01", subs=[s])
    found = codes(j, on="2026-05-01")
    assert "clearance_gap" in found and "clearance_missing" not in found
    # a gap entirely before the job is not this job's problem
    assert "clearance_gap" not in codes(dict(j, start="2026-05-01"), on="2026-05-02")


def test_history_uses_latest_certificate_for_expiry():
    s = job_dict()["subs"][0]
    s["clearances"] = [{"issuer": "WSIB", "number": "0", "issued": "2025-01-01", "expires": "2025-03-31"}]
    assert "clearance_expired" not in codes(job_dict(subs=[s]))


# ---- insurance minimums ------------------------------------------------

@pytest.mark.parametrize("text,amount", [("C$2M", 2_000_000), ("$2,000,000", 2_000_000), ("2 million", 2_000_000),
                                         ("$1.5M general liability", 1_500_000), ("500k", 500_000),
                                         (5_000_000, 5_000_000), ("2000000", 2_000_000)])
def test_parse_limit(text, amount):
    assert parse_limit(text) == (amount, "")


@pytest.mark.parametrize("text", ["", None, "US$2M", "unlimited", True, -5, "EUR 3M"])
def test_parse_limit_refuses_to_guess(text):
    amount, problem = parse_limit(text)
    assert amount is None and problem


def test_min_liability_enforced():
    j = job_dict(requirements={"min_liability": "C$2M"})
    j["subs"][0]["insurance"]["coverage"] = "C$1M"
    assert "insurance_below_minimum" in codes(j)
    j["subs"][0]["insurance"]["coverage"] = "US$5M"
    assert "insurance_limit_unreadable" in codes(j)
    j["subs"][0]["insurance"]["coverage"] = "C$5M"
    assert not {"insurance_below_minimum", "insurance_limit_unreadable"} & set(codes(j))


def test_bad_requirement_rejected():
    with pytest.raises(DataError):
        Job.from_dict(job_dict(requirements={"min_liability": "lots"}))


# ---- hostile text -----------------------------------------------------

def test_clean_strips_escapes_bidi_zero_width():
    out = clean("a\x1b[31mred\u202ereversed\u200bz\r\nnewline")
    assert "\x1b" not in out and "\u202e" not in out and "\u200b" not in out and "\n" not in out
    assert "\\u001b" in out


def test_csv_formula_guard():
    assert csv_cell("=1+1").startswith("'") and csv_cell("@x").startswith("'")


def test_outputs_are_safe(tmp_path, capsys):
    j = job_dict(name="Tower\x1b[2J\u202e")
    j["subs"][0]["name"] = "=HYPERLINK(\"http://x\")\nINJECT | col"
    j["subs"][0].pop("insurance")
    p = write(tmp_path, [j])
    for fmt in ("text", "csv", "md"):
        main(["audit", p, "--on", "2026-02-15", "--format", fmt])
        out = capsys.readouterr().out
        assert "\x1b" not in out and "\u202e" not in out
    main(["audit", p, "--on", "2026-02-15", "--format", "csv"])
    rows = list(csv.reader(io.StringIO(capsys.readouterr().out)))
    assert rows[0][0] == "severity" and all(not r[3].startswith("=") for r in rows[1:])
    assert all(len(r) == 6 for r in rows)  # newline in a name cannot add rows/columns


def test_md_chase_list_groups_by_sub(tmp_path, capsys):
    j = job_dict()
    j["subs"][0].pop("insurance")
    assert main(["audit", write(tmp_path, [j]), "--on", "2026-02-15", "--format", "md"]) == 1
    out = capsys.readouterr().out
    assert "## J / S" in out and "certificate of insurance" in out and "Not legal advice" in out


# ---- exit codes / renewals ---------------------------------------------

def test_fail_on_warn_and_never(tmp_path):
    j = job_dict(end="2026-02-28")
    j["subs"][0]["clearance"].update(issued="2026-01-20", expires="2026-03-10")
    p = write(tmp_path, [j])
    assert main(["audit", p, "--on", "2026-02-15"]) == 0
    assert main(["audit", p, "--on", "2026-02-15", "--fail-on", "warn"]) == 1
    j["subs"][0].pop("insurance")
    p = write(tmp_path, [j], "j2.json")
    assert main(["audit", p, "--on", "2026-02-15", "--fail-on", "never"]) == 0


def test_json_output_has_job_and_sub(tmp_path, capsys):
    j = job_dict()
    j["subs"][0].pop("insurance")
    main(["audit", write(tmp_path, [j]), "--on", "2026-02-15", "--json"])
    f = json.loads(capsys.readouterr().out)["findings"][0]
    assert f["job"] == "J" and f["sub"] == "S"


def test_renewals_include_during_job_is_opt_in():
    j = Job.from_dict(job_dict())
    j.subs[0].clearance.expires = D("2026-03-15")  # expires before job end, 28 days out -> listed either way
    j.subs[0].insurance.expires = D("2026-03-20")
    j.end = D("2026-06-30")
    base = renewals([j], within=5, on=D("2026-02-15"))
    more = renewals([j], within=5, on=D("2026-02-15"), include_during_job=True)
    assert len(more) > len(base) == 0


def test_python_api_unchanged():
    sub = Subcontractor(name="n", clearance=Clearance(issuer="WSIB", issued=D("2026-01-10")),
                        insurance=Insurance(provider="a", expires=D("2026-12-31")))
    assert audit(Job(name="j", province="ON", end=D("2026-03-01"), subs=[sub]), on=D("2026-02-01")) == []
