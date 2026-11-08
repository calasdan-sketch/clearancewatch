"""Round 5: author line, Manitoba (WCB), broker-style insurance text, spreadsheet import, old-version files."""
import datetime as dt
import io
import json
import os
import re
import sys

import pytest

import clearancewatch
from clearancewatch import Job, audit
from clearancewatch.cli import ACTIONS, main
from clearancewatch.money import mentions_excess, parse_limits

ROOT = os.path.join(os.path.dirname(__file__), "..")
ON = dt.date(2026, 6, 1)
AUTHOR = "Calas Automations Inc."


def codes(findings, severity=None):
    return sorted(f.code for f in findings if severity in (None, f.severity))


def mb_job(sub, **job):
    base = {"name": "Winnipeg infill", "province": "MB", "start": "2026-05-01", "end": "2026-08-31", "subs": [sub]}
    base.update(job)
    return Job.from_dict(base)


def ins(**kw):
    d = {"provider": "A", "policy": "P", "coverage": "C$2M", "expires": "2027-06-01"}
    d.update(kw)
    return d


# ---- author line -----------------------------------------------------------------------------------------

def test_author_string_is_pinned_everywhere():
    assert clearancewatch.__author__ == AUTHOR
    read = lambda *p: open(os.path.join(ROOT, *p), encoding="utf-8").read()  # noqa: E731
    py = read("pyproject.toml")
    assert 'authors = [{ name = "Calas Automations Inc." }]' in py
    assert 'maintainers = [{ name = "Calas Automations Inc." }]' in py
    assert "Copyright (c) 2026 Calas Automations Inc." in read("LICENSE")
    assert "calasdan" not in read("LICENSE")
    assert "Calas Automations Inc." in read("README.md")


def test_about_and_ics_carry_the_author(tmp_path, capsys):
    assert main(["about"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"clearancewatch {clearancewatch.__version__}\n") and AUTHOR in out and "MIT" in out
    jobs = tmp_path / "j.json"
    jobs.write_text(json.dumps([{"name": "J", "province": "ON", "end": "2026-12-31", "subs": [
        {"name": "S", "clearance": {"issuer": "WSIB", "issued": "2026-05-20"},
         "insurance": ins(expires="2026-06-10")}]}]))
    main(["audit", str(jobs), "--on", "2026-06-01", "--format", "ics"])
    assert "PRODID:-//Calas Automations Inc.//clearancewatch//EN" in capsys.readouterr().out


def test_version_flag_is_still_one_line(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out == f"clearancewatch {clearancewatch.__version__}\n"


# ---- Manitoba --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("issuer", ["WCB Manitoba", "WCB-MB", "Workers Compensation Board of Manitoba",
                                    "WCBMB", "WCB", ""])
def test_manitoba_letter_current_is_clean(issuer):
    j = mb_job({"name": "Prairie Framing", "clearance": {"issuer": issuer, "number": "77", "issued": "2026-05-20",
                                                         "covered_until": "2026-08-31"}, "insurance": ins()})
    assert codes(audit(j, on=ON)) == []


def test_manitoba_letter_without_expiry_is_a_letter_not_a_ninety_day_certificate():
    j = mb_job({"name": "S", "clearance": {"issuer": "WCB Manitoba", "issued": "2026-05-20"}, "insurance": ins()})
    got = audit(j, on=ON)
    assert "clearance_cover_lapsed" in codes(got)          # work continues to 31 Aug, letter is dated 20 May
    assert "clearance_expired" not in codes(got) and "clearance_no_expiry" not in codes(got)


def test_manitoba_job_with_bare_wcb_issuer_is_read_as_manitoba_letter():
    j = mb_job({"name": "S", "clearance": {"issuer": "WCB", "issued": "2026-05-20"}, "insurance": ins()})
    assert "clearance_no_expiry" not in codes(audit(j, on=ON))


def test_manitoba_job_with_ontario_certificate_is_a_mismatch():
    j = mb_job({"name": "S", "clearance": {"issuer": "WSIB", "issued": "2026-05-20", "expires": "2026-09-01"},
                "insurance": ins()})
    assert "issuer_mismatch" in codes(audit(j, on=ON))


def test_alberta_letter_on_manitoba_job_is_a_mismatch_and_vice_versa():
    a = mb_job({"name": "S", "clearance": {"issuer": "WCB-AB", "issued": "2026-05-20"}, "insurance": ins()})
    assert "issuer_mismatch" in codes(audit(a, on=ON))
    b = Job.from_dict({"name": "J", "province": "AB", "end": "2026-08-31", "subs": [
        {"name": "S", "clearance": {"issuer": "WCB Manitoba", "issued": "2026-05-20"}, "insurance": ins()}]})
    assert "issuer_mismatch" in codes(audit(b, on=ON))


