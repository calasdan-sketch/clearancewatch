"""Round 3: broker/auditor/attacker/DX findings. Pinned dates; no network."""
import copy
import io
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from clearancewatch import __version__  # noqa: F401
from clearancewatch.audit import audit
from clearancewatch.cli import main as _main
from clearancewatch.model import DataError, Insurance, Job, Licence, Requirements, Subcontractor
from clearancewatch.money import parse_limit, parse_limits
from clearancewatch.schema import TEMPLATE, jobs_schema

import datetime as dt

D = dt.date.fromisoformat
ROOT = Path(__file__).resolve().parent.parent


def main(argv):
    try:
        return _main(argv)
    except SystemExit as e:
        return e.code


def jd(**kw):
    base = {"name": "J", "province": "ON", "start": "2026-02-01", "end": "2026-03-30",
            "subs": [{"name": "S", "trade": "electrical",
                      "clearance": {"issuer": "WSIB", "number": "1", "issued": "2026-01-10", "expires": "2026-04-10"},
                      "insurance": {"provider": "A", "policy": "P", "coverage": "C$2M", "expires": "2026-12-31"}}]}
    base.update(kw)
    return base


def found(job, on="2026-02-15", **kw):
    return audit(Job.from_dict(job), on=D(on), **kw)


def codes(job, on="2026-02-15", **kw):
    return [f.code for f in found(job, on, **kw)]


def write(tmp, data, name="jobs.json"):
    p = tmp / name
    p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return str(p)


# ---- insurance limits: what a broker actually types -------------------

@pytest.mark.parametrize("text", ["2 000 000", "$2.000.000", "1e6", "-5", "$-5", "1,5M", "$2,0", "9" * 400,
                                  "99999999999999999999M", float("inf"), float("nan"), 10 ** 30, "٢M", "x" * 5000])
def test_limits_that_used_to_misparse_or_crash_are_unreadable(text):
    amount, problem = parse_limit(text)
    assert amount is None and problem


@pytest.mark.parametrize("text,amount", [("C$2MM", 2_000_000), ("2000000.50", 2_000_000), ("$ 2M", 2_000_000),
                                         ("CAD 2M", 2_000_000), ("$2,000,000 per occurrence, $5M aggregate", 2_000_000),
                                         ("$5M aggregate, $1M per occurrence", 1_000_000),
                                         ("each occurrence: $2,000,000 General aggregate: $4M", 2_000_000)])
def test_limits_read_correctly(text, amount):
    assert parse_limit(text) == (amount, "")


def test_parse_limits_lists_every_amount():
    assert [a for a, _ in parse_limits("C$1M / C$2M aggregate")[0]] == [1_000_000, 2_000_000]


def test_ambiguous_amounts_warn_instead_of_error():
    j = jd(requirements={"min_liability": "C$2M"})
    j["subs"][0]["insurance"]["coverage"] = "C$1M / C$2M aggregate"
    c = codes(j)
    assert "insurance_limit_ambiguous" in c and "insurance_below_minimum" not in c
    j["subs"][0]["insurance"]["coverage"] = "C$1M per occurrence / C$2M aggregate"
    assert "insurance_below_minimum" in codes(j)  # labelled: it really is below


def test_huge_limit_in_requirements_is_a_data_error_not_a_crash(tmp_path):
    p = write(tmp_path, [jd(requirements={"min_liability": "9" * 400})])
    assert main(["audit", p]) == 2


def test_absurd_json_integer_exits_2(tmp_path):
    p = write(tmp_path, '[{"name": "J", "requirements": {"min_liability": ' + "9" * 6000 + "}}]")
    assert main(["audit", p]) == 2


# ---- endorsements, licences, exemptions ---------------------------------

def test_required_endorsements():
    j = jd(requirements={"additional_insured": True, "waiver_of_subrogation": True})
    assert codes(j).count("insurance_endorsement_unconfirmed") == 2
    j["subs"][0]["insurance"].update(additional_insured=True, waiver_of_subrogation=False)
    c = codes(j)
    assert c == ["insurance_endorsement_missing"]
    j["subs"][0]["insurance"]["waiver_of_subrogation"] = True
    assert codes(j) == []


