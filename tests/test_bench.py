"""Guard: every planted defect in the benchmark corpus stays detected, with no false alarms."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bench"))

from corpus import build  # noqa: E402
from run import evaluate  # noqa: E402


def test_benchmark_corpus_fully_caught_no_false_alarms():
    rows, fp, clean_n, _per = evaluate(build())
    assert rows["cw"][0] == rows["cw"][1] == 84
    assert fp["cw"] == 0 and clean_n == 30
    assert rows["base"][0] < rows["cw"][0]  # the plain date-column baseline really is weaker