def test_manitoba_payment_check_names_the_right_board():
    j = mb_job({"name": "S", "clearance": {"issuer": "WCB Manitoba", "issued": "2026-05-20"}, "insurance": ins()},
               payment_dates=["2026-06-30"])
    f = [x for x in audit(j, on=ON) if x.code == "clearance_not_valid_at_payment"]
    assert len(f) == 1 and "WCB Manitoba" in f[0].detail and "Alberta" not in f[0].detail


def test_alberta_payment_message_still_says_alberta():
    j = Job.from_dict({"name": "J", "province": "AB", "payment_dates": ["2026-06-30"], "subs": [
        {"name": "S", "clearance": {"issuer": "WCB-AB", "issued": "2026-05-20"}, "insurance": ins()}]})
    f = [x for x in audit(j, on=ON) if x.code == "clearance_not_valid_at_payment"]
    assert "WCB Alberta" in f[0].detail


@pytest.mark.parametrize("status,code,sev", [
    ("deemed worker", "clearance_status_deemed_worker", "warn"),
    ("Deemed Worker", "clearance_status_deemed_worker", "warn"),
    ("deemed/default", "clearance_status_not_good", "error"),
    ("Deemed / Defaulted", "clearance_status_not_good", "error"),
    ("not in good standing", "clearance_status_not_good", "error"),
    ("NOT in good standing", "clearance_status_not_good", "error"),
    ("pending", "clearance_status_unrecognised", "warn"),
])
def test_manitoba_status_words(status, code, sev):
    j = mb_job({"name": "S", "clearance": {"issuer": "WCB Manitoba", "issued": "2026-05-20", "status": status},
                "insurance": ins()})
    hit = [f for f in audit(j, on=ON) if f.code == code]
    assert len(hit) == 1 and hit[0].severity == sev


@pytest.mark.parametrize("status", ["good standing", "In Good Standing", ""])
def test_good_standing_or_no_status_adds_nothing(status):
    j = mb_job({"name": "S", "clearance": {"issuer": "WCB Manitoba", "issued": "2026-05-20", "status": status,
                                           "covered_until": "2026-08-31"}, "insurance": ins()})
    assert not [c for c in codes(audit(j, on=ON)) if c.startswith("clearance_status")]


def test_status_only_clearance_is_not_blank_so_it_is_checked():
    j = mb_job({"name": "S", "clearance": {"status": "deemed/default"}, "insurance": ins()})
    assert "clearance_status_not_good" in codes(audit(j, on=ON))


def test_supply_only_is_a_note_not_an_error_and_only_without_a_clearance():
    j = mb_job({"name": "Lumber yard", "supply_only": True, "insurance": ins()})
    got = audit(j, on=ON)
    assert codes(got) == ["clearance_supply_only"] and got[0].severity == "info"
    j2 = mb_job({"name": "Lumber yard", "supply_only": False, "insurance": ins()})
    assert "clearance_missing" in codes(audit(j2, on=ON))


def test_supply_only_must_be_true_or_false():
    with pytest.raises(clearancewatch.DataError):
        Job.from_dict({"name": "J", "subs": [{"name": "S", "supply_only": "yes"}]})


def test_clearance_dated_after_the_sub_started_work_is_flagged_in_manitoba_and_alberta():
    sub = {"name": "S", "start": "2026-05-01", "clearance": {"issuer": "WCB Manitoba", "issued": "2026-05-20",
           "covered_until": "2026-08-31"}, "insurance": ins()}
    assert "clearance_after_work_started" in codes(audit(mb_job(sub), on=ON))
    ab_sub = dict(sub, clearance={"issuer": "WCB-AB", "issued": "2026-05-20"})
    ab = Job.from_dict({"name": "J", "province": "AB", "subs": [ab_sub]})
    assert "clearance_after_work_started" in codes(audit(ab, on=ON))


def test_earlier_certificate_in_history_satisfies_before_work_starts():
    sub = {"name": "S", "start": "2026-05-01",
           "clearance": {"issuer": "WCB Manitoba", "issued": "2026-05-20", "covered_until": "2026-08-31"},
           "clearances": [{"issuer": "WCB Manitoba", "issued": "2026-04-20"}], "insurance": ins()}
    assert "clearance_after_work_started" not in codes(audit(mb_job(sub), on=ON))


def test_work_start_check_does_not_apply_to_ontario():
    j = Job.from_dict({"name": "J", "province": "ON", "end": "2026-12-01", "subs": [
        {"name": "S", "start": "2026-05-01", "clearance": {"issuer": "WSIB", "issued": "2026-05-20"},
         "insurance": ins()}]})
    assert "clearance_after_work_started" not in codes(audit(j, on=ON))


