from datetime import date, datetime

import pytest

from backend import mailer
from backend.cycle import digest
from backend.jobs import scheduler
from tests.cycle.conftest import DAY, entry

D = date.fromisoformat(DAY)


@pytest.fixture
def mail(monkeypatch):
    """Mail enabled, transport stubbed: records every message instead of sending."""
    sent = []
    monkeypatch.setenv("TIMESNAP_SEND_MAIL", "1")
    monkeypatch.setattr(mailer, "send_mail", lambda to, subject, text, body: (sent.append((to, subject, text, body)) or ("sent", "")))
    return sent


def seed(cdb):
    cdb["c_submissions"].insert_one({"employee_id": "JHS9101", "date": DAY, "submitted_at": datetime.utcnow()})
    cdb["c_entries"].insert_many([
        entry("JHS9101", DAY, 8, "done"),
        entry("JHS9101", DAY, 1, "blocked", activity="Waiting for client <b>data</b>"),
        entry("JHS9102", DAY, 4, "in_progress", is_unplanned=True, task_id=None,
              activity="Fix printer", unplanned_reason="<script>alert(1)</script>"),
        entry("JHS9103", DAY, 8, "done"),
        entry("JHS9104", DAY, 8, "done")])                                      # not a pilot employee
    cdb["c_uploads"].insert_one({"status": "done", "uploaded_at": datetime.utcnow(),
                                 "date_from": "2026-10-12", "date_to": "2026-10-14"})
    cdb["c_reco"].insert_many([
        {"employee_id": "JHS9102", "date": "2026-10-12", "result": "short", "diff": -2.0, "status": "open", "reason": ""},
        {"employee_id": "JHS9102", "date": "2026-10-13", "result": "over", "diff": 1.5, "status": "accepted"},  # reviewed
        {"employee_id": "JHS9102", "date": "2026-10-01", "result": "short", "diff": -1.0, "status": "open"},    # older upload
        {"employee_id": "JHS9104", "date": "2026-10-12", "result": "short", "diff": -1.0, "status": "open"}])   # not pilot


def test_one_email_per_manager_with_correct_content(cdb, mail):
    seed(cdb)
    results = digest.send_digests(D)
    assert sorted((r["manager"], r["status"]) for r in results) == [("JHS9001", "sent"), ("JHS9002", "sent")]
    assert len(mail) == 2                                                       # NOT one per employee
    to, subject, text, body = next(m for m in mail if m[0] == ["mgr.a@example.invalid"])
    assert "1/2 submitted" in subject                                           # JHS9104 (non-pilot) excluded
    assert "Emp One" in body and "Emp Two" in body and "Not Pilot" not in body
    assert "Fix printer" in body and "short" in body and "2026-10-12" in body
    assert "2026-10-13" not in body and "2026-10-01" not in body                # accepted row / older upload not listed
    assert "Emp Two" in text.split("Not submitted")[1]                          # Emp Two has not submitted


def test_dynamic_text_is_html_escaped(cdb, mail):
    seed(cdb)
    digest.send_digests(D)
    body = next(m for m in mail if m[0] == ["mgr.a@example.invalid"])[3]
    assert "<script>" not in body and "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "<b>data</b>" not in body and "&lt;b&gt;data&lt;/b&gt;" in body


def test_second_run_same_day_sends_nothing(cdb, mail):
    seed(cdb)
    digest.send_digests(D)
    again = digest.send_digests(D)
    assert [r["status"] for r in again] == ["duplicate", "duplicate"] and len(mail) == 2
    rows = list(cdb["c_email_log"].find({"kind": "digest"}))
    assert len(rows) == 2 and all(r["status"] == "sent" for r in rows)
    assert all("body" not in r and "html" not in r for r in rows)               # bodies are never stored


def test_failed_send_is_retried_then_not_repeated(cdb, monkeypatch):
    seed(cdb)
    monkeypatch.setenv("TIMESNAP_SEND_MAIL", "1")
    outcomes = iter([("failed", "smtp down"), ("sent", ""), ("sent", "")])
    calls = []
    monkeypatch.setattr(mailer, "send_mail", lambda *a: (calls.append(a[0]) or next(outcomes)))
    first = digest.send_digests(D)
    assert sorted(r["status"] for r in first) == ["failed", "sent"]
    second = digest.send_digests(D)
    assert sorted(r["status"] for r in second) == ["duplicate", "sent"]         # only the failed one is retried
    assert len(calls) == 3
    assert digest.send_digests(D) and len(calls) == 3


