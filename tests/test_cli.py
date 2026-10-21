"""CLI tests."""
import json

from clearancewatch.cli import main


def write_jobs(tmp, jobs):
    p = tmp / "jobs.json"
    p.write_text(json.dumps(jobs), encoding="utf-8")
    return str(p)


GOOD = {
    "name": "Kitchen reno",
    "province": "ON",
    "start": "2026-02-01",
    "end": "2026-03-30",
    "subs": [{
        "name": "Bob's Drywall",
        "clearance": {"issuer": "WSIB", "number": "123", "issued": "2026-01-10", "expires": "2026-04-10"},
        "insurance": {"provider": "Aviva", "policy": "P-1", "expires": "2026-12-31"},
    }],
}


def test_audit_clean(tmp_path, capsys):
    assert main(["audit", write_jobs(tmp_path, [GOOD]), "--on", "2026-02-15"]) == 0
    assert "PASS" in capsys.readouterr().out


def test_audit_errors_fail_with_json(tmp_path, capsys):
    bad = dict(GOOD, subs=[{"name": "NoDocs"}])
    code = main(["audit", write_jobs(tmp_path, [bad]), "--on", "2026-02-15", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and out["errors"] >= 2
    assert any(f["code"] == "clearance_missing" for f in out["findings"])


def test_jobs_wrapper_dict(tmp_path, capsys):
    p = tmp_path / "jobs.json"
    p.write_text(json.dumps({"jobs": [GOOD]}), encoding="utf-8")
    assert main(["audit", str(p), "--on", "2026-02-15"]) == 0


def test_renewals_only_due(tmp_path, capsys):
    due = dict(GOOD, end="2026-02-28",  # job ends before the expiry -> renewal_due, not during-job
               subs=[dict(GOOD["subs"][0],
                          clearance={"issuer": "WSIB", "issued": "2026-01-20", "expires": "2026-03-10"})])
    assert main(["renewals", write_jobs(tmp_path, [due, GOOD]), "--within", "30", "--on", "2026-02-15"]) == 0
    out = capsys.readouterr().out
    assert "renewal_due" in out and out.count("WARN") == 1


def test_missing_file(tmp_path):
    try:
        main(["audit", str(tmp_path / "nope.json")])
        raised = False
    except SystemExit as e:
        raised = True
    assert raised