def test_endorsement_flags_must_be_real_booleans():
    j = jd()
    j["subs"][0]["insurance"]["additional_insured"] = "yes"
    with pytest.raises(DataError, match="additional_insured"):
        Job.from_dict(j)


def test_required_licence_missing_and_present():
    j = jd(requirements={"required_licences": {"Electrical": "electrician"}})
    assert "licence_missing" in codes(j)
    j["subs"][0]["licences"] = [{"name": "309A Electrician", "expires": "2027-01-01"}]
    assert "licence_missing" not in codes(j)
    j["subs"][0]["trade"] = "plumbing"  # rule is per trade
    j["subs"][0]["licences"] = []
    assert "licence_missing" not in codes(j)


def test_bad_required_licences_rejected():
    with pytest.raises(DataError):
        Job.from_dict(jd(requirements={"required_licences": {"electrical": ""}}))


def test_clearance_exempt_needs_a_reason_and_is_only_a_note():
    j = jd()
    j["subs"][0].pop("clearance")
    assert "clearance_missing" in codes(j)
    j["subs"][0]["clearance_exempt"] = "sole proprietor, no workers"
    fs = found(j)
    assert [f.code for f in fs if f.severity == "error"] == []
    assert any(f.code == "clearance_exempt" and f.severity == "info" for f in fs)


def test_info_never_fails_a_run(tmp_path, capsys):
    j = jd()
    j["subs"][0].pop("clearance")
    j["subs"][0]["clearance_exempt"] = "no employees"
    p = write(tmp_path, [j])
    assert main(["audit", p, "--on", "2026-02-15", "--fail-on", "warn"]) == 0
    out = capsys.readouterr().out
    assert "INFO" in out and "1 note(s)" in out and "PASS" in out


# ---- long jobs: a 90-day clearance cannot span them ---------------------

def test_job_longer_than_one_clearance_warns_not_errors():
    j = jd(end="2026-12-31")
    fs = found(j)
    f = [x for x in fs if x.code == "clearance_expires_during_job"]
    assert f and f[0].severity == "warn" and "renewal" in f[0].detail
    strict = found(j, strict_whole_job=True)
    assert [x for x in strict if x.code == "clearance_expires_during_job"][0].severity == "error"


def test_short_job_still_errors():
    j = jd(end="2026-04-20")
    assert [x.severity for x in found(j) if x.code == "clearance_expires_during_job"] == ["error"]


def test_long_job_near_expiry_is_a_renewal_due():
    j = jd(end="2026-12-31")
    assert "renewal_due" in codes(j, on="2026-04-01")


# ---- payment dates -------------------------------------------------------

def test_payment_after_clearance_expiry_warns():
    j = jd(payment_dates=["2026-03-01", "2026-05-01"])
    fs = [f for f in found(j) if f.code == "clearance_not_valid_at_payment"]
    assert len(fs) == 1 and "2026-05-01" in fs[0].detail


def test_past_payments_ignored_and_alberta_letter():
    j = jd(province="AB", payment_dates=["2026-01-01", "2026-03-01"])
    j["subs"][0]["clearance"] = {"issuer": "WCB-AB", "number": "9", "issued": "2026-02-01"}
    fs = [f for f in found(j) if f.code == "clearance_not_valid_at_payment"]
    assert len(fs) == 1 and "2026-03-01" in fs[0].detail and "does not state" in fs[0].detail


def test_cli_payment_on_flag(tmp_path, capsys):
    p = write(tmp_path, [jd()])
    assert main(["audit", p, "--on", "2026-02-15", "--payment-on", "2026-06-01"]) == 0
    assert "clearance_not_valid_at_payment" in capsys.readouterr().out
    assert main(["renewals", p, "--on", "2026-02-15", "--payment-on", "2026-06-01"]) == 0
    assert "clearance_not_valid_at_payment" in capsys.readouterr().out