def test_ontario_behaviour_is_unchanged_by_manitoba_support():
    j = Job.from_dict({"name": "J", "province": "ON", "end": "2026-08-01", "subs": [
        {"name": "S", "clearance": {"issuer": "WSIB", "issued": "2026-02-01"}, "insurance": ins()}]})
    assert codes(audit(j, on=ON), "error") == ["clearance_expired"]


# ---- insurance text the way brokers write it -------------------------------------------------------------

@pytest.mark.parametrize("text,expect", [
    ("$2M per occurrence, $5,000 deductible", [(2_000_000, True)]),
    ("$5,000 deductible; $2M", [(2_000_000, False)]),
    ("deductible: $5,000, $2M per occurrence", [(2_000_000, True)]),
    ("SIR $10,000 / $2M occurrence", [(2_000_000, True)]),
    ("$2M CGL, 10k retention", [(2_000_000, False)]),
])
def test_deductibles_are_not_limits(text, expect):
    assert parse_limits(text) == (expect, "")


@pytest.mark.parametrize("text", ["1/2M", "2/4M", "1 of 2, $2M CGL"])
def test_small_bare_numbers_are_unreadable_not_a_dollar_limit(text):
    amounts, problem = parse_limits(text)
    assert amounts == [] and "not a dollar amount" in problem


def test_dollar_amounts_under_a_thousand_with_a_sign_still_read():
    assert parse_limits("$500") == ([(500, False)], "")


def test_deductible_does_not_cause_a_false_below_minimum_error():
    j = Job.from_dict({"name": "J", "requirements": {"min_liability": "C$2M"}, "subs": [
        {"name": "S", "insurance": ins(coverage="$5,000 deductible, C$2M per occurrence")}]})
    assert "insurance_below_minimum" not in codes(audit(j, on=ON))


def test_shorthand_limit_warns_instead_of_claiming_one_dollar():
    j = Job.from_dict({"name": "J", "requirements": {"min_liability": "C$1M"}, "subs": [
        {"name": "S", "insurance": ins(coverage="1/2M")}]})
    got = audit(j, on=ON)
    assert "insurance_limit_unreadable" in codes(got) and "insurance_below_minimum" not in codes(got)


def test_umbrella_text_downgrades_below_minimum_to_a_question():
    j = Job.from_dict({"name": "J", "requirements": {"min_liability": "C$2M"}, "subs": [
        {"name": "S", "insurance": ins(coverage="C$1M + C$1M umbrella")}]})
    got = [f for f in audit(j, on=ON) if f.code.startswith("insurance")]
    assert codes(got) == ["insurance_limit_includes_umbrella"] and got[0].severity == "warn"
    j2 = Job.from_dict({"name": "J", "requirements": {"min_liability": "C$2M"}, "subs": [
        {"name": "S", "insurance": ins(coverage="C$1M")}]})
    assert [c for c in codes(audit(j2, on=ON)) if c.startswith("insurance")] == ["insurance_below_minimum"]


def test_mentions_excess_is_whole_word():
    assert mentions_excess("1M primary, 5M Excess") and mentions_excess("umbrella")
    assert not mentions_excess("excessive") and not mentions_excess(None) and not mentions_excess(5)


# ---- spreadsheet import ----------------------------------------------------------------------------------

CSV = (
    "Job,Province,Start,End,Sub,Trade,Clearance issuer,Clearance number,Clearance issued,Clearance covered until,"
    "Insurance coverage,Insurance expires,Licence name,Licence expires\n"
    "Winnipeg infill,MB,2026-05-01,2026-08-31,Prairie Framing,framing,WCB Manitoba,77,2026-05-20,2026-08-31,"
    "C$2M,2027-06-01,,\n"
    "Winnipeg infill,,,,Prairie Framing,,,,,,,,Fall protection,2027-01-01\n"
    "Winnipeg infill,,,,Red River Electric,electrical,WCB Manitoba,78,2026-05-21,2026-08-31,"
    "C$2M,2027-06-01,Electrician,2027-01-01\n"
    "Second job,ON,2026-06-01,2026-07-01,Bob's Drywall,drywall,WSIB,1,2026-05-20,,C$2M,2027-06-01,,\n"
)


def test_import_csv_round_trips_into_a_clean_audit(tmp_path, capsys):
    src, out = tmp_path / "subs.csv", tmp_path / "jobs.json"
    src.write_text(CSV, encoding="utf-8")
    assert main(["import-csv", str(src), "-o", str(out)]) == 0
    jobs = json.loads(out.read_text(encoding="utf-8"))
    assert [j["name"] for j in jobs] == ["Winnipeg infill", "Second job"]
    assert [s["name"] for s in jobs[0]["subs"]] == ["Prairie Framing", "Red River Electric"]
    assert jobs[0]["subs"][0]["licences"] == [{"name": "Fall protection", "expires": "2027-01-01"}]
    assert "read 4 row(s) into 2 job(s)" in capsys.readouterr().err
    assert main(["audit", str(out), "--on", "2026-06-01", "--fail-on", "never", "--format", "json"]) == 0


