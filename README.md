# clearancewatch

**A principal must hold valid workers'-comp coverage for every sub — for the whole job.** `clearancewatch` audits subcontractor compliance documents against the job calendar and tells you what's expired, what expires mid-job, and what's coming up for renewal.

Rules modelled from official sources (verified October 2026):

- **Ontario WSIB**: clearance certificates are valid **up to 90 days**; WSIB states a principal must ensure a valid clearance is in place for the **full length of a job**. ([wsib.ca clearances](https://www.wsib.ca/en/businesses/premiums-and-payment/clearances))
- **Alberta WCB**: a clearance letter is valid for work done **up to the date of the letter** — WCB advises requesting one at hire and before each installment. ([wcb.ab.ca clearance letters](https://www.wcb.ab.ca/insurance-and-premiums/clearance-letters/))

> **This is not legal advice.** It's a date-tracking assistant built on the rules above; confirm obligations with your broker, WSIB/WCB, or counsel.

## Install

```bash
pip install clearancewatch
```

## Jobs file

```json
[
  {
    "name": "Kitchen reno",
    "province": "ON",
    "start": "2026-02-01",
    "end": "2026-03-30",
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
clearancewatch audit jobs.json --json             # machine-readable
```

```
ERROR clearance_expires_during_job  Kitchen reno / Bob's Drywall: clearance expires 2026-03-15 before job end 2026-03-30...
WARN  renewal_due                   Kitchen reno / Bob's Drywall: insurance expires 2026-03-05 (within 30 days)

1 error(s), 1 warning(s) — FAIL
```

Exit `1` when any error-severity finding exists (missing/expired clearance, lapsed coverage, expired insurance or licence) — CI- and cron-friendly.

## What it catches

| Finding | Severity |
|---|---|
| `clearance_missing` / `clearance_expired` / `clearance_expires_during_job` | error |
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

## License

MIT-style: use it, ship it, no warranty.
