# backend/cycle/digest.py
"""
Manager evening digest: ONE email per manager per day (20:00 IST), covering the manager's
PILOT reportees. Also the email_log claim helper shared with the reminder mails.

  build_digest(manager, day)  -> data dict (or None when there is nothing to send)
  render_digest(data)         -> (subject, text, html)   every dynamic value is HTML-escaped
  send_digests(day, dry_run_dir=None) -> per-manager outcomes (idempotent via email_log)
"""
import html
import logging
import os
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from pymongo.errors import DuplicateKeyError

from backend import mailer
from backend.cycle.store import holidays_set, pilot_set, store

log = logging.getLogger("digest")
MAX_LIST = 30


# ───────────────────────────── email_log claim ───────────────────────────────

def ensure_indexes() -> None:
    store.email_log.create_index([("key", 1)], unique=True,
                                 partialFilterExpression={"key": {"$type": "string"}})
    store.job_runs.create_index([("job", 1), ("date", 1)], unique=True)


def claim(key: str, doc: dict) -> bool:
    """Reserve a send. False if that exact mail was already sent/is being sent
    (a previous 'failed' attempt may be retried)."""
    base = {**doc, "key": key, "status": "sending", "created_at": datetime.utcnow()}
    try:
        store.email_log.insert_one(base)
        return True
    except DuplicateKeyError:
        res = store.email_log.update_one({"key": key, "status": "failed"},
                                         {"$set": {"status": "sending", "retried_at": datetime.utcnow()}})
        return res.modified_count == 1


def record(key: Optional[str], doc: dict, status: str, error: str = "") -> None:
    """Finish a claimed send, or log a mail that was not attempted (no key -> never blocks a later send)."""
    if key:
        store.email_log.update_one({"key": key}, {"$set": {"status": status, "error": error,
                                                          "sent_at": datetime.utcnow()}})
    else:
        store.email_log.insert_one({**doc, "status": status, "error": error, "created_at": datetime.utcnow()})


def deliver(key: str, doc: dict, to: List[str], subject: str, text: str, body: str) -> str:
    """Claim -> send -> log. Returns 'sent' | 'failed' | 'disabled' | 'duplicate'."""
    if not mailer.enabled():
        record(None, {**doc, "to": to, "subject": subject}, "disabled", "TIMESNAP_SEND_MAIL is not 1")
        return "disabled"
    if not claim(key, {**doc, "to": to, "subject": subject}):
        return "duplicate"
    status, err = mailer.send_mail(to, subject, text, body)
    record(key, doc, status, err)
    return status


# ───────────────────────────────── build ─────────────────────────────────────

def is_working_day(day: date) -> bool:
    return day.weekday() < 5 and day.isoformat() not in holidays_set()


def managers_with_pilot_reportees() -> Dict[str, List[dict]]:
    pilot = pilot_set()
    out: Dict[str, List[dict]] = {}
    if not pilot:
        return out
    for e in store.employees.find({"EmpID": {"$in": list(pilot)}}):
        mgr = (e.get("ReportingEmpCode") or "").strip().upper()
        if mgr:
            out.setdefault(mgr, []).append(e)
    return out


def build_digest(manager: str, reportees: List[dict], day: date) -> Optional[dict]:
    iso = day.isoformat()
    ids = [r["EmpID"].strip().upper() for r in reportees]
    names = {r["EmpID"].strip().upper(): r.get("Emp Name", "") for r in reportees}
    submitted = {s["employee_id"] for s in store.submissions.find({"employee_id": {"$in": ids}, "date": iso})}
    off = {h["employee_id"] for h in store.hrms.find(
        {"employee_id": {"$in": ids}, "date": iso, "leave_flag": True}, {"employee_id": 1})}
    entries = list(store.entries.find({"employee_id": {"$in": ids}, "date": iso}))

    hours = round(sum(e["hours"] for e in entries if e.get("hours") is not None), 2)
    done = [e for e in entries if e.get("task_status") == "done"]
    blocked = [e for e in entries if e.get("task_status") == "blocked"]
    unplanned = [e for e in entries if e.get("is_unplanned")]

    latest = store.uploads.find_one({"status": {"$ne": "failed"}}, sort=[("uploaded_at", -1)])
    gaps = []
    if latest and latest.get("date_from") and latest.get("date_to"):
        gaps = list(store.reco.find({
            "employee_id": {"$in": ids}, "date": {"$gte": latest["date_from"], "$lte": latest["date_to"]},
            "result": {"$in": ["short", "over", "no_punch", "not_filled"]}, "status": "open",
        }).sort([("date", 1), ("employee_id", 1)]))

    not_submitted = [i for i in ids if i not in submitted and i not in off]
    row = lambda e, extra="": {"employee": names.get(e["employee_id"], e["employee_id"]),
                               "task": e.get("task_name") or e.get("project") or "",
                               "activity": e.get("activity", ""), "extra": extra}
    return {
        "manager": manager, "day": iso, "team_size": len(ids),
        "submitted_count": len(submitted & set(ids)), "hours": hours, "tasks_done": len(done),
        "blocked": [row(e) for e in blocked][:MAX_LIST],
        "unplanned": [row(e, e.get("unplanned_reason", "")) for e in unplanned][:MAX_LIST],
        "reco_gaps": [{"employee": names.get(g["employee_id"], g["employee_id"]), "date": g["date"],
                       "result": g["result"], "diff": g.get("diff"), "reason": g.get("reason", "")}
                      for g in gaps][:MAX_LIST],
        "reco_gap_total": len(gaps),
        "not_submitted": [names.get(i, i) for i in not_submitted],
    }


