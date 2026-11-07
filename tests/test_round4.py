"""Round 4: what a stranger hits on day one (install, Windows-style input, CI output, metadata)."""
import json
import os
import re
import sys

import pytest

import clearancewatch
from clearancewatch.cli import ACTIONS, main

ROOT = os.path.join(os.path.dirname(__file__), "..")
GOOD = [{
    "name": "Kitchen reno", "province": "ON", "start": "2026-02-01", "end": "2026-03-30",
    "subs": [{"name": "Bob's Drywall",
              "clearance": {"issuer": "WSIB", "number": "1", "issued": "2026-01-10", "expires": "2026-04-10"},
              "insurance": {"provider": "A", "policy": "P", "expires": "2026-12-31"}}],
}]


def put(tmp, data, name="jobs.json", encoding="utf-8"):
    p = tmp / name
    text = data if isinstance(data, str) else json.dumps(data)
    p.write_bytes(text.encode(encoding))
    return str(p)


def test_utf16_file_from_powershell_redirect_loads(tmp_path, capsys):
    p = put(tmp_path, GOOD, encoding="utf-16")  # Python writes a BOM for "utf-16"
    assert main(["audit", p, "--on", "2026-02-15"]) == 0
    assert "PASS" in capsys.readouterr().out


def test_utf16_stdin(monkeypatch, capsys):
    import io
    raw = json.dumps(GOOD).encode("utf-16")

    class Stdin:
        buffer = io.BytesIO(raw)
    monkeypatch.setattr(sys, "stdin", Stdin())
    assert main(["audit", "-", "--on", "2026-02-15"]) == 0


@pytest.mark.parametrize("const", ["NaN", "Infinity", "-Infinity"])
def test_nan_and_infinity_are_rejected(tmp_path, capsys, const):
    p = put(tmp_path, '[{"name": %s, "subs": []}]' % const)
    with pytest.raises(SystemExit) as e:
        main(["audit", p])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "not valid JSON" in err and "Traceback" not in err


