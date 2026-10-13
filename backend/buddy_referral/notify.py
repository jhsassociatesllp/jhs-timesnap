# backend/buddy_referral/notify.py
"""
Acknowledgement e-mail to HR whenever someone submits a Buddy Referral.

Sent from your Microsoft 365 mailbox. Tried in this order, the first that works wins:
  1. Microsoft Graph (recommended - no mailbox password, works when SMTP password
     sign-in is blocked): needs GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET.
  2. Outlook SMTP (smtp.office365.com, port 587, STARTTLS) with a password / app password.
  3. Brevo (the service the forgot-password OTP uses) when BREVO_API_KEY is set.
Everything is best-effort: a missing setting or a mail outage is logged (never the
password) and never stops the referral from being saved - callers run this as a
background task.

Settings (environment variables / .env):
  GRAPH_TENANT_ID     Directory (tenant) ID of the Azure app registration
  GRAPH_CLIENT_ID     Application (client) ID of that app
  GRAPH_CLIENT_SECRET its client secret VALUE (the app needs the "Mail.Send" application permission)
  GRAPH_SENDER        mailbox the mail is sent from; defaults to OUTLOOK_EMAIL
  OUTLOOK_EMAIL       the mailbox the mail is sent FROM          (e.g. you@yourcompany.com)
  OUTLOOK_PASSWORD    its password
  OUTLOOK_APP_PASSWORD  an App Password (needed when the account uses two-step verification);
                      when set it is used instead of OUTLOOK_PASSWORD. Spaces in it are ignored.
  OUTLOOK_SMTP_HOST   default smtp.office365.com
  OUTLOOK_SMTP_PORT   default 587
  HR_NOTIFY_EMAIL     who receives the e-mail - one address, or several separated by
                      commas or semicolons: a@x.com, b@x.com   (default: DEFAULT_HR_EMAIL below)
  MAIL_SENDER_NAME    the From name                              (default: JHS Timesnap)
  APP_BASE_URL        e.g. https://timesheet.yourcompany.in - adds an "Open Control Panel" button
  (fallback only) BREVO_API_KEY, MAIL_SENDER_EMAIL = a sender verified in Brevo
"""

import html
import logging
import os
import re
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formataddr
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

log = logging.getLogger("buddy_referral.notify")

DEFAULT_HR_EMAIL = "hr@jhsassociates.in, roussel.swaries@jhsassociatesllp.in"     # used when HR_NOTIFY_EMAIL is empty; several allowed, comma separated
DEFAULT_SENDER_EMAIL = "osama.khan@jhsassociatesllp.in"      # the sender already verified for the OTP mails
SUBJECT_PREFIX = "Buddy Referral"
_IST = timedelta(hours=5, minutes=30)


_EMP_CODE = re.compile(r"\bJHS[\s\-_]*\d+\b", re.I)          # JHS1485, JHS 1485, JHS-1485 ...


def _clean(value: Optional[str], limit: int = 120) -> str:
    """One line, no control characters, no employee codes, bounded length (these values go into a mail)."""
    text = " ".join(_EMP_CODE.sub(" ", str(value or "")).split())
    return text.strip(" ,;:-")[:limit]


def _subject(name: str, detail: str) -> str:
    """"Buddy Referral from Osama Khan for Senior Auditor" - employee name and what they referred for."""
    name, detail = _clean(name, 60), _clean(detail, 70)
    parts = [SUBJECT_PREFIX]
    if name:
        parts.append(f"from {name}")
    if detail:
        parts.append(f"for {detail}")
    return " ".join(parts)


def _build(empid: str, name: str, kind: str, detail: str, referred_by: str = "") -> tuple:
    """-> (subject, plain-text body, html body)"""
    subject = _subject(name, detail)
    name, detail, referred_by = _clean(name), _clean(detail), _clean(referred_by)    # employee codes are never put in the e-mail
    who = name or "An employee"
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

    body = _html_body(who, what, detail, referred_by, when, link)
    return subject, text, body