def test_import_csv_accepts_excel_unicode_text_and_utf8_bom(tmp_path, capsys):
    for enc in ("utf-16", "utf-8-sig"):
        src = tmp_path / "s.csv"
        src.write_bytes(CSV.encode(enc))
        assert main(["import-csv", str(src)]) == 0
        assert json.loads(capsys.readouterr().out)[0]["name"] == "Winnipeg infill"


@pytest.mark.parametrize("body,needle", [
    ("", "empty"),
    ("job,sub\n", "no rows"),
    ("job,sub,colour\nJ,S,red\n", "unknown column"),
    ("job,job,sub\nJ,J,S\n", "twice"),
    ("sub\nS\n", "'job' column"),
    ("job,sub\n,S\n", "row 2"),
    ("job,sub,start\nJ,S,2/15/2026\n", "got '2/15/2026'"),
    ("job,sub,supply_only\nJ,S,maybe\n", "yes or no"),
    ("job,sub,province\nJ,S,ON\nJ,T,MB\n", "differs"),
    ("job,sub\nJ,S,extra,cells\n", "cells"),
])
def test_import_csv_refuses_bad_files_with_plain_errors(tmp_path, capsys, body, needle):
    src = tmp_path / "s.csv"
    src.write_text(body, encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        main(["import-csv", str(src)])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert needle in err and "Traceback" not in err


def test_import_csv_missing_file_and_folder(tmp_path, capsys):
    for target in (str(tmp_path / "nope.csv"), str(tmp_path)):
        with pytest.raises(SystemExit) as e:
            main(["import-csv", target])
        assert e.value.code == 2
    assert "clearancewatch: import-csv:" in capsys.readouterr().err


def test_import_csv_reads_stdin(monkeypatch, capsys):
    class Stdin:
        buffer = io.BytesIO(CSV.encode("utf-8"))
    monkeypatch.setattr(sys, "stdin", Stdin())
    assert main(["import-csv", "-"]) == 0


# ---- files written for clearancewatch 0.1.0 --------------------------------------------------------------

def test_a_0_1_0_json_report_still_works_as_a_baseline(tmp_path):
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps([{"name": "Old job", "province": "ON", "end": "2026-12-31",
                                 "subs": [{"name": "Sub A"}]}]))
    old = tmp_path / "old.json"   # the shape 0.1.0 printed: no schema/version, no job/sub keys
    old.write_text(json.dumps({"errors": 1, "warnings": 0, "findings": [
        {"severity": "error", "code": "insurance_missing", "subject": "Old job / Sub A",
         "detail": "no insurance on file"},
        {"severity": "error", "code": "clearance_missing", "subject": "Old job / Sub A",
         "detail": "no clearance certificate on file"}]}))
    assert main(["audit", str(jobs), "--on", "2026-06-01", "--baseline", str(old), "--format", "json",
                 "-o", str(tmp_path / "r.json")]) == 0
    doc = json.loads((tmp_path / "r.json").read_text())
    assert doc["findings"] == [] and doc["baseline"]["known_hidden"] == 2


def test_0_1_0_shaped_job_files_load_unchanged():
    old = {"jobs": [{"name": "J", "province": "ON", "start": "2026-02-01", "end": "2026-03-30", "subcontractors": [
        {"name": "S", "province": "ON", "trade": "x",
         "clearance": {"issuer": "WSIB", "number": "1", "issued": "2026-01-10", "expires": "2026-04-10"},
         "insurance": {"provider": "A", "policy": "P", "coverage": "C$2M", "expires": "2026-12-31"},
         "licences": [{"name": "L", "number": "1", "authority": "TSSA", "expires": "2026-09-01"}]}]}]}
    job = Job.from_dict(old["jobs"][0])
    assert audit(job, on=dt.date(2026, 2, 15)) == []


def test_every_new_code_has_an_action_and_is_documented():
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    for code in ("clearance_after_work_started", "clearance_status_not_good", "clearance_status_deemed_worker",
                 "clearance_status_unrecognised", "clearance_supply_only", "insurance_limit_includes_umbrella"):
        assert ACTIONS[code] and f"`{code}`" in readme


def test_readme_names_the_manitoba_sources_and_date():
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    assert "wcb.mb.ca/clearances" in readme and "W200" in readme and re.search(r"2026-11-0\d", readme)
