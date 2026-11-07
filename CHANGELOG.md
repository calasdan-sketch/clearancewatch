# Changelog

## 0.2.0 (unreleased)

### Round 4 (first-hour user, release engineer, supply-chain reviewer, docs/DX writer, CI integrator, hostile-input fuzzer, performance engineer, competitor maintainer; see docs/ROUND4.md)

Fixed
- Source distribution did not contain `bench/` (or the changelog), so `pytest` failed on an unpacked sdist (`No module named 'corpus'`). Added `MANIFEST.in`.
- `pytest` from a fresh clone failed with `No module named 'clearancewatch'` unless the package was installed first; `pythonpath = ["src"]` is now configured.
- Build requirement `setuptools>=68` could not read `license = "MIT"` (SPDX, needs 77+); now `>=77`.
- Metadata: author was a GitHub handle, now "Calas Automations Inc."; added project URLs, Python 3.9-3.13 / OS-independent / typed classifiers; ship `py.typed`.
- A Windows PowerShell 5 redirect (`clearancewatch template > jobs.json`) writes UTF-16 and the next `audit` said "not UTF-8". UTF-16 files (with BOM) now load.
- `NaN` / `Infinity` in the JSON were accepted; now exit 2.
- `--within abc` printed `invalid _non_negative value`; now "expected a whole number of days".
- U+2028 / U+2029 (line/paragraph separators) in names were not escaped and could split a report line.
- Closed-pipe handling now also covers the errors Windows reports (EPIPE/EINVAL), and ics output no longer needs `sys.stdout.buffer`.
- Package docstring still said "a principal must hold a valid clearance for the whole job" as if verified; now says it is house policy, like the README.
- Two mypy errors; CI now runs ruff and mypy.

Added
- `--format github` (GitHub Actions annotations) and `-o/--output FILE` (UTF-8, replaced in one step) on `audit`, `renewals`, `template`, `schema`.
- JSON report gained `"schema": 1` and `"version"`.
- `job_has_no_subs` (info) and `duplicate_job` (warn).
- CI matrix: Windows and macOS (not yet run there), Python 3.9 and 3.13, plus "tests pass from the sdist".

Compatibility: nothing removed. New JSON keys and two new finding codes are additive; consumers should already tolerate unknown codes. Recommended release: 0.2.0 (still pre-1.0; behaviour changes in the Round 3 notes below are the reason it is not 0.1.1).

### Round 3 (contract-compliance auditor, insurance broker, project admin, attacker, performance engineer, docs/DX lead, competitor engineer)

Added
- `--payment-on DATE` (repeatable) and job `payment_dates`: `clearance_not_valid_at_payment` when a planned payment falls after the clearance stops covering it.
- Insurance endorsements: `requirements.additional_insured` / `waiver_of_subrogation` / `primary_noncontributory` with `insurance_endorsement_missing` (certificate says false) and `insurance_endorsement_unconfirmed` (nothing recorded). Strict true/false only.
- `requirements.required_licences` (trade -> licence-name text) with `licence_missing`.
- `clearance_exempt: "reason"` on a sub: an `info` note instead of `clearance_missing`. New severity `info`; it never fails a run, counts as "note(s)", and JSON gets an `info` count. Consumers that assumed only `error`/`warn` should tolerate it.
- `insurance_limit_ambiguous` when a coverage string lists several amounts and only a non-first one meets the minimum.
- `--format ics` (all-day events, 14-day reminder, RFC 5545 escaping/folding, stable UIDs); findings gained an optional `due` date (JSON `due`).
- `--baseline PREV.json` (only new findings), `--active-only`, `--strict-whole-job`, stdin via `-`, `clearancewatch template`, `clearancewatch schema`.
- Exit code `3` for an internal error (was exit 1, indistinguishable from "findings").
- Bench: 84 defects / 21 kinds / 30 clean jobs; a defect counts only at the right severity.