def _html_body(who: str, what: str, detail: str, referred_by: str, when: str, link: str) -> str:
    """HTML e-mail built from nested tables with inline styles and bgcolor attributes. Outlook for
    Windows draws HTML with the Word engine, which ignores div padding, auto margins, max-width and
    rounded corners - tables are the one layout that looks the same everywhere."""
    e = html.escape
    font = "font-family:'Segoe UI',Calibri,Arial,sans-serif;"
    rows = [("Referral for", detail)]
    if referred_by:
        rows.append(("Referring", referred_by))
    rows.append(("Received", when))
    detail_rows = "".join(
        f'<tr><td width="110" valign="top" style="{font}padding:7px 0;font-size:14px;color:#6b7280">{e(k)}</td>'
        f'<td valign="top" style="{font}padding:7px 0;font-size:15px;font-weight:bold;color:#1f2937">{e(v)}</td></tr>'
        for k, v in rows)
    referring = f", referring <b>{e(referred_by)}</b>" if referred_by else ""
    button = (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:6px 0 4px"><tr>'
        f'<td bgcolor="#c8102e" align="center" style="border-radius:6px;padding:13px 28px">'
        f'<a href="{e(link)}" style="{font}font-size:15px;font-weight:bold;color:#ffffff;text-decoration:none;display:inline-block">'
        f'Open Control Panel &rarr;</a></td></tr></table>'
    ) if link else ""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Buddy Referral</title></head>
<body style="margin:0;padding:0;background-color:#f3f4f6">
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;color:#f3f4f6">{e(who)} has referred a candidate for {e(detail)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#f3f4f6"><tr><td align="center" style="padding:28px 12px">
 <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" bgcolor="#ffffff" style="width:600px;max-width:600px;border:1px solid #e5e7eb">
  <tr><td bgcolor="#c8102e" style="padding:26px 32px 24px 32px;{font}color:#ffffff">
    <div style="font-size:12px;letter-spacing:2px;color:#fbd5da;font-weight:bold">NEW REFERRAL</div>
    <div style="font-size:28px;line-height:34px;font-weight:bold;color:#ffffff;padding-top:4px">Buddy Referral</div>
  </td></tr>
  <tr><td style="padding:30px 32px 0 32px;{font}font-size:16px;line-height:24px;color:#1f2937">Dear HR Team,</td></tr>
  <tr><td style="padding:16px 32px 8px 32px;{font}font-size:16px;line-height:25px;color:#1f2937"><b>{e(who)}</b> has sent you a referral for {what} <b>{e(detail)}</b>{referring}.</td></tr>
  <tr><td style="padding:18px 32px 6px 32px">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
      <td width="5" bgcolor="#c8102e" style="font-size:1px;line-height:1px">&nbsp;</td>
      <td bgcolor="#fdf2f4" style="padding:12px 20px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{detail_rows}</table></td>
    </tr></table>
  </td></tr>
  <tr><td style="padding:18px 32px 10px 32px;{font}font-size:15px;line-height:23px;color:#374151">
    Please log in to the <b>Timesheet portal</b> &rarr; <b>Control Panel</b> &rarr; <b>Buddy Referral</b> to review the candidate and their details.
  </td></tr>
  <tr><td style="padding:6px 32px 28px 32px">{button}</td></tr>
  <tr><td bgcolor="#f9fafb" style="padding:16px 32px;border-top:1px solid #e5e7eb;{font}font-size:12px;line-height:18px;color:#9ca3af">
    This is an automated acknowledgement from JHS Timesnap.<br>JHS &amp; Associates LLP
  </td></tr>
 </table>
