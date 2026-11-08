# Round 5: the people who actually use it (GC risk manager, broker, clerk, Manitoba WCB, QA)

**Honest note on method.** One agent played the specialists one after another. No independent sub-agents could be spawned here, so each "specialist" is a checklist I ran for real, and every finding names the command that showed it. Linux only (Python 3.11, 3.12, 3.13 run; 3.9 checked by syntax only). Windows and macOS have never been run.

## Author line (done first)

Owner/author/maintainer is exactly `Calas Automations Inc.`. Old label found by re-grepping the whole tree: `LICENSE` said `Copyright (c) 2026 calasdan-sketch`. Fixed. `pyproject.toml` already had `authors`; added `maintainers`; added `__author__` / `__copyright__`; `.ics` PRODID is now `-//Calas Automations Inc.//clearancewatch//EN`; new `clearancewatch about` prints the name; README license section updated. There is no package.json, SARIF or JUnit output, so nothing to change there. GitHub URLs left alone (see "could not test" about whether the repo is public).

Proof, on a freshly built wheel (not editable):
`python -m build` then `unzip -p dist/clearancewatch-0.2.0-py3-none-any.whl clearancewatch-0.2.0.dist-info/METADATA` shows `Author: Calas Automations Inc.` and `Maintainer: Calas Automations Inc.`; `.../licenses/LICENSE` line 3 is `Copyright (c) 2026 Calas Automations Inc.`; `twine check dist/*` passes. `tests/test_round5.py::test_author_string_is_pinned_everywhere` pins all of it.

## Baseline before any change
`python -m pytest -q`: 166 passed. `python bench/run.py`: 84/84 planted defects, 0/30 false alarms (date-column stand-in 20/84). Speed varied with VM load (28,000 sub audits/s that first run).

## Specialist findings