Fixed
- `parse_limit` crashed (`OverflowError`, exit 1 with a traceback) on `1e999`-style or 400-digit amounts, read `-5` as 5, `2 000 000` as 2, `$2.000.000` as 2, `1e6` as 6, and ignored per-occurrence vs aggregate. Now unreadable (a warning) unless unambiguous; amounts above a trillion are refused.
- A legacy console (`PYTHONIOENCODING=ascii`, old Windows code pages) turned any non-ASCII name into a traceback; output now degrades to `\x..` escapes. `| head` no longer prints a traceback.
- An absurdly long integer in the jobs file raised a bare `ValueError`; now exit 2.
- Hostile input: 20,000 subs sharing one clearance number was quadratic and produced a 100 KB finding; now linear and capped ("and N more").
- Markdown chase list: names like `[text](url)` rendered as links; brackets are now escaped.
- The 90-day default was applied to gap detection for non-WSIB boards; it no longer is.
- README: the sample output block did not match the tool (wrong code/wording); the quick start pointed at a PyPI version (0.1.0) that lacks these features; "~130,000 sub audits/s" was not reproducible (measured ~20-45k/s on this machine, which varies). All three corrected; tests now compare the README example and sample output with the tool.

Changed (behaviour)
- `clearance_expires_during_job` is a warning (not an error) when the job runs longer than one 90-day clearance could cover from the audit date: an unfixable error that blocked CI until the final certificate. `--strict-whole-job` restores the old behaviour. Jobs a single clearance could cover stay errors.
- Competitor notes refreshed 2026-11-07: mycoitracking.com now redirects to illumend.ai (myCOI's AI product); OpenCOI (AGPL) added.

Speed: per-string caching of issuer, province and limit parsing recovered the cost of the new checks. On the same shared VM the benchmark ran ~31-35k subs/s before this round and ~21-47k after (run-to-run noise is larger than the difference, and the corpus is heavier now); treat it as "tens of thousands per second".


Expert deep-dive (construction risk manager, WCB/WSIB compliance specialist, first-time project admin, document-data QA engineer).

### Added
- `--format text|json|csv|md` (markdown chase list grouped by sub, with the action to take), `--fail-on error|warn|never`, `renewals --include-during-job`.
- Exit code `2` for bad input, distinct from `1` (findings).
- Job `requirements.min_liability` with `insurance_below_minimum` / `insurance_limit_unreadable`.
- Renewal history via `clearances: [...]`; `clearance_gap`.
- Document-QA findings: `clearance_dates_inconsistent`, `clearance_term_exceeds_90_days`, `clearance_issued_in_future`, `clearance_number_shared`, `duplicate_sub`, `job_dates_invalid`, `unknown_field`, `province_not_modelled`.
- Hostile-text hygiene (`safe.py`): control/bidi/zero-width escaping, CSV formula guard, Markdown escaping.
- `bench/` re-runnable benchmark and a regression test over it.

### Fixed
- Malformed dates, wrong shapes, bad `--on` crashed with a traceback (exit 1); now a clear message naming the field, exit 2. Strict `YYYY-MM-DD`, years 1900-2200 (no date-overflow crash).
- `{}`, `[]` or an unrelated object used to pass as "0 errors"; now rejected.
- "WCB Labrador" was treated as Alberta (substring match on "AB"); issuers now match whole words. Province names (`ontario`) accepted.
- The 90-day WSIB default was silently applied to other boards' certificates; now `clearance_no_expiry` + `province_not_modelled`.
- Generic `WCB` issuer on an Ontario job now warns.
- UTF-8 BOM files load. `renewals --help` no longer claims exit 1 when something is due (it never did).
- README: separated verified rules from unverified house policy; the "full length of a job" and "Alberta letter up to its date" wording is not on the cited pages.

### Compatibility
Python API unchanged (new optional fields only; `Finding` gained `job`/`sub`; JSON gained `job`/`sub`/`jobs`). `renewals()` default unchanged. All 18 original tests pass untouched except one unused-variable lint fix.
