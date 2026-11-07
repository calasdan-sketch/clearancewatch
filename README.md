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

**Heads-up:** the 0.2.0 features below (`--format`, `--fail-on`, payment-date checks, `.ics`, ...) are unreleased. The version on PyPI when this was written (2026-11-07) was 0.1.0. Until 0.2.0 is published, install from a checkout: `pip install .` (or `PYTHONPATH=src python -m clearancewatch.cli ...`).

First run: `clearancewatch template > jobs.json`, then `clearancewatch audit jobs.json --on 2026-02-15` (the template is the example below and passes clean on that date).

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
clearancewatch audit jobs.json --format ics > renewals.ics   # calendar events (all-day, 14-day reminder)
clearancewatch audit jobs.json --payment-on 2026-03-01       # is the clearance good on the day you pay?
clearancewatch audit jobs.json --active-only      # skip jobs whose end date has passed
clearancewatch audit jobs.json --json > week1.json; clearancewatch audit jobs.json --baseline week1.json   # only what is new
cat jobs.json | clearancewatch audit -            # stdin
clearancewatch schema > jobs.schema.json          # JSON Schema for editor validation
clearancewatch audit jobs.json --fail-on warn     # also fail CI on warnings (or: never)
clearancewatch renewals jobs.json --include-during-job
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
| `clearance_cover_lapsed` (Alberta letter predates ongoing work) | warn |
| `issuer_mismatch` (ON job, WCB-AB clearance — or vice versa) | warn |
| `insurance_missing` / `insurance_expired` | error |
| `insurance_expires_during_job` / `licence_expires_during_job` | warn |
| `licence_expired` | error |
| `renewal_due` / `insurance_renewal_due` / `licence_renewal_due` (within `--within` days) | warn |

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

## Hostile or messy data

Names and issuers come from emails and PDFs. Terminal escapes, bidi/zero-width characters and newlines are shown as `\uXXXX`; CSV cells starting with `= + - @` are neutralised; Markdown table characters and `[ ]` (so a name cannot become a link) are escaped; `.ics` text is escaped per RFC 5545 and cannot inject events; fields are length-capped. A console that cannot show a character (legacy Windows code page, `PYTHONIOENCODING=ascii`) gets a `\x..` escape instead of a crash. Absurd limits (`1e999`, thousand-digit numbers) are reported, not fatal. Typo'd field names are reported rather than silently dropped. Dates must be `YYYY-MM-DD` (years 1900-2200).

## How it compares

| | clearancewatch | Avetta / ComplyWorks / Procore / TrustLayer / myCOI |
|---|---|---|
| What it is | free local CLI/library, one JSON file, MIT | commercial platforms (unverified: pricing, exact features) |
| Data leaves your machine | no | unverified; hosted products by design |
| Sub self-service portal, document upload, COI parsing | **no** | advertised by vendors (unverified) |
| WSIB / WCB Alberta date rules with sources | yes, see table above | unverified |
| Reads the certificate itself (OCR/PDF) | **no**, you type the dates | TrustLayer: "reads each COI, checks it against your standards" ([trustlayer.io](https://www.trustlayer.io/)); myCOI's current product: reviews COIs and endorsements incl. additional insured, waiver of subrogation, primary and non-contributory, per-project aggregates ([illumend.ai](https://www.illumend.ai/)); not tested |
| Endorsements (additional insured, waiver, primary/non-contributory) | you type true/false from the certificate; flagged if missing | vendors say they check them automatically (above, unverified) |
| Calendar export | `.ics`, local | unverified |

Vendor home pages read on 2026-11-07: [avetta.com](https://www.avetta.com/) (supplier safety and compliance, "360,000+ businesses"), [trustlayer.io](https://www.trustlayer.io/) (verification of insurance, licences, compliance docs; Procore panel, API), [illumend.ai](https://www.illumend.ai/) (mycoitracking.com redirected there on that date; says it is myCOI's AI-native product). The closest open-source project found, [OpenCOI](https://github.com/ajayasai/opencoi) (AGPL-3.0, Node.js 24+, PDF extraction with human review, limit comparison USD-only per its README), is a different shape: a self-hosted web app for US-style COIs; it was not run here. [complyworks.com](https://www.complyworks.com/) blocked automated access and a Procore compliance page returned 404, so nothing is claimed about them. None of these products was run or priced; this is not a feature-by-feature review.

## Benchmark (re-runnable)

`python bench/run.py` plants one defect in each of 84 otherwise-clean jobs (21 kinds x 4, fixed seed) plus 30 clean jobs (some ongoing, some with three subs), and compares clearancewatch with a stand-in for a spreadsheet date column (flags only explicit expiry dates already past or within 30 days). A planted defect only counts as caught if the right code is reported **at the right severity**.

| | clearancewatch | date-column stand-in |
|---|---|---|
| planted defects caught | 84/84 | 20/84 (24%) |
| false alarms on 30 clean jobs | 0 | 0 |
| speed | roughly 20,000-45,000 sub audits/s on a shared cloud VM, one core (varies run to run; yours will differ) | n/a |

History: round 2 measured 64/64 on 16 kinds; the corpus now has 5 more kinds (endorsements, required licence, payment date, ambiguous limit) and a stricter caught-at-right-severity rule. An earlier README said "~130,000 sub audits/s"; that figure was not reproducible and has been removed.

Honest caveat: I wrote both the corpus and the checks, so 84/84 shows the checks do what they claim and guards against regressions. It does not predict accuracy on your real documents, and the stand-in is not any commercial product.

## Limits

- You type the dates; nothing is read from PDFs and nothing is checked against WSIB/WCB (no live clearance lookup).
- Only Ontario (WSIB) and Alberta (WCB) are modelled. Other provinces get date checks plus a warning. A sub's own `province` field is stored but not used; the job's province decides the rules.
- Payment-date checks compare your dates with the dates you typed. WCB Alberta's page does not say how long a letter stays valid (read 2026-11-07), so for an Alberta letter the tool only checks the letter is dated on or after the payment and says so.
- `--baseline` matches findings on exact text, so use the same `--within` and the same command for both runs.
- `--format ics` only has events for findings that carry a date (expiries); `renewals` needs `--include-during-job` to include documents that expire before the job ends.
- "Whole job" and "Alberta letter date" rules are house policy (see the verification table); tune severity with `--fail-on`. WSIB's page says a clearance is valid up to 90 days and does not say whether it must cover a whole job.
- Insurance limits are the first amount found in free text (`C$2M`, `$2,000,000`, `2 million`); `US$`/other currencies are flagged, not converted. Additional-insured and waiver-of-subrogation wording are not checked.

## License

MIT-style: use it, ship it, no warranty.
