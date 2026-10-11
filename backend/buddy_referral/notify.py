# backend/buddy_referral/notify.py
"""
Acknowledgement e-mail to HR whenever someone submits a Buddy Referral.

Sent from your Outlook / Microsoft 365 mailbox over SMTP (smtp.office365.com, port
587, STARTTLS). If that is not configured, or Outlook refuses the login, it falls
back to Brevo (the service the forgot-password OTP uses) when BREVO_API_KEY is set.
Everything is best-effort: a missing setting or a mail outage is logged (never the
password) and never stops the referral from being saved - callers run this as a
background task.

Settings (environment variables / .env):
  OUTLOOK_EMAIL       the mailbox the mail is sent FROM          (e.g. you@yourcompany.com)
  OUTLOOK_PASSWORD    its password - or an App Password if the account uses MFA
  OUTLOOK_SMTP_HOST   default smtp.office365.com
  OUTLOOK_SMTP_PORT   default 587
  HR_NOTIFY_EMAIL     who receives the e-mail                    (default: hr@jhsaccoiates.in)
  MAIL_SENDER_NAME    the From name                              (default: JHS Timesnap)
  APP_BASE_URL        e.g. https://timesheet.yourcompany.in - adds an "Open Control Panel" button
  (fallback only) BREVO_API_KEY, MAIL_SENDER_EMAIL = a sender verified in Brevo
"""

import html
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

log = logging.getLogger("buddy_referral.notify")

DEFAULT_HR_EMAIL = "maaz.quraishi@jhsassociates.in"
DEFAULT_SENDER_EMAIL = "osama.khan@jhsassociatesllp.in"      # the sender already verified for the OTP mails
SUBJECT = "Buddy Referral"
_IST = timedelta(hours=5, minutes=30)


def _clean(value: Optional[str], limit: int = 120) -> str:
    """One line, no control characters, bounded length (these values go into a mail)."""
    text = " ".join(str(value or "").split())
    return text[:limit]


def _build(empid: str, name: str, kind: str, detail: str, referred_by: str = "") -> tuple:
    empid, name, detail, referred_by = _clean(empid, 30), _clean(name), _clean(detail), _clean(referred_by)
    who = f"{empid} {name}".strip()
    what = "the position of" if kind == "existing" else "the role of"
    sentence = f"{who} has sent you a referral for {what} {detail}."
    if referred_by:
        sentence = f"{who} has sent you a referral for {what} {detail}, referring {referred_by}."
    when = (datetime.now(timezone.utc) + _IST).strftime("%d %b %Y, %I:%M %p IST")
    base = os.getenv("APP_BASE_URL", "").strip().rstrip("/")
    link = f"{base}/control-panel" if base.startswith(("http://", "https://")) else ""

    text = (
        "Dear HR Team,\n\n"
        f"{sentence}\n\n"
        "Please log in to the Timesheet portal, open the Control Panel and go to Buddy Referral "
        "to review the candidate and their details.\n"
        + (f"\nControl Panel: {link}\n" if link else "")
        + f"\nReceived: {when}\n\nRegards,\nJHS Timesnap\n"
    )

    e = html.escape
    button = (f'<p style="margin:22px 0 6px"><a href="{e(link)}" style="background:#c8102e;color:#ffffff;'
              'text-decoration:none;padding:11px 22px;border-radius:8px;font-weight:600;display:inline-block">'
              'Open Control Panel</a></p>') if link else ""
    rows = [("Employee", f"{empid} &ndash; {e(name)}"), ("Referral for", e(detail))]
    if referred_by:
        rows.append(("Referring", e(referred_by)))
    rows.append(("Received", e(when)))
    table = "".join(
        f'<tr><td style="padding:6px 14px 6px 0;color:#6b6b6b;white-space:nowrap">{k}</td>'
        f'<td style="padding:6px 0;font-weight:600;color:#2b2b2b">{v}</td></tr>' for k, v in rows)
    body = f"""<div style="font-family:Segoe UI,Arial,sans-serif;max-width:560px;margin:auto;color:#2b2b2b">
  <div style="background:#c8102e;color:#ffffff;padding:16px 22px;border-radius:10px 10px 0 0;font-size:18px;font-weight:700">Buddy Referral</div>
  <div style="border:1px solid #eee;border-top:none;padding:22px;border-radius:0 0 10px 10px">
    <p style="margin-top:0">Dear HR Team,</p>
    <p><strong>{e(who)}</strong> has sent you a referral for {what} <strong>{e(detail)}</strong>{(', referring <strong>' + e(referred_by) + '</strong>') if referred_by else ''}.</p>
    <table style="border-collapse:collapse;margin:14px 0;font-size:14px">{table}</table>
    <p>Please log in to the <strong>Timesheet portal &rarr; Control Panel &rarr; Buddy Referral</strong> to review the candidate and their details.</p>
    {button}
    <p style="color:#8a8a8a;font-size:12px;margin-top:22px">This is an automated acknowledgement from JHS Timesnap.</p>
  </div>
</div>"""
    return text, body