</td></tr></table>
</body></html>"""


_ADDRESS = re.compile(r"^[A-Za-z0-9._%+'\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
MAX_RECIPIENTS = 20


def _parse_addresses(raw) -> list:
    """Addresses from a string (comma / semicolon / space / new line separated, quotes tolerated)
    or from a list / tuple of strings. Invalid ones are skipped and logged, duplicates removed."""
    if isinstance(raw, (list, tuple, set)):
        raw = ",".join(str(x) for x in raw)
    out, seen = [], set()
    for part in re.split(r"[,;\s]+", str(raw or "")):
        addr = part.strip().strip("<>\"'")
        if not addr:
            continue
        if not _ADDRESS.match(addr):
            log.warning("e-mail recipients: ignoring '%s' (not a valid e-mail address)", addr[:60])
            continue
        if addr.lower() not in seen:
            seen.add(addr.lower())
            out.append(addr)
    return out


def _recipients() -> list:
    """Who gets the mail: HR_NOTIFY_EMAIL (one or several addresses), else the built-in default."""
    return (_parse_addresses(os.getenv("HR_NOTIFY_EMAIL", "")) or _parse_addresses(DEFAULT_HR_EMAIL))[:MAX_RECIPIENTS]


def _send_outlook(user: str, password: str, recipients: list, subject: str, text: str, body: str) -> bool:
    host = os.getenv("OUTLOOK_SMTP_HOST", "smtp.office365.com").strip() or "smtp.office365.com"
    try:
        port = int(os.getenv("OUTLOOK_SMTP_PORT", "587"))
    except ValueError:
        port = 587
    msg = EmailMessage()
    msg["From"] = formataddr((os.getenv("MAIL_SENDER_NAME", "JHS Timesnap"), user))
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
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


_graph_token = {"value": "", "expires": 0.0}


def _graph_access_token(tenant: str, client_id: str, secret: str) -> str:
    """App-only token for Microsoft Graph, cached until shortly before it expires."""
    now = time.time()
    if _graph_token["value"] and now < _graph_token["expires"] - 60:
        return _graph_token["value"]
    resp = requests.post(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data={"client_id": client_id, "client_secret": secret,
              "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"},
        timeout=15,
    )
    if resp.status_code >= 300:
        try:
            err = resp.json()
            detail = f"{err.get('error')}: {str(err.get('error_description', ''))[:160]}"
        except Exception:
            detail = resp.text[:160]
        raise RuntimeError(f"token request failed ({resp.status_code}) {detail}")
    data = resp.json()
    _graph_token["value"] = data["access_token"]
    _graph_token["expires"] = now + int(data.get("expires_in", 3000))
    return _graph_token["value"]


def _send_graph(tenant: str, client_id: str, secret: str, sender: str, recipients: list, subject: str, body: str) -> bool:
    """Send as `sender` through Microsoft Graph (POST /users/{sender}/sendMail)."""
    try:
        token = _graph_access_token(tenant, client_id, secret)
        resp = requests.post(
            f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail",
            json={"message": {"subject": subject,
                              "body": {"contentType": "HTML", "content": body},
                              "toRecipients": [{"emailAddress": {"address": r}} for r in recipients]},
                  "saveToSentItems": True},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=20,
        )
        if resp.status_code in (200, 202):
            return True
        if resp.status_code == 401:
            _graph_token["value"] = ""                       # force a fresh token next time
        try:
            code = (resp.json().get("error") or {}).get("code", "")
        except Exception:
            code = ""
        log.warning("Microsoft Graph refused the mail (%s %s). Check the app has the Mail.Send "
                    "application permission with admin consent, and that %s is a real mailbox.",
                    resp.status_code, code, sender)
    except Exception as exc:
        log.warning("Microsoft Graph send failed: %s", str(exc)[:240])
    return False


def _send_brevo(api_key: str, recipients: list, subject: str, text: str, body: str) -> bool:
    resp = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        json={
            "sender": {"name": os.getenv("MAIL_SENDER_NAME", "JHS Timesnap"),
                       "email": os.getenv("MAIL_SENDER_EMAIL", DEFAULT_SENDER_EMAIL).strip()},
            "to": [{"email": r} for r in recipients],
            "subject": subject,
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
        recipients = _recipients()
        subject, text, body = _build(empid, name, kind, detail, referred_by)
        user = os.getenv("OUTLOOK_EMAIL", "").strip()
        app_password = os.getenv("OUTLOOK_APP_PASSWORD", "").replace(" ", "").strip()   # Microsoft shows it as "abcd efgh ijkl mnop"
        password = app_password or os.getenv("OUTLOOK_PASSWORD", "")
        tenant = os.getenv("GRAPH_TENANT_ID", "").strip()
        client_id = os.getenv("GRAPH_CLIENT_ID", "").strip()
        secret = os.getenv("GRAPH_CLIENT_SECRET", "").strip()
        graph_sender = os.getenv("GRAPH_SENDER", "").strip() or user
        if tenant and client_id and secret and graph_sender:
            if _send_graph(tenant, client_id, secret, graph_sender, recipients, subject, body):
                return True
        if user and password:
            if _send_outlook(user, password, recipients, subject, text, body):
                return True
        brevo_key = os.getenv("BREVO_API_KEY", "").strip()
        if brevo_key:
            return _send_brevo(brevo_key, recipients, subject, text, body)
        if not (user and password):
            log.warning("Buddy referral e-mail not sent: set OUTLOOK_EMAIL and OUTLOOK_APP_PASSWORD (or OUTLOOK_PASSWORD)")
        return False
    except Exception as exc:                      # a mail problem must never affect the referral itself
        log.warning("Buddy referral e-mail failed: %s", exc)
        return False