# ───────────────────────────────── render ────────────────────────────────────

def _e(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def render_digest(d: dict, base_url: str = "") -> Tuple[str, str, str]:
    day = date.fromisoformat(d["day"]).strftime("%a %d %b %Y")
    subject = f"Timesheet digest - {day} ({d['submitted_count']}/{d['team_size']} submitted)"
    lines = [f"Timesheet digest for {day}",
             f"Submitted: {d['submitted_count']} of {d['team_size']}   Hours logged: {d['hours']}   Tasks done: {d['tasks_done']}"]

    def sect(title, items, fmt):
        out = ["", f"{title} ({len(items)})"]
        out += [fmt(i) for i in items] or ["  none"]
        return out

    lines += sect("Blocked", d["blocked"], lambda i: f"  - {i['employee']}: {i['task']} - {i['activity']}")
    lines += sect("Unplanned work", d["unplanned"], lambda i: f"  - {i['employee']}: {i['activity']} (reason: {i['extra']})")
    lines += sect("Hours gaps vs HRMS (latest upload)", d["reco_gaps"],
                  lambda g: f"  - {g['employee']} {g['date']}: {g['result']} {g['diff'] if g['diff'] is not None else ''}")
    lines += sect("Not submitted", d["not_submitted"], lambda n: f"  - {n}")
    text = "\n".join(lines)

    def ul(items, fmt):
        return "<ul>" + "".join(f"<li>{fmt(i)}</li>" for i in items) + "</ul>" if items else "<p style='color:#888'>none</p>"

    link = ""
    if base_url.startswith(("http://", "https://")):
        link = f"<p><a href=\"{_e(base_url.rstrip('/'))}/static/timesheet/reco.html\">Open reconciliation</a></p>"
    body = f"""<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#222">
<h2 style="margin:0 0 8px">Timesheet digest &mdash; {_e(day)}</h2>
<table cellpadding="6" style="border-collapse:collapse"><tr>
<td><b>{_e(d['submitted_count'])}</b> of {_e(d['team_size'])}<br>submitted</td>
<td><b>{_e(d['hours'])}</b><br>hours logged</td><td><b>{_e(d['tasks_done'])}</b><br>tasks done</td></tr></table>
<h3>Blocked ({len(d['blocked'])})</h3>{ul(d['blocked'], lambda i: f"<b>{_e(i['employee'])}</b>: {_e(i['task'])} &ndash; {_e(i['activity'])}")}
<h3>Unplanned work ({len(d['unplanned'])})</h3>{ul(d['unplanned'], lambda i: f"<b>{_e(i['employee'])}</b>: {_e(i['activity'])} <i>(reason: {_e(i['extra'])})</i>")}
<h3>Hours gaps vs HRMS, latest upload ({d['reco_gap_total']})</h3>{ul(d['reco_gaps'], lambda g: f"<b>{_e(g['employee'])}</b> {_e(g['date'])}: {_e(g['result'])} {_e(g['diff'])}")}
<h3>Not submitted ({len(d['not_submitted'])})</h3>{ul(d['not_submitted'], lambda n: _e(n))}
{link}</div>"""
    return subject, text, body


# ───────────────────────────────── send ──────────────────────────────────────

def _manager_email(manager: str) -> str:
    doc = store.employees.find_one({"EmpID": manager}, {"EMail": 1}) or {}
    return (doc.get("EMail") or "").strip()


def send_digests(day: date, dry_run_dir: Optional[str] = None) -> List[dict]:
    """One mail per manager. With dry_run_dir the HTML is written there and NOTHING is sent
    or logged as sent. Re-running the same day never sends twice (email_log key)."""
    results: List[dict] = []
    if not is_working_day(day):
        return [{"skipped": "not a working day"}]
    ensure_indexes()
    base_url = os.getenv("APP_BASE_URL", "").strip()
    for manager, reportees in sorted(managers_with_pilot_reportees().items()):
        data = build_digest(manager, reportees, day)
        subject, text, body = render_digest(data, base_url)
        if dry_run_dir:
            os.makedirs(dry_run_dir, exist_ok=True)
            path = os.path.join(dry_run_dir, f"digest_{manager}_{day.isoformat()}.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
            results.append({"manager": manager, "status": "dry_run", "file": path})
            continue
        to = _manager_email(manager)
        if not mailer.valid_address(to):
            record(None, {"kind": "digest", "manager_id": manager, "date": day.isoformat(), "to": [to]},
                   "failed", "manager has no valid EMail in Employee_details")
            results.append({"manager": manager, "status": "no_email"})
            continue
        status = deliver(f"digest:{manager}:{day.isoformat()}",
                         {"kind": "digest", "manager_id": manager, "date": day.isoformat()},
                         [to], subject, text, body)
        results.append({"manager": manager, "status": status})
    return results
