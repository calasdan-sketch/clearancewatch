# clearancewatch

**Your sub's paperwork, checked against the job calendar.** `clearancewatch` reads a jobs file and tells a project admin which workers'-comp clearances, insurance certificates and licences are expired, expire mid-job, are below your contract minimum, or look like data-entry mistakes, with a paste-ready chase list.

## What is verified, and what is policy

Checked against the regulators' own pages on 2026-11-07:

| Rule | Source | Status |
|---|---|---|
| WSIB clearance number is valid **up to 90 days** and covers all of a business's contracts | [wsib.ca clearances](https://www.wsib.ca/en/businesses/premiums-and-payment/clearances) | verified |
| WCB Alberta: get a clearance **before hiring** and **before releasing payment**; without one you may be liable for the contractor's unpaid premiums | [wcb.ab.ca clearance letters](https://www.wcb.ab.ca/insurance-and-premiums/clearance-letters/), [when is a clearance needed](https://www.wcb.ab.ca/insurance-and-premiums/clearance-letters/when-is-a-clearance-needed/) | verified |
| "A WSIB clearance must be valid for the **whole job**" | not found on the pages above | **unverified**: treated as conservative house policy (error severity) |
| "An Alberta letter covers work only **up to its date**" | not found on the pages above | **unverified**: treated as conservative house policy (warning `clearance_cover_lapsed`) |
| Clearance rules for other provinces | not modelled | the tool says so (`province_not_modelled`) instead of guessing |

> **This is not legal advice.** It's a date-tracking assistant. Read the regulator's current page and confirm obligations with your broker, WSIB/WCB, or counsel before relying on any finding.

## Install

```bash
pip install clearancewatch   # Python 3.9+, no dependencies
```

First run: save the example below as `jobs.json`, then `clearancewatch audit jobs.json --on 2026-02-15`.

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
clearancewatch audit jobs.json --json             # machine-readable
clearancewatch audit jobs.json --fail-on warn     # also fail CI on warnings (or: never)
clearancewatch renewals jobs.json --include-during-job
```

Example output if Bob's clearance `expires` were `2026-03-15` and the insurance `2026-03-05` (the file above passes clean):

```
ERROR clearance_expires_during_job  Kitchen reno / Bob's Drywall: clearance expires 2026-03-15 before job end 2026-03-30...
WARN  renewal_due                   Kitchen reno / Bob's Drywall: insurance expires 2026-03-05 (within 30 days)

1 error(s), 1 warning(s) — FAIL
```

Exit `0` pass, `1` findings at or above `--fail-on` (default: errors), `2` your data is broken (bad date, wrong shape, empty file). The message names the field, e.g. `jobs[0].subs[1].clearance.expires: expected a date like 2026-03-31`. An empty or unrecognisable file never passes silently.

## What it catches

| Finding | Severity |
|---|---|
| `clearance_missing` / `clearance_expired` / `clearance_expires_during_job` / `clearance_no_expiry` | error |
| `clearance_dates_inconsistent` (expires before issued) | error |
| `clearance_term_exceeds_90_days` (WSIB dates longer than the stated maximum: typo?) | warn |
| `clearance_gap` (history shows days with no valid certificate inside the job) | warn |
| `clearance_number_shared` / `duplicate_sub` / `clearance_issued_in_future` | warn |
| `insurance_below_minimum` (job `requirements.min_liability`) | error |
| `insurance_limit_unreadable` (e.g. `US$` limits are not compared, never guessed) | warn |
| `province_not_modelled` / `unknown_field` (typo'd key was ignored) | warn |
| `job_dates_invalid` | error |
| `clearance_cover_lapsed` (Alberta letter predates ongoing work) | warn |
| `issuer_mismatch` (ON job, WCB-AB clearance — or vice versa) | warn |
| `insurance_missing` / `insurance_expired` | error |
| `insurance_expires_during_job` | warn |
| `licence_expired` | error |
| `renewal_due` / `insurance_renewal_due` / `licence_renewal_due` (within `--within` days) | warn |

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

## Hostile or messy data

Names and issuers come from emails and PDFs. Terminal escapes, bidi/zero-width characters and newlines are shown as `\uXXXX`; CSV cells starting with `= + - @` are neutralised; Markdown table characters are escaped; fields are length-capped. Typo'd field names are reported rather than silently dropped. Dates must be `YYYY-MM-DD` (years 1900-2200).

## How it compares

| | clearancewatch | Avetta / ComplyWorks / Procore / TrustLayer / myCOI |
|---|---|---|
| What it is | free local CLI/library, one JSON file, MIT | commercial platforms (unverified: pricing, exact features) |
| Data leaves your machine | no | unverified; hosted products by design |
| Sub self-service portal, document upload, COI parsing | **no** | advertised by vendors (unverified) |
| WSIB / WCB Alberta date rules with sources | yes, see table above | unverified |
| Reads the certificate itself (OCR/PDF) | **no**, you type the dates | TrustLayer and myCOI describe automated COI review on their sites ([trustlayer.io](https://www.trustlayer.io/), [mycoitracking.com](https://www.mycoitracking.com/)); not tested |

Vendor home pages read on 2026-11-07: [avetta.com](https://www.avetta.com/) (supplier safety and compliance, "360,000+ businesses"), [trustlayer.io](https://www.trustlayer.io/) (verification of insurance, licences, compliance docs), [mycoitracking.com](https://www.mycoitracking.com/) (COI tracking). [complyworks.com](https://www.complyworks.com/) blocked automated access and a Procore compliance page returned 404, so nothing is claimed about them. None of these products was run or priced; this is not a feature-by-feature review.

## Benchmark (re-runnable)

`python bench/run.py` plants one defect in each of 64 otherwise-clean jobs (16 kinds x 4, fixed seed) plus 24 clean jobs, and compares clearancewatch with a stand-in for a spreadsheet date column (flags only explicit expiry dates already past or within 30 days):

| | clearancewatch | date-column stand-in |
|---|---|---|
| planted defects caught | 64/64 | 20/64 (31%) |
| false alarms on 24 clean jobs | 0 | 0 |
| speed | ~130,000 sub audits/s, one core | n/a |

Honest caveat: I wrote both the corpus and the checks, so 64/64 shows the checks do what they claim and guards against regressions. It does not predict accuracy on your real documents, and the stand-in is not any commercial product.

## Limits

- You type the dates; nothing is read from PDFs and nothing is checked against WSIB/WCB (no live clearance lookup).
- Only Ontario (WSIB) and Alberta (WCB) are modelled. Other provinces get date checks plus a warning.
- "Whole job" and "Alberta letter date" rules are house policy (see the verification table); tune severity with `--fail-on`.
- Insurance limits are the first amount found in free text (`C$2M`, `$2,000,000`, `2 million`); `US$`/other currencies are flagged, not converted. Additional-insured and waiver-of-subrogation wording are not checked.

## License

MIT-style: use it, ship it, no warranty.
