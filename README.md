# clearancewatch

**Your sub's paperwork, checked against the job calendar.** `clearancewatch` reads a jobs file and tells a project admin which workers'-comp clearances, insurance certificates and licences are expired, expire mid-job, are below your contract minimum, or look like data-entry mistakes, with a paste-ready chase list.

## What is verified, and what is policy

Checked against the regulators' own pages on 2026-11-07 (Ontario, Alberta) and 2026-11-08 (Manitoba):

| Rule | Source | Status |
|---|---|---|
| WSIB clearance number is valid **up to 90 days** and covers all of a business's contracts | [wsib.ca clearances](https://www.wsib.ca/en/businesses/premiums-and-payment/clearances) | verified |
| WCB Alberta: get a clearance **before hiring** and **before releasing payment**; without one you may be liable for the contractor's unpaid premiums | [wcb.ab.ca clearance letters](https://www.wcb.ab.ca/insurance-and-premiums/clearance-letters/), [when is a clearance needed](https://www.wcb.ab.ca/insurance-and-premiums/clearance-letters/when-is-a-clearance-needed/) | verified |
| WCB Manitoba: a clearance letter says whether a business, contractor or subcontractor is **in good standing**; general contractors and anyone hiring for construction, transportation and similar work should get it **before work commences and before any payment is made** | [wcb.mb.ca/clearances](https://www.wcb.mb.ca/clearances), FAQ "Who should get clearances?" | verified |
| WCB Manitoba: a firm without proper coverage is a **"deemed worker"** of the contractor (you report the *labour portion* of the contract in your payroll and cannot deduct that cost from the firm); **"deemed/default"** means it has also not complied with the Act; **supply-only** firms need no clearance | same page, FAQ entries on deemed workers and supply-only contracts | verified |
| Manitoba *The Workers Compensation Act* (C.C.S.M. c. W200): the principal must see that the contractor files the required statements (s. 11); a contractor and the person it works for are both liable for the assessment on the work (s. 90(1)); contractor and subcontractor likewise (s. 90(2)); a contractor is the principal as to its subcontractor (s. 89(3)) | [web2.gov.mb.ca w200 (PDF)](https://web2.gov.mb.ca/laws/statutes/ccsm/_pdf.php?cap=w200), consolidation current 1 June to 4 Nov 2026, read 2026-11-08 | verified as read; the tool only paraphrases these sections, it does not interpret them |
| How long a Manitoba clearance letter stays good | not found on the WCB Manitoba page | **unverified**: a Manitoba letter is treated as dated cover only, like Alberta, and the payment check tells you to request a fresh one |
| "A WSIB clearance must be valid for the **whole job**" | not found on the pages above | **unverified**: treated as conservative house policy (error severity) |
| "An Alberta letter covers work only **up to its date**" | not found on the pages above | **unverified**: treated as conservative house policy (warning `clearance_cover_lapsed`) |
| Clearance rules for other provinces (BC, SK, QC, ...) | not modelled | the tool says so (`province_not_modelled`) instead of guessing |

> **This is not legal advice.** It's a date-tracking assistant. Read the regulator's current page and confirm obligations with your broker, WSIB/WCB, or counsel before relying on any finding.

## Install

```bash
pip install clearancewatch   # Python 3.9+, no dependencies
```

**Heads-up:** everything below is version 0.2.0, which is not on PyPI yet. PyPI still had only 0.1.0 when this was written (checked 2026-11-07), and 0.1.0 has none of the `--format` / `--fail-on` / payment-date / `.ics` features or the `template` command. Until 0.2.0 is published, install from a checkout: `pip install .` (this line is removed when 0.2.0 is released; see `PUBLISH-CHECKLIST.md`).

Windows: not run on Windows (no Windows machine was available; reviewed by reading the code only). `clearancewatch template > jobs.json` in Windows PowerShell 5 writes UTF-16; the tool reads that. To get UTF-8 either way, use `clearancewatch template -o jobs.json` (`-o` is on `audit` and `renewals`; for `template` use `>` or copy the output).

From a spreadsheet: save it as CSV and run `clearancewatch import-csv subs.csv -o jobs.json` (columns below).

First run: `clearancewatch template > jobs.json`, then `clearancewatch audit jobs.json --on 2026-02-15` (the template is the example below and passes clean on that date). On Windows PowerShell use `clearancewatch template -o jobs.json` instead of `>`.

## Jobs file

```json
[
  {
    "name": "Kitchen reno",
    "province": "ON",
    "start": "2026-02-01",
    "end": "2026-03-30",
    "requirements": { "min_liability": "C$2M" },
    "subs": [
      {
        "name": "Bob's Drywall",
        "trade": "drywall",
        "clearance": { "issuer": "WSIB", "number": "1234567", "issued": "2026-01-10", "expires": "2026-04-10" },
        "insurance": { "provider": "Aviva", "policy": "GL-9", "coverage": "C$2M", "expires": "2026-12-31" },
        "licences": [ { "name": "Fall protection", "expires": "2026-09-01" } ]
      }
    ]
  }
]
```

## Usage

```bash
clearancewatch audit jobs.json --on 2026-02-15 --within 30
clearancewatch renewals jobs.json --within 30     # just what's coming due
clearancewatch audit jobs.json --format md        # chase list grouped by sub, paste into email/ticket
clearancewatch audit jobs.json --format csv       # for a spreadsheet
clearancewatch audit jobs.json --json             # machine-readable ("schema": 1, "version": ...)
clearancewatch audit jobs.json --format github    # GitHub Actions annotations (errors/warnings/notices)
clearancewatch audit jobs.json --format md -o chase.md   # write UTF-8 to a file; exit code unchanged
clearancewatch audit jobs.json --format ics > renewals.ics   # calendar events (all-day, 14-day reminder)
clearancewatch audit jobs.json --payment-on 2026-03-01       # is the clearance good on the day you pay?
clearancewatch audit jobs.json --active-only      # skip jobs whose end date has passed
clearancewatch audit jobs.json --json > week1.json; clearancewatch audit jobs.json --baseline week1.json   # only what is new
cat jobs.json | clearancewatch audit -            # stdin
clearancewatch schema > jobs.schema.json          # JSON Schema for editor validation
clearancewatch audit jobs.json --fail-on warn     # also fail CI on warnings (or: never)
clearancewatch renewals jobs.json --include-during-job
clearancewatch import-csv subs.csv -o jobs.json   # spreadsheet export, one row per sub, to a jobs file
clearancewatch about                              # who makes it, licence
```

Example output if Bob's clearance `expires` were `2026-03-15` and the insurance `2026-03-05` (the file above passes clean):

```
ERROR clearance_expires_during_job Kitchen reno / Bob's Drywall: clearance expires 2026-03-15 before job end 2026-03-30; house policy: hold a valid clearance for the whole job
WARN  insurance_expires_during_job Kitchen reno / Bob's Drywall: insurance expires 2026-03-05 before job end

1 error(s), 1 warning(s) — FAIL
```

Exit `0` pass, `1` findings at or above `--fail-on` (default: errors), `2` your data is broken (bad date, wrong shape, empty file, unreadable limit), `3` a bug in clearancewatch itself (never a finding; `CLEARANCEWATCH_DEBUG=1` shows the traceback). The message names the field, e.g. `jobs[0].subs[1].clearance.expires: expected a date like 2026-03-31`. An empty or unrecognisable file never passes silently.

## What it catches

| Finding | Severity |
|---|---|
| `clearance_missing` / `clearance_expired` / `clearance_no_expiry` / `clearance_no_coverage_dates` | error |
| `clearance_expires_during_job` | error; **warn** when the job is longer than one 90-day clearance could cover from the audit date (nothing can fix that today, so it reads as "plan a renewal"). `--strict-whole-job` keeps the error |
| `clearance_not_valid_at_payment` (a planned payment date, from `payment_dates` or `--payment-on`, falls after the clearance stops covering it) | warn |
| `job_has_no_subs` (a job with an empty `subs` list: nothing was checked) | info |
| `duplicate_job` (two jobs share a name, so reports and `--baseline` cannot tell them apart) | warn |
| `clearance_exempt` (you recorded `clearance_exempt: "reason"` and no clearance is on file) | info: a note, never fails a run |
| `clearance_dates_inconsistent` (expires before issued) | error |
| `clearance_term_exceeds_90_days` (WSIB dates longer than the stated maximum: typo?) | warn |
| `clearance_gap` (history shows days with no valid certificate inside the job) | warn |
| `clearance_number_shared` / `duplicate_sub` / `clearance_issued_in_future` | warn |
| `insurance_below_minimum` (job `requirements.min_liability`) | error |
| `insurance_limit_unreadable` (e.g. `US$`, `2 000 000`, `$2.000.000`, `1e6`, negatives: never guessed) | warn |
| `insurance_limit_ambiguous` (several amounts, none labelled "per occurrence", and the first is below the minimum but another meets it) | warn |
| `insurance_endorsement_missing` / `insurance_endorsement_unconfirmed` (job requires `additional_insured`, `waiver_of_subrogation` or `primary_noncontributory`; certificate says `false` / says nothing) | error / warn |
| `licence_missing` (job `requirements.required_licences` names a licence for the sub's trade and none matches) | error |
| `insurance_no_expiry` / `licence_no_expiry` | warn |
| `province_not_modelled` / `unknown_field` (typo'd key was ignored) | warn |
| `job_dates_invalid` | error |
| `clearance_cover_lapsed` (an Alberta or Manitoba letter predates ongoing work) | warn |
| `clearance_after_work_started` (sub's own `start` is earlier than the earliest clearance on file; AB/MB jobs) | warn |
| `clearance_status_not_good` (letter status is "deemed/default", or says "not in good standing") | error |
| `clearance_status_deemed_worker` (WCB Manitoba "deemed worker": you report the labour portion in your payroll) | warn |
| `clearance_status_unrecognised` (a `status` that is none of the three WCB Manitoba words) | warn |
| `clearance_supply_only` (you recorded `supply_only: true` and no clearance is on file) | info |
| `insurance_limit_includes_umbrella` (primary limit under the minimum, text mentions umbrella/excess: check the contract) | warn |
| `issuer_mismatch` (ON job, WCB-AB clearance — or vice versa) | warn |
| `insurance_missing` / `insurance_expired` | error |
| `insurance_expires_during_job` / `licence_expires_during_job` | warn |
| `licence_expired` | error |
| `renewal_due` / `insurance_renewal_due` / `licence_renewal_due` (within `--within` days) | warn |

### Manitoba and the other optional fields (all new in 0.2.0)

```json
{
  "name": "Winnipeg infill", "province": "MB",
  "subs": [
    { "name": "Prairie Framing", "start": "2026-05-01",
      "clearance": { "issuer": "WCB Manitoba", "number": "77", "issued": "2026-05-20", "status": "good standing" } },
    { "name": "Lumber Yard", "supply_only": true }
  ]
}
```

A Manitoba (or Alberta) clearance is a dated **letter**: give `issued` (and `covered_until` if the letter states one). `status` is what the letter says: `good standing`, `deemed worker` or `deemed/default`. `start` is the day that sub's own work starts: a letter dated after it is flagged (both regulators say to get the clearance before work starts). `supply_only: true` records that the sub only supplies material; the tool only prints a note for you to confirm.

### Optional fields (all new in 0.2.0)

```json
{
  "name": "Kitchen reno",
  "payment_dates": ["2026-03-01", "2026-03-31"],
  "requirements": {
    "min_liability": "C$2M",
    "additional_insured": true, "waiver_of_subrogation": true, "primary_noncontributory": false,
    "required_licences": { "electrical": "electrician" }
  },
  "subs": [{
    "name": "Sparky Ltd", "trade": "electrical",
    "insurance": { "coverage": "C$2M per occurrence", "additional_insured": true, "waiver_of_subrogation": false },
    "clearance_exempt": "sole proprietor, no workers"
  }]
}
```

Endorsement flags are `true` / `false` / absent (not recorded), never `"yes"`. `required_licences` maps a sub's `trade` (exact, case-insensitive) to text that must appear in one of its licence names. `clearance_exempt` is **your** statement, not something the tool knows: it only produces a note for a human to confirm with the regulator (WSIB's own page says some independent operators may not be registered and so cannot get a clearance, but the tool does not decide who is exempt). The endorsement and licence checks compare what you typed; they do not read the certificate.

## Python API

```python
import datetime as dt
from clearancewatch import Job, audit

job = Job.from_dict({...})
for finding in audit(job, on=dt.date(2026, 2, 15), horizon=30):
    print(finding.severity, finding.code, finding.detail)
```

`clearancewatch renewals` over a weekly cron gives you the "call these three subs" list before a gap becomes a deeming problem.

Renewal history: give a sub several certificates with `"clearances": [...]` (the newest decides expiry; gaps between them are reported).

## From a spreadsheet

`clearancewatch import-csv subs.csv -o jobs.json` reads a CSV (UTF-8, or Excel's "Unicode Text"/UTF-16) with a header row and one row per sub. Column names are not case-sensitive and spaces count as underscores. Needed: `job`, `sub`. Allowed: `province`, `start`, `end` (job, taken from the job's first row; a later row that disagrees stops the import), `min_liability`, `require_additional_insured`, `require_waiver_of_subrogation`, `require_primary_noncontributory`, `trade`, `sub_start`, `supply_only`, `clearance_exempt`, `clearance_issuer`, `clearance_number`, `clearance_issued`, `clearance_expires`, `clearance_covered_until`, `clearance_status`, `insurance_provider`, `insurance_policy`, `insurance_coverage`, `insurance_expires`, `insurance_additional_insured`, `insurance_waiver_of_subrogation`, `insurance_primary_noncontributory`, `licence_name`, `licence_number`, `licence_authority`, `licence_expires`. A second row for the same job and sub adds a licence and/or an older clearance (renewal history). Yes/no columns take yes, no, true, false, 1, 0. An unknown column, a date that is not `YYYY-MM-DD` (Excel often saves `2/15/2026`; format the column as text `YYYY-MM-DD` first) or a bad yes/no stops the import with the row number; nothing is guessed.

## Hostile or messy data

Names and issuers come from emails and PDFs. Terminal escapes, bidi/zero-width characters and newlines are shown as `\uXXXX`; CSV cells starting with `= + - @` are neutralised; Markdown table characters and `[ ]` (so a name cannot become a link) are escaped; `.ics` text is escaped per RFC 5545 and cannot inject events; fields are length-capped. A console that cannot show a character (legacy Windows code page, `PYTHONIOENCODING=ascii`) gets a `\x..` escape instead of a crash. Absurd limits (`1e999`, thousand-digit numbers) are reported, not fatal. Typo'd field names are reported rather than silently dropped. Dates must be `YYYY-MM-DD` (years 1900-2200). Line/paragraph separators (U+2028/2029) are escaped too. `NaN` / `Infinity` in the JSON are refused. Files may be UTF-8, UTF-8 with BOM, or UTF-16 with BOM (what Windows PowerShell 5 writes for `>`).

## How it compares

| | clearancewatch | Avetta / ComplyWorks / Procore / TrustLayer / myCOI |
|---|---|---|
| What it is | free local CLI/library, one JSON file, MIT | commercial platforms (TrustLayer's own site says "Pricing varies depending on platform usage", read 2026-11-07; other prices unverified) |
| Data leaves your machine | no | unverified; hosted products by design |
| Sub self-service portal, document upload, COI parsing | **no** | advertised by vendors (unverified) |
| WSIB / WCB Alberta date rules with sources | yes, see table above | unverified |
| Reads the certificate itself (OCR/PDF) | **no**, you type the dates | TrustLayer: "reads each COI, checks it against your standards" ([trustlayer.io](https://www.trustlayer.io/)); myCOI's current product: reviews COIs and endorsements incl. additional insured, waiver of subrogation, primary and non-contributory, per-project aggregates ([illumend.ai](https://www.illumend.ai/)); not tested |
| Endorsements (additional insured, waiver, primary/non-contributory) | you type true/false from the certificate; flagged if missing | vendors say they check them automatically (above, unverified) |
| Calendar export | `.ics`, local | unverified |

Vendor home pages read on 2026-11-07: [avetta.com](https://www.avetta.com/) (supplier safety and compliance, "360,000+ businesses"), [trustlayer.io](https://www.trustlayer.io/) (verification of insurance, licences, compliance docs; Procore panel, API), [illumend.ai](https://www.illumend.ai/) (mycoitracking.com redirected there on that date; says it is myCOI's AI-native product). The closest open-source project found, [OpenCOI](https://github.com/ajayasai/opencoi) (AGPL-3.0, Node.js 24+, PDF extraction with human review, limit comparison USD-only per its README), is a different shape: a self-hosted web app for US-style COIs; it was not run here, and its GitHub page returned 403 to an automated fetch on the second look (2026-11-07), so those details are from round 3 and not re-checked. [complyworks.com](https://www.complyworks.com/) blocked automated access and a Procore compliance page returned 404, so nothing is claimed about them. None of these products was run or priced; this is not a feature-by-feature review.

## Benchmark (re-runnable)

`python bench/run.py` plants one defect in each of 100 otherwise-clean jobs (25 kinds x 4, fixed seed) plus 36 clean jobs (some ongoing, some with three subs, some with a deductible in the coverage text, 6 Manitoba), and compares clearancewatch with a stand-in for a spreadsheet date column (flags only explicit expiry dates already past or within 30 days).

| | clearancewatch | date-column stand-in |
|---|---|---|
| planted defects caught (at the right severity) | 100/100 | 20/100 (20%) |
| false alarms on 36 clean jobs | 0 | 0 |
| speed | about 105,000-120,000 sub audits/s on one core of a quiet shared cloud VM; Round 4 measured 17,000-45,000 on a busy one, so treat it as "varies 5x with VM load" | n/a |

Round 5 compared the previous commit and this one back to back on the same quiet VM (3 runs each): about 117,000 vs 107,000 sub audits/s, so the new checks cost roughly 8%.

History: round 2 measured 64/64 on 16 kinds; round 4 84/84 on 21 kinds; round 5 added 4 kinds (Manitoba status x2, work started before the clearance, umbrella text) and the clean jobs with deductibles and Manitoba letters (the first version of the Manitoba clean jobs found a bug in the corpus itself: extra subs kept Ontario certificates). An earlier README said "~130,000 sub audits/s"; that figure was not reproducible and was removed.

Honest caveat: I wrote both the corpus and the checks, so 100/100 shows the checks do what they claim and guards against regressions. It does not predict accuracy on your real documents, and the stand-in is not any commercial product. Separate from the benchmark, `python bench/mutate.py` breaks the checks one condition at a time and counts how many of those breakages the tests notice (Round 5: 63% before the new boundary/golden/property tests, 98% after).

## Limits

- Not run on Windows or macOS; tested on Linux with Python 3.9, 3.10, 3.11, 3.12 and 3.13 only. The CI file also lists Windows and macOS, but it has not run there yet.
- You type the dates; nothing is read from PDFs and nothing is checked against WSIB/WCB (no live clearance lookup).
- Only Ontario (WSIB), Alberta (WCB) and Manitoba (WCB) are modelled. Other provinces get date checks plus a warning. A sub's own `province` field is stored but not used; the job's province decides the rules.
- Payment-date checks compare your dates with the dates you typed. WCB Alberta's page (read 2026-11-07) and WCB Manitoba's page (read 2026-11-08) do not say how long a letter stays valid, so for an Alberta or Manitoba letter the tool only checks the letter is dated on or after the payment and says so.
- `--baseline` matches findings on exact text, so use the same `--within` and the same command for both runs.
- `--format ics` only has events for findings that carry a date (expiries); `renewals` needs `--include-during-job` to include documents that expire before the job ends.
- "Whole job" and "Alberta letter date" rules are house policy (see the verification table); tune severity with `--fail-on`. WSIB's page says a clearance is valid up to 90 days and does not say whether it must cover a whole job.
- Insurance limits are the per-occurrence amount if the text labels one, else the first amount found in free text (`C$2M`, `$2,000,000`, `2 million`); amounts next to *deductible*, *retention* or *SIR* are ignored; a small bare number such as the `1` in `1/2M` makes the text unreadable (flagged, not guessed); umbrella/excess layers are never added up (`insurance_limit_includes_umbrella` asks you to check the contract); `US$`/other currencies are flagged, not converted. Additional-insured and waiver-of-subrogation wording are not checked.

## License

MIT, Copyright (c) 2026 Calas Automations Inc. Use it, ship it, no warranty. Maintained by Calas Automations Inc.

## Coming from 0.1.0

Jobs files written for 0.1.0 still load. What changed for them: dates must be `YYYY-MM-DD` (0.1.0 also took `20260101` on Python 3.11+; now it says so and exits 2); a bare `WCB` issuer no longer gets an automatic 90-day expiry outside Ontario (you get `clearance_no_expiry` or, on an Alberta/Manitoba job, a dated letter); "expires during the job" is a warning when the job is longer than one 90-day clearance; empty jobs are reported. A 0.1.0 `--json` report can be used as a `--baseline` (its text for some findings has changed, so a few old findings will show as new once).