def test_bad_payment_dates_rejected():
    with pytest.raises(DataError, match="payment_dates"):
        Job.from_dict(jd(payment_dates="2026-03-01"))
    with pytest.raises(DataError, match=r"payment_dates\[0\]"):
        Job.from_dict(jd(payment_dates=["soon"]))
    with pytest.raises(DataError):
        Job.from_dict(jd(payment_dates=["2026-03-01"] * 501))


# ---- CLI: robustness, DX ----------------------------------------------

def test_internal_error_is_exit_3_not_1(tmp_path, monkeypatch, capsys):
    import clearancewatch.cli as cli

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "audit", boom)
    p = write(tmp_path, [jd()])
    assert main(["audit", p]) == 3
    assert "bug, not a finding" in capsys.readouterr().err


def test_stdin_dash(tmp_path, monkeypatch, capsys):
    class FakeIn:
        buffer = io.BytesIO(json.dumps([jd()]).encode())

    monkeypatch.setattr(sys, "stdin", FakeIn())
    assert main(["audit", "-", "--on", "2026-02-15"]) == 0
    assert "PASS" in capsys.readouterr().out


def test_legacy_console_cannot_crash_output():
    code = ("import sys,json;sys.argv=['x'];from clearancewatch.cli import main;"
            "main(['audit','-','--on','2026-02-15'])")
    job = jd(name="Café 工事")
    job["subs"][0].pop("insurance")
    r = subprocess.run([sys.executable, "-c", code], input=json.dumps([job]).encode(),
                       env={"PYTHONIOENCODING": "ascii", "PYTHONPATH": str(ROOT / "src")}, capture_output=True)
    assert b"Traceback" not in r.stderr and b"insurance_missing" in r.stdout, r.stderr


