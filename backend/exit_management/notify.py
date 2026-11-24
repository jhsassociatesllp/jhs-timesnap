# backend/exit_management/notify.py
"""E-mail notifications for the exit workflow, sent through Microsoft Graph (the app registration in .env).

    Employee submits the Exit Form        -> mail to the employee's Reporting Manager
    Reporting Manager submits Project Details -> mail to the IT representatives
    IT representative submits IT Clearance    -> mail to the HR representatives
    HR representative submits HR Clearance    -> mail to the employee: "your exit process is completed"

Settings (environment / .env):
    TENANT_AP, CLIENT_AP, CLIENT_SECRET_AP   Azure app registration (client-credentials, "Mail.Send" application permission)
    SENDER_AP                                the mailbox the mail is sent from
    EXIT_MAIL_LOGIN_URL                      optional; the login link put in every mail (default https://jhstimesnap.in/)
    EXIT_MAIL_DISABLED=1                     optional switch: do everything except actually sending (used by tests / local runs)

Everything here is best-effort and runs as a background task AFTER the form was saved: a missing setting, a missing e-mail address or a mail outage
is logged (never the secret) and never affects the submission. Each recipient gets their own message.
"""
import html
import logging
import os
import re
import time

import requests
from bson import ObjectId
from bson.errors import InvalidId

from backend.exit_management import approvals
from backend.exit_management import repository as repo

log = logging.getLogger("exit_management.notify")

LOGIN_URL = "https://jhstimesnap.in/"
_EMAIL = re.compile(r"^[^@\s;,]+@[^@\s;,]+\.[A-Za-z]{2,}$")
_token = {"value": None, "expires": 0.0}
_warned = {"missing": False}


# ── settings / sending ───────────────────────────────────────────────────────
def _setting(name: str) -> str:
    return (os.getenv(name) or "").strip()


def enabled() -> bool:
    if _setting("EXIT_MAIL_DISABLED").lower() in ("1", "true", "yes"):
        return False
    return all(_setting(k) for k in ("TENANT_AP", "CLIENT_AP", "CLIENT_SECRET_AP", "SENDER_AP"))


def _access_token() -> str:
    """App-only Graph token (cached until shortly before it expires)."""
    if _token["value"] and time.time() < _token["expires"] - 60:
        return _token["value"]
    r = requests.post(
        f"https://login.microsoftonline.com/{_setting('TENANT_AP')}/oauth2/v2.0/token",
        data={"client_id": _setting("CLIENT_AP"), "client_secret": _setting("CLIENT_SECRET_AP"),
              "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"}, timeout=15)
    r.raise_for_status()
    data = r.json()
    _token["value"], _token["expires"] = data["access_token"], time.time() + int(data.get("expires_in", 3000))
    return _token["value"]


def _send_graph(to: str, subject: str, body_html: str) -> None:
    r = requests.post(
        f"https://graph.microsoft.com/v1.0/users/{_setting('SENDER_AP')}/sendMail",
        headers={"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json"},
        json={"message": {"subject": subject, "body": {"contentType": "HTML", "content": body_html},
                          "toRecipients": [{"emailAddress": {"address": to}}]}, "saveToSentItems": True}, timeout=20)
    if r.status_code not in (200, 202):
        raise RuntimeError(f"Graph sendMail answered {r.status_code}: {r.text[:200]}")


def _deliver(to: str, subject: str, body_html: str) -> bool:
    """Send one message; never raises."""
    if not enabled():
        missing = [k for k in ("TENANT_AP", "CLIENT_AP", "CLIENT_SECRET_AP", "SENDER_AP") if not _setting(k)]
        if missing and not _warned["missing"]:                     # say it loudly ONCE in the server log (names only, never values)
            _warned["missing"] = True
            log.warning("exit mail is NOT being sent: these settings are empty in this environment: %s "
                        "(they must be passed to the container, e.g. -e NAME=... in the deploy workflow)", ", ".join(missing))
        log.info("exit mail not sent to %s (%s): mail is disabled or not configured", to, subject)
        return False
    try:
        _send_graph(to, subject, body_html)
        log.info("exit mail sent to %s: %s", to, subject)
        return True
    except Exception as exc:                                       # network / Graph / auth: log it, never break the workflow
        log.warning("exit mail to %s failed: %s", to, str(exc)[:300])
        return False


# ── who gets what ────────────────────────────────────────────────────────────
def _name(emp: dict, fallback: str = "") -> str:
    return (emp or {}).get("Emp Name") or (emp or {}).get("EmployeeName") or (emp or {}).get("Name") or fallback


def _address(code: str):
    """(name, OFFICIAL e-mail address) of an employee: the `EMail` field of Employee_details. The personal address
    (`Personal EMail`) is never used; without a valid official address the person is simply skipped."""
    emp = repo.find_employee(code) or {}
    value = str(emp.get("EMail") or "").strip()
    return _name(emp, code), (value if _EMAIL.match(value) else None)


def _load(form_id):
    try:
        return repo.collection.find_one({"_id": ObjectId(str(form_id))})
    except (InvalidId, TypeError):
        return None


def _send_to_codes(codes, subject_fn, body_fn):
    """One message per recipient: subject_fn(name) / body_fn(name)."""
    sent = 0
    for code in sorted({c for c in codes if c}):
        name, address = _address(code)
        if not address:
            log.warning("exit mail: no e-mail address on record for %s", code)
            continue
        sent += 1 if _deliver(address, subject_fn(name), body_fn(name)) else 0
    return sent


# ── the message ──────────────────────────────────────────────────────────────
def _link() -> str:
    return _setting("EXIT_MAIL_LOGIN_URL") or LOGIN_URL