| Specialist | Finding | Proof (command) | Status |
|---|---|---|---|
| Manitoba WCB specialist | The tool did not know Manitoba at all (`province: "MB"` gave `province_not_modelled`; a `WCB Manitoba` letter was misread as a 90-day certificate or "no rule modelled"). Dan's own province. | `curl` of wcb.mb.ca/clearances (2026-11-08) and the Act PDF (C.C.S.M. c. W200, current to 4 Nov 2026) | fixed: MB letters, `status`, `supply_only`, sources in README table |
| Manitoba WCB specialist | Primary sources say: get the clearance before work commences and before any payment; "deemed worker" and "deemed/default" statuses; supply-only firms need no clearance; Act s. 11, 89(3), 90 make principal and contractor liable for assessments. They do **not** say how long a letter stays valid. | `pdftotext -layout w200.pdf`, read ss. 11, 89(3), 90(1)-(2); page text of /clearances | README marks letter validity **unverified**; payment check says "request a fresh one" |
| GC / construction risk manager | Alberta says "before hiring" and Manitoba "before work commences", but there was no way to record when a sub's own work starts, so a letter obtained after the crew arrived passed silently. | `audit` on a job with a letter dated after the start: no finding | fixed: `sub.start`, `clearance_after_work_started` (AB and MB only) |
| GC / construction risk manager | Bare `WCB` or blank issuer on an Alberta/Manitoba job (the most common way a clerk types it) gave `clearance_no_expiry` and an unusable message. | `clearancewatch audit` on `{"issuer":"WCB","issued":...}` with `province: AB` | fixed: read as that province's letter when no expiry is given |
| Insurance broker | `"$5,000 deductible, C$2M"` was read as a C$5,000 limit and gave a false `insurance_below_minimum` error. | `parse_limits("$5,000 deductible; $2M")` returned `[]`/wrong before the fix | fixed: amounts next to deductible/retention/SIR are skipped |
| Insurance broker | Broker shorthand `1/2M` (1M per occurrence / 2M aggregate) was read as C$1 and as a C$1 limit. | `parse_limits("1/2M")` returned `[(1, False), (2000000, False)]` | fixed: a small bare number makes the text unreadable (a warning), never a guess |
| Insurance broker | `"C$1M + C$1M umbrella"` against a C$2M minimum was a hard error although many contracts let umbrella count. | audit on that text | new warn `insurance_limit_includes_umbrella`; layers are never added up |
| Compliance clerk | Subs live in Excel; there was no way in except hand-writing JSON. | n/a | new `import-csv` (UTF-8 / Excel UTF-16, strict, row numbers) |
| Compliance clerk | While importing a row that had a limit and an expiry but no policy number, the sub was reported `insurance_missing` ("no insurance on file"). Same for JSON. | `import-csv` then `audit` on a row without provider/policy | fixed: missing only when the entry has nothing at all |
| Compliance clerk | `--baseline` keys on exact text, so anything whose text depends on file order makes old findings reappear as "new". Property test found two: `clearance_number_shared` lists subs in file order; `duplicate_sub` names the first spelling in file order. | hypothesis counterexamples (seed 347 / 5214) | fixed: sorted names, canonical spelling |
| Upgrade-path tester | 0.1.0 jobs files still load (3 random files x 40 jobs through the real 0.1.0 wheel and this tree: no file rejected; every difference is a documented change: new info/warn codes, `clearance_expires_during_job` error to warn on long jobs, bare `WCB` no longer gets 90 days). | `pip download clearancewatch==0.1.0 --no-deps`, two venvs, same files, same `--on`, diff of (severity, code, subject) | documented in README "Coming from 0.1.0" |
| Upgrade-path tester | A 0.1.0 `--json` report (no `job`/`sub` keys) was refused as a `--baseline`. | `clearancewatch audit ... --baseline old.json` exit 2 | fixed |
| Upgrade-path tester | 0.1.0 accepted `"start": "20260101"` on Python 3.11+ (it calls `date.fromisoformat`); 0.2.0 refuses it with a clear exit-2 message. | ran both | kept strict (deliberate since Round 3), documented |
| QA / test methodology (mutation) | `bench/mutate.py` flips one comparison / and-or / not at a time in `audit.py` and `money.py` (188 mutants) and runs the tests. Existing suite killed 120 (63%). Survivors were almost all "exactly on the day" boundaries (`<` vs `<=` on expiry, horizon, cover date, payment date). | `python bench/mutate.py` | fixed with `tests/test_boundaries.py` (every expiry kind x job end x days-to-expiry against an independent oracle); second pass 186/188; the two survivors got tests (WSIB certificate on an AB job stays a certificate; five-name cap); final pass below |
| QA / test methodology (property-based) | Properties: audit is deterministic; sub order never changes what is found; renewals is a subset of audit; every code has an action; no report format emits control or bidi characters; limit parser total; clean functions total. 300 seeded jobs (always) + hypothesis (if installed) + a one-off 20,000-job run: 0 failures after the two fixes above. | `pytest tests/test_properties.py` | DONE |
| QA / test methodology (golden files) | One fixed defects file through all 8 outputs (text, md, csv, json, github, ics, renewals, payment) byte for byte; includes an ESC sequence and a quote/comma name to prove escaping. `UPDATE_GOLDEN=1` regenerates after an intended change. | `pytest tests/test_golden.py` | DONE |
| QA / differential | The previous version (0.1.0 wheel) acted as the reference implementation for 120 jobs (above); there is no outside reference for WSIB/WCB rules. | see upgrade row | done as far as possible |
| Debug pass | Hostile / huge / odd input to the new `import-csv`: NUL byte, 200 kB single field (clean exit 2, "field larger than field limit"), invalid bytes (exit 2), 60,000 rows (4 s, 12,000 jobs), `LC_ALL=C`, folder as file, missing file, stdin. No traceback in any. | commands run in a folder with a space in its name | OK |
| Debug pass | No network use (stdlib only, no socket/urllib import; ran under `unshare -rn` with no network). 12 simultaneous `-o same.md` runs: no leftover temp files, identical output. `\| head -1`: exit 0. | commands run | OK |
| Debug pass | `ruff check .` clean; `mypy` clean (8 source files); syntax checked for Python 3.9 with `ast.parse(feature_version=(3, 9))`; full suite on 3.11, 3.12, 3.13. | commands run | OK |
| Competitor maintainer | TrustLayer (read 2026-11-08): "Pricing varies depending on platform usage" unchanged; markets COI tracking including a "Workers Comp" page (an insurance-policy product, not clearance letters). illumend.ai (myCOI) still advertises reading endorsements (additional insured, waiver of subrogation, primary and non-contributory). Neither home page mentions WCB Manitoba clearances (home pages only; not exhaustive). | `curl` read-only | README comparison unchanged in substance |

## Pass B: attacking my own result
- Re-read the full diff of `audit.py` adversarially. Found and fixed: the negative-status regex flagged `In good standing (no issues)` as an error (any "no"); now only `not/no/without/lost good ...` counts, everything else odd is a warning (`clearance_status_unrecognised`).
- Built the wheel and sdist fresh (`python -m build` in a scratch copy of `git archive HEAD`), installed the wheel (non-editable) into a clean venv in a folder with a space in its name, and ran every command in the README quick start: `template -o`, `audit --on`, `--format md|csv|json|github|ics`, `-o`, `--baseline`, `--payment-on`, `import-csv` (file and stdin), `schema`, `about`, `--version`. All as documented. Unpacked the sdist and ran its tests: all pass (`tests/golden` ships in it).
- The benchmark's first Manitoba clean jobs produced 2 false alarms; the fault was in the corpus (extra subs on ongoing jobs kept Ontario certificates), not the tool. Fixed in `bench/corpus.py`.

