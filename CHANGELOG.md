# Changelog

## 0.2.0 (unreleased)

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
