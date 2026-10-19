# backend/mailer.py
"""
Generic outbound mail for the timesheet jobs (digest, reminders). Reuses the transport
that already works for the buddy-referral mails (Microsoft Graph -> Outlook SMTP -> Brevo),
so no new provider or secrets are introduced.

SAFETY: nothing is sent unless TIMESNAP_SEND_MAIL=1 is set in the environment. A developer
machine (or test run) therefore can never mail real people by accident. Every attempt is
recorded in email_log (never the body) by the callers in backend/cycle/digest.py.
"""
import logging
import os
import re
from typing import List, Tuple

from backend.buddy_referral import notify

log = logging.getLogger("mailer")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def enabled() -> bool:
    return os.getenv("TIMESNAP_SEND_MAIL", "").strip() == "1"


def valid_address(addr: str) -> bool:
    return bool(addr) and len(addr) <= 254 and EMAIL_RE.match(addr.strip()) is not None


def send_mail(recipients: List[str], subject: str, text: str, html_body: str) -> Tuple[str, str]:
    """-> (status, error) with status 'sent' | 'failed' | 'disabled'. Never raises."""
    recipients = [r.strip() for r in recipients if valid_address(r)]
    if not recipients:
        return "failed", "no valid recipient address"
    if not enabled():
        return "disabled", "TIMESNAP_SEND_MAIL is not 1"
    try:
        user = os.getenv("OUTLOOK_EMAIL", "").strip()
        app_password = os.getenv("OUTLOOK_APP_PASSWORD", "").replace(" ", "").strip()
        password = app_password or os.getenv("OUTLOOK_PASSWORD", "")
        tenant = os.getenv("GRAPH_TENANT_ID", "").strip()
        client_id = os.getenv("GRAPH_CLIENT_ID", "").strip()
        secret = os.getenv("GRAPH_CLIENT_SECRET", "").strip()
        graph_sender = os.getenv("GRAPH_SENDER", "").strip() or user
        if tenant and client_id and secret and graph_sender:
            if notify._send_graph(tenant, client_id, secret, graph_sender, recipients, subject, html_body):
                return "sent", ""
        if user and password:
            if notify._send_outlook(user, password, recipients, subject, text, html_body):
                return "sent", ""
        brevo_key = os.getenv("BREVO_API_KEY", "").strip()
        if brevo_key and notify._send_brevo(brevo_key, recipients, subject, text, html_body):
            return "sent", ""
        return "failed", "no mail transport accepted the message"
    except Exception as exc:                                  # a mail problem must never break a job
        log.warning("send_mail failed: %s", str(exc)[:200])
        return "failed", str(exc)[:200]