def _send_outlook(user: str, password: str, to_email: str, text: str, body: str) -> bool:
    host = os.getenv("OUTLOOK_SMTP_HOST", "smtp.office365.com").strip() or "smtp.office365.com"
    try:
        port = int(os.getenv("OUTLOOK_SMTP_PORT", "587"))
    except ValueError:
        port = 587
    msg = EmailMessage()
    msg["From"] = formataddr((os.getenv("MAIL_SENDER_NAME", "JHS Timesnap"), user))
    msg["To"] = to_email
    msg["Subject"] = SUBJECT
    msg.set_content(text)
    msg.add_alternative(body, subtype="html")
    try:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(user, password)
            smtp.send_message(msg)
        return True
    except smtplib.SMTPAuthenticationError as exc:
        log.warning("Outlook rejected the login for %s (%s). Check the password; accounts with "
                    "two-step verification need an App Password, and 'Authenticated SMTP' must be "
                    "enabled for the mailbox in Microsoft 365.", user, exc.smtp_code)
    except Exception as exc:
        log.warning("Outlook send failed: %s", type(exc).__name__ + ": " + str(exc)[:200])
    return False


def _send_brevo(api_key: str, to_email: str, text: str, body: str) -> bool:
    resp = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        json={
            "sender": {"name": os.getenv("MAIL_SENDER_NAME", "JHS Timesnap"),
                       "email": os.getenv("MAIL_SENDER_EMAIL", DEFAULT_SENDER_EMAIL).strip()},
            "to": [{"email": to_email}],
            "subject": SUBJECT,
            "htmlContent": body,
            "textContent": text,
        },
        headers={"accept": "application/json", "api-key": api_key, "content-type": "application/json"},
        timeout=15,
    )
    if resp.status_code >= 300:
        log.warning("Buddy referral e-mail rejected by Brevo (%s): %s", resp.status_code, resp.text[:200])
        return False
    return True


def send_referral_email(empid: str, name: str, kind: str, detail: str, referred_by: str = "") -> bool:
    """kind = 'referral' (candidate with resume) or 'existing' (existing-employee referral).
    Returns True if a mail service accepted the message. Never raises."""
    try:
        to_email = os.getenv("HR_NOTIFY_EMAIL", "").strip() or DEFAULT_HR_EMAIL
        text, body = _build(empid, name, kind, detail, referred_by)
        user = os.getenv("OUTLOOK_EMAIL", "").strip()
        password = os.getenv("OUTLOOK_PASSWORD", "")
        if user and password:
            if _send_outlook(user, password, to_email, text, body):
                return True
        brevo_key = os.getenv("BREVO_API_KEY", "").strip()
        if brevo_key:
            return _send_brevo(brevo_key, to_email, text, body)
        if not (user and password):
            log.warning("Buddy referral e-mail not sent: set OUTLOOK_EMAIL and OUTLOOK_PASSWORD")
        return False
    except Exception as exc:                      # a mail problem must never affect the referral itself
        log.warning("Buddy referral e-mail failed: %s", exc)
        return False
