"""Golden files: every output format for one fixed jobs file, compared byte for byte.

A change in wording or layout shows up here as a diff. To accept an intended change:
``UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py`` and read the diff in git before committing.
"""
import json
import os

import pytest

import clearancewatch
from clearancewatch.cli import ACTIONS, main

HERE = os.path.dirname(__file__)
GOLD = os.path.join(HERE, "golden")
JOBS = os.path.join(GOLD, "jobs_defects.json")
CASES = [
    ("audit", ["audit", JOBS, "--on", "2026-02-15"], "audit.txt"),
    ("audit-md", ["audit", JOBS, "--on", "2026-02-15", "--format", "md"], "audit.md"),
    ("audit-csv", ["audit", JOBS, "--on", "2026-02-15", "--format", "csv"], "audit.csv"),
    ("audit-json", ["audit", JOBS, "--on", "2026-02-15", "--format", "json"], "audit.json"),
    ("audit-github", ["audit", JOBS, "--on", "2026-02-15", "--format", "github"], "audit.github.txt"),
    ("audit-ics", ["audit", JOBS, "--on", "2026-02-15", "--format", "ics"], "audit.ics"),
    ("renewals", ["renewals", JOBS, "--on", "2026-02-15", "--within", "45"], "renewals.txt"),
    ("payment", ["audit", JOBS, "--on", "2026-02-15", "--payment-on", "2026-04-15"], "audit-payment.txt"),
]


def _run(argv, tmp_path):
    out = tmp_path / "out.bin"
    main(argv + ["--fail-on", "never", "-o", str(out)])
    text = out.read_bytes().decode("utf-8")
    return text.replace(f'"version": "{clearancewatch.__version__}"', '"version": "VERSION"')


@pytest.mark.parametrize("name,argv,fname", CASES, ids=[c[0] for c in CASES])
def test_output_matches_golden_file(name, argv, fname, tmp_path):
    got = _run(argv, tmp_path)
    path = os.path.join(GOLD, fname)
    if os.environ.get("UPDATE_GOLDEN"):
        with open(path, "wb") as fh:
            fh.write(got.encode("utf-8"))
    with open(path, "rb") as fh:
        want = fh.read().decode("utf-8")
    assert got == want, f"{fname} differs; if the change is intended run with UPDATE_GOLDEN=1"


def test_golden_outputs_contain_no_raw_control_characters(tmp_path):
    for name, argv, fname in CASES:
        got = _run(argv, tmp_path)
        bad = [c for c in got if ord(c) < 32 and c not in "\n\r"]
        assert not bad, (fname, bad)


def test_golden_file_exercises_many_known_codes():
    with open(os.path.join(GOLD, "audit.json"), encoding="utf-8") as fh:
        doc = json.load(fh)
    codes = {f["code"] for f in doc["findings"]}
    assert codes <= set(ACTIONS) and len(codes) >= 15