def test_bad_within_message_is_plain(tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        main(["audit", put(tmp_path, GOOD), "--within", "abc"])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "_non_negative" not in err and "whole number" in err


def test_json_report_names_its_schema_and_version(tmp_path, capsys):
    main(["audit", put(tmp_path, GOOD), "--on", "2026-02-15", "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == 1 and doc["version"] == clearancewatch.__version__
    assert {"errors", "warnings", "info", "jobs", "findings"} <= set(doc)


def test_job_without_subs_is_a_note_not_a_failure(tmp_path, capsys):
    p = put(tmp_path, [{"name": "Empty", "subs": []}])
    assert main(["audit", p, "--on", "2026-02-15", "--fail-on", "warn"]) == 0
    assert "job_has_no_subs" in capsys.readouterr().out


def test_two_jobs_with_one_name_warn(tmp_path, capsys):
    p = put(tmp_path, GOOD + GOOD)
    assert main(["audit", p, "--on", "2026-02-15", "--json"]) == 0
    codes = [f["code"] for f in json.loads(capsys.readouterr().out)["findings"]]
    assert "duplicate_job" in codes


def test_github_format_levels_and_escaping(tmp_path, capsys):
    jobs = [{"name": "100%: a,b", "province": "ON", "start": "2026-02-01", "end": "2026-03-30",
             "subs": [{"name": "Evil name::error title=x"}]}]
    rc = main(["audit", put(tmp_path, jobs), "--on", "2026-02-15", "--format", "github"])
    out = capsys.readouterr().out
    assert rc == 1
    lines = out.splitlines()
    assert lines and all(re.match(r"^::(error|warning|notice) title=[A-Za-z_]+::", ln) for ln in lines)
    assert any(ln.startswith("::error title=clearance_missing::") for ln in lines)
    assert "100%25" in out and " " not in out


def test_github_format_clean_run_prints_nothing(tmp_path, capsys):
    assert main(["audit", put(tmp_path, GOOD), "--on", "2026-02-15", "--format", "github"]) == 0
    assert capsys.readouterr().out == ""


def test_output_file_is_utf8_and_exit_code_unchanged(tmp_path, capsys):
    jobs = [{"name": "Café", "subs": [{"name": "Zoë"}]}]
    out = tmp_path / "report.md"
    rc = main(["audit", put(tmp_path, jobs), "--on", "2026-02-15", "--format", "md", "-o", str(out)])
    assert rc == 1
    assert capsys.readouterr().out == ""
    assert "Zoë" in out.read_text(encoding="utf-8")
    assert not [f for f in os.listdir(tmp_path) if "cwtmp" in f]


def test_output_ics_keeps_crlf(tmp_path):
    jobs = [{"name": "J", "end": "2026-12-31", "subs": [{"name": "S",
             "clearance": {"issuer": "WSIB", "issued": "2026-02-01", "expires": "2026-02-20"}}]}]
    out = tmp_path / "r.ics"
    main(["audit", put(tmp_path, jobs), "--on", "2026-02-15", "--format", "ics", "-o", str(out)])
    raw = out.read_bytes()
    assert b"\r\n" in raw and b"\r\r\n" not in raw and raw.count(b"\n") == raw.count(b"\r\n")


def test_output_to_missing_folder_is_a_plain_exit_2(tmp_path, capsys):
    rc = None
    with pytest.raises(SystemExit) as e:
        main(["audit", put(tmp_path, GOOD), "--on", "2026-02-15", "-o", str(tmp_path / "nope" / "r.txt")])
    rc = e.value.code
    assert rc == 2
    err = capsys.readouterr().err
    assert "cannot write" in err and "Traceback" not in err


def test_path_with_spaces_and_non_ascii(tmp_path, capsys):
    d = tmp_path / "my jobs é"
    d.mkdir()
    assert main(["audit", put(d, GOOD, "jobs file.json"), "--on", "2026-02-15"]) == 0


def test_every_code_the_auditor_can_emit_has_an_action():
    src = open(os.path.join(ROOT, "src", "clearancewatch", "audit.py"), encoding="utf-8").read()
    codes = set(re.findall(r'"(?:error|warn|info)",\s*"([a-z0-9_]+)"', src))
    codes |= set(re.findall(r'\badd\(\s*(?:sev\w*|"(?:error|warn|info)")\s*,\s*"([a-z0-9_]+)"', src))
    assert len(codes) > 25
    assert not (codes - set(ACTIONS)), codes - set(ACTIONS)


def test_version_is_the_same_everywhere():
    py = open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8").read()
    assert re.search(r'^version = "%s"$' % re.escape(clearancewatch.__version__), py, re.M)
    log = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    assert re.search(r"^## %s\b" % re.escape(clearancewatch.__version__), log, re.M)


def test_metadata_and_package_files():
    py = open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8").read()
    assert 'name = "Calas Automations Inc."' in py
    assert "https://github.com/calasdan-sketch/clearancewatch" in py
    assert 'license = "MIT"' in py and "setuptools>=77" in py
    assert os.path.exists(os.path.join(ROOT, "src", "clearancewatch", "py.typed"))
    manifest = open(os.path.join(ROOT, "MANIFEST.in"), encoding="utf-8").read()
    assert "graft bench" in manifest and "CHANGELOG.md" in manifest
    assert "MIT" in open(os.path.join(ROOT, "LICENSE"), encoding="utf-8").read()


def test_template_and_schema_can_be_written_with_dash_o(tmp_path, capsys):
    t, sc = tmp_path / "jobs.json", tmp_path / "s.json"
    assert main(["template", "-o", str(t)]) == 0 and main(["schema", "-o", str(sc)]) == 0
    assert capsys.readouterr().out == ""
    assert main(["audit", str(t), "--on", "2026-02-15"]) == 0
    assert json.loads(sc.read_text(encoding="utf-8"))["title"]