def test_closed_pipe_does_not_traceback(tmp_path):
    p = write(tmp_path, [jd() for _ in range(1)])
    r = subprocess.run(f"{sys.executable} -m clearancewatch.cli audit {p} --on 2026-02-15 --json | true",
                       shell=True, capture_output=True, env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"})
    assert b"Traceback" not in r.stderr


def test_template_is_valid_and_clean(tmp_path, capsys):
    data = json.loads(TEMPLATE)
    assert main(["template"]) == 0
    assert json.loads(capsys.readouterr().out) == data
    p = write(tmp_path, data)
    assert main(["audit", p, "--on", "2026-02-15"]) == 0


def test_readme_example_matches_template_and_passes():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)```", readme, re.S)
    assert json.loads(blocks[0]) == json.loads(TEMPLATE)


def _keys(cls):
    return set(cls._KEYS)


def test_schema_field_names_match_model():
    s = jobs_schema()
    job = s["anyOf"][2]
    assert set(job["properties"]) == _keys(Job)
    sub = job["properties"]["subs"]["items"]
    assert set(sub["properties"]) == _keys(Subcontractor)
    assert set(sub["properties"]["insurance"]["properties"]) == _keys(Insurance)
    assert set(sub["properties"]["licences"]["items"]["properties"]) == _keys(Licence)
    assert set(job["properties"]["requirements"]["properties"]) == _keys(Requirements)
    from clearancewatch.model import Clearance
    assert set(sub["properties"]["clearance"]["properties"]) == _keys(Clearance)


def test_schema_validates_template_when_jsonschema_is_installed():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(json.loads(TEMPLATE), jobs_schema())


# ---- active-only, baseline ----------------------------------------------

def test_active_only_skips_finished_jobs(tmp_path, capsys):
    done = jd(name="Done", end="2026-01-31")
    done["subs"][0].pop("insurance")
    p = write(tmp_path, [done, jd(name="Live")])
    assert main(["audit", p, "--on", "2026-02-15"]) == 1
    capsys.readouterr()
    assert main(["audit", p, "--on", "2026-02-15", "--active-only"]) == 0
    assert "1 finished job(s) skipped" in capsys.readouterr().out


def test_baseline_shows_only_new_findings(tmp_path, capsys):
    bad = jd(name="Old")
    bad["subs"][0].pop("insurance")
    p = write(tmp_path, [bad])
    assert main(["audit", p, "--on", "2026-02-15", "--json"]) == 1
    prev = tmp_path / "prev.json"
    prev.write_text(capsys.readouterr().out, encoding="utf-8")
    assert main(["audit", p, "--on", "2026-02-15", "--baseline", str(prev)]) == 0
    out = capsys.readouterr().out
    assert "1 already in baseline hidden" in out and "insurance_missing" not in out
    worse = jd(name="Old")
    worse["subs"][0].pop("insurance")
    worse["subs"].append({"name": "New sub"})
    p2 = write(tmp_path, [worse], "jobs2.json")
    assert main(["audit", p2, "--on", "2026-02-15", "--baseline", str(prev)]) == 1
    out = capsys.readouterr().out
    assert "New sub" in out and "S:" not in out.replace("New sub", "")


def test_bad_baseline_exits_2(tmp_path):
    p = write(tmp_path, [jd()])
    for payload in ('{"x": 1}', "nope", '{"findings": [{"code": 1}]}', "[]"):
        b = write(tmp_path, payload, "b.json")
        assert main(["audit", p, "--baseline", b]) == 2
    assert main(["audit", p, "--baseline", str(tmp_path / "missing.json")]) == 2


# ---- hostile input -----------------------------------------------------

def test_markdown_links_in_names_are_neutralised(tmp_path, capsys):
    j = jd(name="[Click here](http://evil.example)")
    j["subs"][0].pop("insurance")
    p = write(tmp_path, [j])
    main(["audit", p, "--on", "2026-02-15", "--format", "md"])
    out = capsys.readouterr().out
    assert "[Click" not in out.replace("\\[", "")


def test_many_subs_sharing_one_clearance_number_is_fast_and_capped():
    subs = [{"name": f"S{i}", "clearance": {"issuer": "WSIB", "number": "7", "issued": "2026-01-10",
                                           "expires": "2026-04-10"}} for i in range(20000)]
    j = Job.from_dict(jd(subs=subs))
    t = time.perf_counter()
    fs = audit(j, on=D("2026-02-15"))
    assert time.perf_counter() - t < 20
    shared = [f for f in fs if f.code == "clearance_number_shared"]
    assert len(shared) == 1 and "19995 more" in shared[0].detail and len(shared[0].detail) < 400


def test_input_objects_are_not_mutated():
    j = jd(requirements={"min_liability": "C$2M"}, payment_dates=["2026-03-01"])
    before = copy.deepcopy(j)
    found(j)
    assert j == before


# ---- pass B: things found attacking the pass-A code ---------------------

def test_label_after_aggregate_belongs_to_the_next_amount():
    assert parse_limits("$1M aggregate, per occurrence $500k")[0] == [(1_000_000, False), (500_000, True)]
    assert parse_limit("$1M aggregate, per occurrence $500k") == (500_000, "")


def test_ninety_day_default_not_used_for_payment_or_gap_checks_on_other_boards():
    j = jd(province="BC", payment_dates=["2026-03-01"])
    j["subs"][0]["clearance"] = {"issuer": "WorkSafeBC", "number": "1", "issued": "2026-02-01"}
    c = codes(j)
    assert "clearance_no_expiry" in c and "clearance_not_valid_at_payment" in c


def test_findings_carry_the_due_date():
    fs = found(jd(end="2026-12-31"), on="2026-04-01")
    due = {f.code: f.due for f in fs if f.due}
    assert due["renewal_due"] == D("2026-04-10")
    assert fs[0].as_dict().get("due") or all("due" not in f.as_dict() for f in fs if f.due is None)


def _unfold(text):
    return text.replace("\r\n ", "")


def test_ics_is_well_formed_and_injection_proof(tmp_path, capsysbinary):
    j = jd(name="Job, one; two\r\nBEGIN:VEVENT", end="2026-05-30")
    j["subs"][0]["name"] = "Séb " + "é" * 60
    j["subs"][0]["clearance"].update(issued="2026-02-01", expires="2026-04-20")
    p = write(tmp_path, [j])
    assert main(["audit", p, "--on", "2026-04-01", "--format", "ics", "--fail-on", "never"]) == 0
    raw = capsysbinary.readouterr().out
    assert raw.endswith(b"END:VCALENDAR\r\n") and b"\n" not in raw.replace(b"\r\n", b"")
    for line in raw.split(b"\r\n")[:-1]:
        assert len(line) <= 75
    text = _unfold(raw.decode("utf-8"))
    lines = text.split("\r\n")
    assert lines.count("BEGIN:VEVENT") == 1 == lines.count("END:VEVENT")  # the injected BEGIN:VEVENT is inert
    assert "DTSTART;VALUE=DATE:20260420" in lines
    assert any(x.startswith("UID:") and x.endswith("@clearancewatch.invalid") for x in lines)
    assert "Job\\, one\\; two" in text


def test_ics_has_only_dated_findings():
    from clearancewatch.cli import render_ics
    j = jd()
    j["subs"][0].pop("insurance")  # an undated error
    out = render_ics(found(j), D("2026-02-15"))
    assert "VEVENT" not in out and out.startswith("BEGIN:VCALENDAR") and out.endswith("END:VCALENDAR")


def test_ics_uid_is_stable():
    from clearancewatch.cli import render_ics
    j = jd(end="2026-12-31")
    a = render_ics(found(j, on="2026-04-01"), D("2026-04-01"))
    assert a == render_ics(found(j, on="2026-04-01"), D("2026-04-01"))


def test_every_finding_code_has_an_action():
    """The chase list must never show a blank 'what to do'."""
    from clearancewatch.cli import ACTIONS
    src = (ROOT / "src" / "clearancewatch" / "audit.py").read_text(encoding="utf-8")
    emitted = set(re.findall(r'x\.add\(\s*"(?:error|warn|info)",\s*"(\w+)"', src))
    emitted |= set(re.findall(r'Finding\("(?:error|warn)",\s*"(\w+)"', src))
    emitted |= {"unknown_field", "job_dates_invalid", "duplicate_sub", "clearance_number_shared"}
    assert emitted and not (emitted - set(ACTIONS)), emitted - set(ACTIONS)


def test_readme_lists_every_finding_code():
    src = (ROOT / "src" / "clearancewatch" / "audit.py").read_text(encoding="utf-8")
    emitted = set(re.findall(r'x\.add\(\s*"(?:error|warn|info)",\s*"(\w+)"', src))
    emitted |= set(re.findall(r'Finding\("(?:error|warn)",\s*"(\w+)"', src))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    missing = {c for c in emitted if c not in readme}
    assert not missing, missing


def test_readme_sample_output_is_what_the_tool_prints(tmp_path, capsys):
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    sample = re.search(r"Example output.*?```\n(.*?)```", readme, re.S).group(1).strip().splitlines()
    data = json.loads(TEMPLATE)
    data[0]["subs"][0]["clearance"]["expires"] = "2026-03-15"
    data[0]["subs"][0]["insurance"]["expires"] = "2026-03-05"
    assert main(["audit", write(tmp_path, data), "--on", "2026-02-15"]) == 1
    actual = capsys.readouterr().out.strip().splitlines()
    assert sample == actual


def test_audit_is_thread_safe_and_deterministic():
    from concurrent.futures import ThreadPoolExecutor
    jobs = [Job.from_dict(jd(name=f"J{i}", requirements={"min_liability": "C$2M"})) for i in range(200)]

    def run(j):
        return [f.as_dict() for f in audit(j, on=D("2026-02-15"))]

    seq = [run(j) for j in jobs]
    with ThreadPoolExecutor(8) as ex:
        assert list(ex.map(run, jobs)) == seq
