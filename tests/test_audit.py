"""Audit-rule tests with pinned dates."""
import datetime as dt

from clearancewatch.audit import audit, renewals
from clearancewatch.model import Clearance, Insurance, Job, Licence, Subcontractor

D = dt.date.fromisoformat


def on_job(subs, start="2026-02-01", end="2026-03-30", province="ON", name="Job A"):
    return Job(name=name, province=province, start=D(start), end=D(end) if end else None, subs=subs)


def on_sub(**kw):
    base = dict(name="Bob's Drywall", province="ON",
                clearance=Clearance(issuer="WSIB", number="123", issued=D("2026-01-10"),
                                    expires=D("2026-04-10")),
                insurance=Insurance(provider="Aviva", policy="P-1", expires=D("2026-12-31")))
    base.update(kw)
    return Subcontractor(**base)


def codes(findings):
    return [f.code for f in findings]


def test_happy_path_clean():
    findings = audit(on_job([on_sub()]), on=D("2026-02-15"))
    assert findings == [], findings


def test_expiry_defaults_to_90_days_for_wsib():
    c = Clearance(issuer="WSIB", issued=D("2026-01-10"))
    assert c.effective_expiry() == D("2026-04-10")


def test_expired_clearance():
    sub = on_sub(clearance=Clearance(issuer="WSIB", issued=D("2025-06-01"), expires=D("2025-08-29")))
    findings = audit(on_job([sub]), on=D("2026-02-15"))
    assert "clearance_expired" in codes(findings)


def test_clearance_expires_during_job():
    sub = on_sub(clearance=Clearance(issuer="WSIB", issued=D("2026-01-20"), expires=D("2026-03-15")))
    findings = audit(on_job([sub]), on=D("2026-02-15"))
    assert "clearance_expires_during_job" in codes(findings)


def test_missing_clearance_and_insurance():
    sub = Subcontractor(name="NoDocs", clearance=None, insurance=None)
    found = codes(audit(on_job([sub]), on=D("2026-02-15")))
    assert "clearance_missing" in found and "insurance_missing" in found


def test_renewal_due_within_horizon():
    # expiry must sit after job end (else during-job error rightly fires first)
    sub = on_sub(clearance=Clearance(issuer="WSIB", issued=D("2026-01-20"), expires=D("2026-03-10")))
    job = on_job([sub], end="2026-03-05")
    found = codes(audit(job, on=D("2026-02-15"), horizon=30))
    assert "renewal_due" in found
    assert "clearance_expired" not in found and "clearance_expires_during_job" not in found


def test_alberta_letter_covers_only_up_to_its_date():
    sub = on_sub(province="AB",
                 clearance=Clearance(issuer="WCB-AB", number="L-9", issued=D("2026-01-05"),
                                     covered_until=D("2026-03-05")))
    job = on_job([sub], start="2026-01-10", end="2026-06-01", province="AB")
    found = codes(audit(job, on=D("2026-02-15")))
    assert "clearance_cover_lapsed" in found


def test_alberta_letter_current_passes():
    sub = on_sub(province="AB",
                 clearance=Clearance(issuer="WCB-AB", issued=D("2026-03-01"), covered_until=D("2026-12-31")))
    job = on_job([sub], start="2026-01-10", end="2026-06-01", province="AB")
    assert audit(job, on=D("2026-02-15")) == []


def test_issuer_mismatch_warns():
    sub = on_sub(clearance=Clearance(issuer="WCB-AB", issued=D("2026-01-05"), covered_until=D("2026-12-31")))
    found = codes(audit(on_job([sub], province="ON"), on=D("2026-02-15")))
    assert "issuer_mismatch" in found


def test_licence_expired_and_due():
    sub = on_sub(licences=[Licence(name="309A electrical", expires=D("2025-12-01")),
                           Licence(name="Fall protection", expires=D("2026-03-14"))])
    job = on_job([sub], end="2026-03-10")  # due licence outlives the job, lands in the horizon
    found = codes(audit(job, on=D("2026-02-15")))
    assert "licence_expired" in found and "licence_renewal_due" in found


def test_ongoing_job_uses_audit_date():
    sub = on_sub(clearance=Clearance(issuer="WSIB", issued=D("2026-01-20"), expires=D("2026-03-15")))
    job = on_job([sub], end=None)  # ongoing
    found = codes(audit(job, on=D("2026-04-01")))
    assert "clearance_expired" in found


def test_insurance_during_job_is_warning():
    sub = on_sub(insurance=Insurance(provider="Aviva", expires=D("2026-03-10")))
    findings = audit(on_job([sub]), on=D("2026-02-15"))
    f = next(x for x in findings if x.code == "insurance_expires_during_job")
    assert f.severity == "warn"


def test_renewals_filter():
    jobs = [
        on_job([on_sub(clearance=Clearance(issuer="WSIB", issued=D("2026-01-20"), expires=D("2026-03-10")))],
               end="2026-03-05"),  # renewal due within 30 days of 02-15
        on_job([on_sub()], name="Job B"),  # nothing due
    ]
    due = renewals(jobs, within=30, on=D("2026-02-15"))
    assert all("due" in f.code or "lapsed" in f.code for f in due)
    assert len(due) == 1