def _page(heading: str, greeting: str, paragraphs, facts, button=True) -> str:
    e = html.escape
    rows = "".join(f'<tr><td style="padding:6px 14px 6px 0;color:#7f8c8d;font-size:13px">{e(k)}</td>'
                   f'<td style="padding:6px 0;font-size:14px;font-weight:600;color:#2c3e50">{e(str(v))}</td></tr>' for k, v in facts if v)
    body = "".join(f'<p style="margin:0 0 12px;font-size:14px;line-height:1.55;color:#34495e">{e(p)}</p>' for p in paragraphs)
    link = _link()
    body += (f'<p style="margin:0 0 12px;font-size:14px;line-height:1.55;color:#34495e">Please log in to JHS Timesnap at '
             f'<a href="{e(link)}" style="color:#667eea;font-weight:600">{e(link)}</a> and open the Employee Exit Management module.</p>')
    btn = (f'<p style="margin:18px 0 4px"><a href="{e(link)}" style="background:#667eea;color:#fff;text-decoration:none;padding:11px 22px;'
           f'border-radius:8px;font-weight:600;font-size:14px">Log in to JHS Timesnap</a></p>') if button else ""
    return ('<div style="background:#f4f6fa;padding:24px;font-family:Segoe UI,Arial,sans-serif">'
            '<div style="max-width:560px;margin:auto;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #e1e8ed">'
            f'<div style="background:#2c3e50;color:#fff;padding:16px 22px;font-size:17px;font-weight:700">{e(heading)}</div>'
            f'<div style="padding:22px"><p style="margin:0 0 14px;font-size:14px;color:#34495e">{e(greeting)}</p>{body}'
            f'<table style="border-collapse:collapse;margin:6px 0 4px">{rows}</table>{btn}'
            '<p style="margin:20px 0 0;font-size:12px;color:#95a5a6">This is an automated message from JHS Timesnap - Employee Exit Management.</p>'
            '</div></div></div>')


def _facts(doc: dict):
    det = doc.get("employee_details") or {}
    return [("Employee", f"{doc.get('employee_name')} ({doc.get('employee_id')})"), ("Designation", det.get("designation")),
            ("Resignation date", det.get("resignation_date")), ("Last working date", det.get("last_working_date"))]


# ── the four events (each is called as a background task after the save succeeded) ──
def exit_submitted(form_id) -> int:
    """1) The employee submitted the Exit Form -> their Reporting Manager(s)."""
    try:
        doc = _load(form_id)
        if not doc:
            return 0
        codes = {approvals.manager_code_for(doc)} | set(approvals.junior_managers(doc["employee_id"]))
        codes.discard(doc["employee_id"])
        if not any(codes):                                         # no manager on record: the HR approvers handle it
            codes = set(approvals.hr_managers()) - {doc["employee_id"]}
        who = f"{doc.get('employee_name')} ({doc.get('employee_id')})"
        return _send_to_codes(codes, lambda n: f"Exit form submitted by {who} - your review is needed",
                              lambda n: _page("Employee Exit Form submitted", f"Dear {n},",
                                              [f"{doc.get('employee_name')} has submitted their Employee Exit Form. Please review it and complete the Project Details (handover) form."],
                                              _facts(doc)))
    except Exception:
        log.exception("exit mail (exit_submitted) failed")
        return 0


def handover_submitted(form_id) -> int:
    """2) The Reporting Manager submitted Project Details -> the IT representatives."""
    try:
        doc = _load(form_id)
        if not doc:
            return 0
        codes = set(approvals.it_managers()) - {doc["employee_id"]}
        who = f"{doc.get('employee_name')} ({doc.get('employee_id')})"
        rm = ((doc.get("approval") or {}).get("reporting_manager") or {}).get("approver_name") or "the Reporting Manager"
        return _send_to_codes(codes, lambda n: f"IT Clearance needed for {who}",
                              lambda n: _page("IT Clearance is waiting for you", f"Dear {n},",
                                              [f"{rm} has completed the Project Details (handover) form for {doc.get('employee_name')}. The IT Clearance is now pending with IT."],
                                              _facts(doc)))
    except Exception:
        log.exception("exit mail (handover_submitted) failed")
        return 0


def it_submitted(form_id) -> int:
    """3) The IT representative submitted IT Clearance -> the HR representatives."""
    try:
        doc = _load(form_id)
        if not doc:
            return 0
        codes = set(approvals.hr_managers()) - {doc["employee_id"]}
        who = f"{doc.get('employee_name')} ({doc.get('employee_id')})"
        it = ((doc.get("approval") or {}).get("it") or {}).get("approver_name") or "IT"
        return _send_to_codes(codes, lambda n: f"HR Clearance needed for {who}",
                              lambda n: _page("HR Clearance is waiting for you", f"Dear {n},",
                                              [f"{it} has completed the IT Clearance for {doc.get('employee_name')}. The HR Clearance is now pending with HR."],
                                              _facts(doc)))
    except Exception:
        log.exception("exit mail (it_submitted) failed")
        return 0


def exit_completed(form_id) -> int:
    """4) The HR representative submitted HR Clearance -> the employee: the exit process is completed."""
    try:
        doc = _load(form_id)
        if not doc:
            return 0
        return _send_to_codes({doc["employee_id"]}, lambda n: "Your exit process is completed",
                              lambda n: _page("Your exit process is completed", f"Dear {n},",
                                              ["All approvals of your exit are complete: Reporting Manager, IT Clearance and HR Clearance.",
                                               "You can follow the status and download your Exit Form as a PDF from the Exit Status Tracker."],
                                              [("Employee", f"{doc.get('employee_name')} ({doc.get('employee_id')})"),
                                               ("Last working date", (doc.get("employee_details") or {}).get("last_working_date"))]))
    except Exception:
        log.exception("exit mail (exit_completed) failed")
        return 0