## Numbers
| | before (82d2da0) | after |
|---|---|---|
| tests | 166 | 386 (385 on Python 3.11/3.12 where one optional test skips) |
| planted defects caught | 84/84 (21 kinds) | 100/100 (25 kinds) |
| false alarms | 0/30 | 0/36 |
| date-column stand-in | 20/84 | 20/100 |
| speed, same VM, same minute | about 117,000 sub audits/s | about 107,000 (new checks cost ~8%) |
| mutation score (`bench/mutate.py`) | 63% (120/188) | FINAL_MUT |

## 25 ideas, scored (1 low - 5 high; effort and risk: 1 low - 5 high)

| # | Idea | User value | Differentiation | Effort | Risk | Status |
|---|---|---|---|---|---|---|
| 1 | Manitoba WCB letters, status words, sources | 5 | 4 | 3 | 3 | DONE |
| 2 | `sub.start` and "clearance before work starts" (AB, MB) | 4 | 4 | 2 | 2 | DONE |
| 3 | `supply_only` note | 3 | 3 | 1 | 2 | DONE |
| 4 | Deductible / retention never read as a limit | 4 | 3 | 2 | 2 | DONE |
| 5 | Broker shorthand `1/2M` flagged, not guessed | 3 | 3 | 1 | 1 | DONE |
| 6 | Umbrella / excess warning instead of a hard error | 4 | 3 | 2 | 3 | DONE |
| 7 | `import-csv` from a spreadsheet | 5 | 3 | 3 | 2 | DONE (prior NOT-DONE #21) |
| 8 | 0.1.0 `--json` report works as a baseline | 2 | 1 | 1 | 1 | DONE |
| 9 | Stable text regardless of sub order (baseline keys) | 3 | 2 | 1 | 1 | DONE |
| 10 | Golden files for every output format | 3 | 1 | 2 | 1 | DONE |
| 11 | Property-based tests (hypothesis + seeded) | 3 | 1 | 2 | 1 | DONE |
| 12 | Mutation check script + boundary oracle tests | 3 | 1 | 3 | 1 | DONE |
| 13 | Author line pinned everywhere + `about` | 4 | 1 | 1 | 1 | DONE |
| 14 | Insurance with only limit/expiry is not "missing" | 3 | 1 | 1 | 1 | DONE |
| 15 | More provinces (BC, SK, QC) | 4 | 4 | 4 | 4 | NOT-DONE (no primary-source read this round; still says "not modelled") |
| 16 | Read certificates from PDF / OCR | 5 | 5 | 5 | 4 | NOT-DONE (dependencies, test PDFs) |
| 17 | Live WSIB / WCB clearance lookup | 5 | 5 | 5 | 5 | NOT-DONE (live service; WCB Manitoba's online system needs a registered account; terms unread) |
| 18 | Use the sub's own `province` | 2 | 2 | 3 | 3 | NOT-DONE |
| 19 | "Last verified on" date per clearance, warn if stale at payment | 4 | 4 | 2 | 3 | NOT-DONE (no regulator rule for how often to re-check; would be invented policy) |
| 20 | Certificate holder / named insured match | 3 | 3 | 3 | 3 | NOT-DONE (needs new fields; broker should confirm what matters) |
| 21 | Policy type (CGL vs auto), claims-made flag, cancellation notice | 3 | 3 | 3 | 3 | NOT-DONE |
| 22 | `holds` command: only the subs to stop paying | 4 | 3 | 2 | 2 | NOT-DONE (`--payment-on` + `--format md` covers most of it) |
| 23 | Read `.xlsx` directly | 4 | 2 | 4 | 3 | NOT-DONE (needs a dependency; CSV export works) |
| 24 | Trusted-Publishing release workflow; pin Actions to SHAs | 3 | 1 | 2 | 3 | NOT-DONE (needs Dan's PyPI setup; SHAs not verifiable offline) |
| 25 | SARIF / JUnit output; pre-commit hook | 2 | 2 | 3 | 2 | NOT-DONE (`--format github` covers CI) |

## What I could not test
- **Windows and macOS**: never run. The new golden tests compare bytes (written through `-o`, so no newline translation), which should be safe, but is unproven. Python 3.9 was not available: syntax-checked only.
- **Whether the GitHub repo is public**: a plain request to github.com through this sandbox returned 403, so I could not tell. The project URLs in `pyproject.toml` (from Round 4) are left in place; if the repo is private, delete the `[project.urls]` block before publishing (PUBLISH-CHECKLIST says so).
- **Manitoba letter validity period**, and whether WCB Manitoba treats a letter as covering work after its date: not stated on the pages I read; the tool does not claim it. A Manitoba WCB representative (204-954-4505 for assessment questions, per their page) could confirm.
- **Manitoba rules beyond the clearance page and the Act's sections 11, 89, 90**: not read (for example, how the "labour portion" is calculated, or any regulation).
- Real clearance letters or broker certificates: none were used; everything is synthetic.
- Competitor products: home pages only; ComplyWorks returned 403.
- `setuptools` older than 77 (unchanged from Round 4); PyPy; the GitHub Actions file has still never run.