def test_mail_is_off_unless_explicitly_enabled(cdb, monkeypatch):
    seed(cdb)
    monkeypatch.delenv("TIMESNAP_SEND_MAIL", raising=False)
    monkeypatch.setattr(mailer, "send_mail", lambda *a: pytest.fail("must not be called"))
    results = digest.send_digests(D)
    # real transport is never reached; status shows it was not sent
    assert {r["status"] for r in results} == {"disabled"}
    assert cdb["c_email_log"].count_documents({"status": "disabled"}) == 2
    # a later real run is NOT blocked by the disabled rows
    monkeypatch.setenv("TIMESNAP_SEND_MAIL", "1")
    sent = []
    monkeypatch.setattr(mailer, "send_mail", lambda *a: (sent.append(1) or ("sent", "")))
    assert {r["status"] for r in digest.send_digests(D)} == {"sent"} and len(sent) == 2


def test_dry_run_writes_html_files_and_sends_nothing(cdb, mail, tmp_path):
    seed(cdb)
    results = digest.send_digests(D, dry_run_dir=str(tmp_path))
    assert {r["status"] for r in results} == {"dry_run"} and not mail
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == [f"digest_JHS9001_{DAY}.html", f"digest_JHS9002_{DAY}.html"]
    assert "Emp One" in (tmp_path / files[0]).read_text(encoding="utf-8")
    assert cdb["c_email_log"].count_documents({}) == 0


def test_weekend_and_holiday_are_skipped(cdb, mail):
    seed(cdb)
    assert digest.send_digests(date(2026, 10, 17)) == [{"skipped": "not a working day"}]     # Saturday
    assert digest.send_digests(date(2026, 10, 2)) == [{"skipped": "not a working day"}]      # holiday in config
    assert not mail


def test_manager_without_email_is_logged_not_crashed(cdb, mail):
    seed(cdb)
    cdb["c_employees"].update_one({"EmpID": "JHS9002"}, {"$set": {"EMail": "not-an-email"}})
    res = {r["manager"]: r["status"] for r in digest.send_digests(D)}
    assert res == {"JHS9001": "sent", "JHS9002": "no_email"}
    assert cdb["c_email_log"].find_one({"manager_id": "JHS9002"})["status"] == "failed"


def test_no_pilot_reportees_no_mail(cdb, mail):
    cdb["c_config"].update_one({"_id": "timesheet"}, {"$set": {"pilot_employees": []}})
    assert digest.send_digests(D) == [] and not mail


# ── scheduler ────────────────────────────────────────────────────────────────

def at(h, m=0, day=DAY):
    return scheduler.IST.localize(datetime.fromisoformat(f"{day}T{h:02d}:{m:02d}:00"))


def test_scheduler_runs_once_after_20_00_ist(cdb, mail):
    seed(cdb)
    assert scheduler.run_due_jobs(at(19, 59)) is None and not mail              # too early
    first = scheduler.run_due_jobs(at(20, 0))
    assert first and len(mail) == 2
    assert scheduler.run_due_jobs(at(20, 1)) is None and scheduler.run_due_jobs(at(23, 30)) is None
    assert len(mail) == 2 and cdb["c_job_runs"].find_one({"job": "digest"})["status"] == "done"


def test_two_scheduler_processes_cannot_both_run_the_job(cdb, mail):
    seed(cdb)
    assert scheduler.claim_run("digest", D) is True
    assert scheduler.claim_run("digest", D) is False


def test_failed_job_is_retried_on_the_next_tick(cdb, mail):
    seed(cdb)
    def boom(day):
        raise RuntimeError("db hiccup")
    with pytest.raises(RuntimeError):
        scheduler.run_due_jobs(at(20, 0), digest_fn=boom)
    assert cdb["c_job_runs"].find_one({"job": "digest"})["status"] == "failed"
    assert scheduler.run_due_jobs(at(20, 1)) and len(mail) == 2
    assert cdb["c_job_runs"].find_one({"job": "digest"})["status"] == "done"
