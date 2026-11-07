# Round 4: the stranger's first hour

**Honest note on method.** This round was done by one agent working through the specialist roles one after another. No independent sub-agents could be spawned in this environment, so the "specialists" are checklists I ran for real, not separate people. Every finding below names the command that showed it. Not run on Windows or macOS; Linux only.

## Specialist findings

| Specialist | Finding | Proof (command) | Status |
|---|---|---|---|
| First-time user (README only, clean venv) | `pytest` from a fresh clone fails: `No module named 'clearancewatch'` | `pytest -q` before `pip install` | fixed (`pythonpath` in pyproject) |
| First-time user | The README quick start works from the built wheel (`template -o`, `audit --on 2026-02-15`, md/ics/github/json) | ran each in a venv under a folder with a space in its name | OK |
| First-time user | `pip install clearancewatch` today gives 0.1.0, which has no `template`, `--format`, `--fail-on` | `pip index versions clearancewatch`; PyPI JSON shows only 0.1.0 | README says so; release needed |
| Release engineer | sdist lacked `bench/`, so tests fail when unpacked | untar sdist, `python -m pytest` -> `No module named 'corpus'` | fixed (`MANIFEST.in`), re-checked on new sdist |
| Release engineer | `setuptools>=68` too old for `license = "MIT"` (SPDX) | reading setuptools docs; version bumped to >=77 | fixed (not run against 68; unverified) |
| Release engineer | author was a GitHub handle, no URLs, no py.typed, thin classifiers | `unzip -l`, METADATA | fixed |
| Supply-chain reviewer | No runtime dependencies (stdlib only); wheel has 7 modules, LICENSE, no tests/secrets/personal paths | `unzip -l` on wheel; `pip list` in clean venv | OK |
| Supply-chain reviewer | Publishing by a long-lived token is the weak spot | n/a | advice in PUBLISH-CHECKLIST (token scoped to the project, or Trusted Publishing); CI actions are tag-pinned, not SHA-pinned (not changed) |
| CI/CD integrator | No annotation format for GitHub Actions; CI never ran lint/mypy/Windows | read ci.yml | `--format github` added; CI matrix + ruff + mypy + sdist test added (never run on GitHub) |
| Hostile-input fuzzer | 6,000 random mutations of the template: 0 crashes (1,149 loaded, 4,851 clean DataError); NaN/Infinity accepted; U+2028 unescaped | `/tmp` fuzz script (not committed) | NaN/Infinity -> exit 2; U+2028/2029 escaped |
| Hostile-input fuzzer | empty, NUL, 100k-deep JSON, latin-1, CRLF, string/number top level, folder as file, read-only folder, `\| head`, ASCII console | ran each | all clean exits (2 or 0/1), no traceback |
| Windows reviewer (static) | PowerShell 5 `>` writes UTF-16 -> "not UTF-8" | reasoning from known PowerShell behaviour, then unit test | fixed (UTF-16 BOM read, `-o`) |
| Windows reviewer (static) | pipe-closed errors differ on Windows; `os.replace` onto an open file fails; text-mode `print` adds CR | read code | EPIPE/EINVAL handled; `-o` writes bytes and reports a plain exit 2 on failure; ics already written as bytes |
| Docs/DX writer | `--within abc` error leaked `_non_negative`; package docstring contradicted README on "whole job" | ran it; read `__init__.py` | fixed |
| Performance engineer | 3,000-sub file audits in about a second; no change after round 4 | `bench/run.py` x3 before/after | 17-23k subs/s after vs 20-28k before; same VM noise, no real change |
| Competitor maintainer | TrustLayer: "Pricing varies depending on platform usage"; myCOI's illumend.ai still advertises endorsement checks; OpenCOI page returned 403 this time | curl, read-only | README updated; OpenCOI marked not re-checked |

## 20+ ideas, scored (1 low - 5 high; effort/risk: 1 low - 5 high)

| # | Idea | User value | Differentiation | Effort | Risk | Status |
|---|---|---|---|---|---|---|
| 1 | Run tests from a fresh clone (pytest pythonpath) | 4 | 1 | 1 | 1 | DONE |
| 2 | sdist contains bench/tests/changelog | 4 | 1 | 1 | 1 | DONE |
| 3 | Correct build requirement + metadata (author, URLs, classifiers) | 4 | 1 | 1 | 1 | DONE |
| 4 | py.typed + clean mypy | 3 | 2 | 1 | 1 | DONE |
| 5 | Read UTF-16 files (PowerShell redirect) | 4 | 2 | 1 | 1 | DONE |
| 6 | `-o FILE` output, UTF-8, atomic replace | 4 | 2 | 2 | 2 | DONE |
| 7 | `--format github` annotations | 4 | 3 | 2 | 2 | DONE |
| 8 | JSON report carries schema + version | 3 | 2 | 1 | 1 | DONE |
| 9 | Reject NaN/Infinity | 2 | 1 | 1 | 1 | DONE |
| 10 | Escape U+2028/2029 | 2 | 2 | 1 | 1 | DONE |
| 11 | Plain error for bad `--within` | 2 | 1 | 1 | 1 | DONE |
| 12 | Note when a job has no subs | 3 | 2 | 1 | 2 | DONE |
| 13 | Warn on duplicate job names (baseline ambiguity) | 3 | 3 | 1 | 1 | DONE |
| 14 | Version consistency + metadata tests | 3 | 1 | 1 | 1 | DONE |
| 15 | Every finding code has a chase-list action (test) | 3 | 2 | 1 | 1 | DONE |
| 16 | CI on Windows/macOS, lint, mypy, sdist test | 4 | 1 | 2 | 2 | DONE (not yet run on GitHub) |
| 17 | Publish checklist in plain words | 5 | 1 | 1 | 1 | DONE |
| 18 | Read certificates from PDF/OCR | 5 | 5 | 5 | 4 | NOT-DONE (needs dependencies and test PDFs; stays out of scope) |
| 19 | Live WSIB/WCB clearance lookup | 5 | 5 | 5 | 5 | NOT-DONE (live service, terms of use unverified) |
| 20 | More provinces (BC, SK, MB, QC) | 4 | 4 | 4 | 4 | NOT-DONE (rules not verified; the tool says "not modelled" instead) |
| 21 | CSV/spreadsheet import of subs | 4 | 3 | 3 | 2 | NOT-DONE |
| 22 | Use the sub's own `province` field | 2 | 2 | 3 | 3 | NOT-DONE |
| 23 | Trusted-Publishing release workflow | 3 | 1 | 2 | 3 | NOT-DONE (needs Dan's PyPI setup; advised in checklist) |
| 24 | Pin GitHub Actions to commit SHAs | 2 | 1 | 1 | 2 | NOT-DONE (SHAs not verified offline) |
| 25 | SARIF / JUnit output | 2 | 2 | 3 | 2 | NOT-DONE (`github` covers the main case) |

## What I could not test
- Windows and macOS (static reading only). The UTF-16 and `-o` fixes are unit-tested on Linux with synthetic bytes, not with real PowerShell.
- `setuptools` older than 77 (the new requirement is from its documentation, not a failed build).
- Python 3.9-3.13 were run on Linux; no PyPy.
- The GitHub Actions file (never executed).
- Competitor products: only home pages read; OpenCOI blocked this time.
- Concurrency: the tool is single-process and keeps no state or lock files; nothing was run in parallel beyond several invocations at once.
