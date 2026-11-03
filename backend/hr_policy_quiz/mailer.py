# backend/hr_policy_quiz/mailer.py
"""
Onboarding-quiz invitation mail.

When HR adds new joiners ("Add and generate password") each one gets an e-mail with the link to the quiz
login, their login e-mail and password, and the "one attempt only" note. It goes out through Microsoft Graph,
using the same app registration as the other JHS mails (see backend/buddy_referral/notify.py). Environment:

  MS_MAIL_TENANT_ID, MS_MAIL_CLIENT_ID, MS_MAIL_CLIENT_SECRET   the Azure app (needs the Mail.Send application permission)
  MS_MAIL_SENDER     the mailbox the mail is sent from (falls back to OUTLOOK_EMAIL)
  QUIZ_LOGIN_URL   optional, defaults to https://jhstimesnap.in/hr-quiz/candidate-login

One mail per candidate (nobody sees anybody else's address). A mail that cannot be sent never stops the
candidate from being created: the result says who got it and who did not, so HR can share the password by hand.
"""
import html
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from backend.buddy_referral import notify

log = logging.getLogger("hr_quiz.mailer")

DEFAULT_LOGIN_URL = "https://jhstimesnap.in/hr-quiz/candidate-login"
SUBJECT = "Onboarding Quiz — JHS Associates"
SUBJECT_RESET = "Your new password — Onboarding Quiz, JHS Associates"


def _settings() -> dict:
    return {
        "tenant": (os.getenv("MS_MAIL_TENANT_ID") or os.getenv("GRAPH_TENANT_ID", "")).strip(),
        "client_id": (os.getenv("MS_MAIL_CLIENT_ID") or os.getenv("GRAPH_CLIENT_ID", "")).strip(),
        "secret": (os.getenv("MS_MAIL_CLIENT_SECRET") or os.getenv("GRAPH_CLIENT_SECRET", "")).strip(),
        "sender": (os.getenv("MS_MAIL_SENDER") or os.getenv("GRAPH_SENDER", "")).strip() or os.getenv("OUTLOOK_EMAIL", "").strip(),
        "url": os.getenv("QUIZ_LOGIN_URL", "").strip() or DEFAULT_LOGIN_URL,
    }


def is_configured() -> bool:
    s = _settings()
    return all(s[k] for k in ("tenant", "client_id", "secret", "sender"))


FONT = "Segoe UI,Arial,sans-serif"
HTML_OPEN = ('<!DOCTYPE html>\n<html xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">'
             '<head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>')


def header_html(title: str) -> str:
    """Coloured title bar. bgcolor (not a CSS gradient) so Outlook shows it too."""
    return (f'<tr><td bgcolor="#667eea" style="background-color:#667eea;padding:22px 28px;font-family:{FONT};'
            f'font-size:20px;font-weight:700;color:#ffffff;"><span style="color:#ffffff;">{html.escape(title)}</span></td></tr>')


def button_html(url: str, label: str) -> str:
    """A real button in every mail client. Outlook (desktop) ignores padding / rounded corners on a link, so it
    gets a VML rounded rectangle; everybody else gets a coloured table cell with the link inside."""
    u, text = html.escape(url, quote=True), html.escape(label)
    width = max(220, 9 * len(label) + 56)
    return (
        '<!--[if mso]>'
        f'<v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="{u}" '
        f'style="height:46px;v-text-anchor:middle;width:{width}px;" arcsize="18%" stroke="f" fillcolor="#667eea">'
        f'<w:anchorlock/><center style="color:#ffffff;font-family:{FONT};font-size:15px;font-weight:bold;">{text}</center>'
        '</v:roundrect><![endif]-->'
        '<!--[if !mso]><!-->'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td bgcolor="#667eea" align="center" style="background-color:#667eea;border-radius:8px;">'
        f'<a href="{u}" target="_blank" style="display:inline-block;padding:13px 26px;font-family:{FONT};font-size:15px;'
        f'font-weight:bold;color:#ffffff;text-decoration:none;border-radius:8px;">{text}</a></td></tr></table>'
        '<!--<![endif]-->'
    )


def build_html(email: str, password: str, url: str = DEFAULT_LOGIN_URL, reset: bool = False) -> str:
    e, p, u = html.escape(email), html.escape(password), html.escape(url, quote=True)
    intro = ("HR has generated a <strong>new password</strong> for you. <strong>Your old password no longer works</strong>; please use the one below."
             if reset else "<strong>Please take the quiz as part of your onboarding process.</strong>")
    return f"""{HTML_OPEN}
<body bgcolor="#f3f4f8" style="margin:0;padding:0;background:#f3f4f8;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f8;padding:24px 0;">
 <tr><td align="center">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;font-family:Segoe UI,Arial,sans-serif;color:#2c3e50;">
   {header_html("Onboarding Quiz")}
   <tr><td style="padding:26px 28px 8px 28px;font-size:15px;line-height:1.6;">
     <p style="margin:0 0 14px 0;">Hello,</p>
     <p style="margin:0 0 14px 0;">{intro}</p>
     <p style="margin:0 0 18px 0;">Click on the link below and start taking the onboarding quiz:</p>
     <div style="margin:0 0 22px 0;">{button_html(url, "Start the onboarding quiz")}</div>
     <p style="margin:0 0 6px 0;font-size:13px;color:#6b7280;">If the button does not open, copy this link into your browser:<br><a href="{u}" style="color:#667eea;word-break:break-all;">{u}</a></p>
   </td></tr>
   <tr><td style="padding:10px 28px 4px 28px;">
     <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f8f9fc;border:1px solid #e1e8ed;border-radius:10px;font-size:14px;">
       <tr><td style="padding:14px 18px;"><div style="font-size:12px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;color:#6b7280;margin-bottom:8px;">Your login details</div>
         <div style="margin-bottom:4px;">Email: <strong>{e}</strong></div>
         <div>Password: <strong style="font-family:Consolas,monospace;font-size:15px;letter-spacing:.5px;">{p}</strong></div></td></tr>
     </table>
   </td></tr>
   <tr><td style="padding:18px 28px 6px 28px;">
     <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff8e1;border:1px solid #ffe08a;border-radius:10px;font-size:14px;line-height:1.55;color:#7a5b00;">
       <tr><td style="padding:12px 18px;"><strong>Please note:</strong> you can take this quiz <strong>only once</strong>. If it has been submitted, you can retake it only with HR approval.</td></tr>
     </table>
   </td></tr>
   <tr><td style="padding:18px 28px 26px 28px;font-size:14px;color:#2c3e50;">Regards,<br>HR Team, JHS Associates</td></tr>
  </table>
 </td></tr>
</table>
</body></html>"""


def send_batch(items) -> dict:
    """items: [(email, subject, html), ...]  ->  {"configured": bool, "sent": [emails], "failed": [emails], "error": str}
    One Microsoft Graph mail per item, a few at a time. Shared by every module that mails new joiners."""
    items = list(items)
    result = {"configured": is_configured(), "sent": [], "failed": [], "error": ""}
    if not items:
        return result
    if not result["configured"]:
        result["failed"] = [e for e, _, _ in items]
        result["error"] = "Microsoft Graph is not set up on the server (MS_MAIL_TENANT_ID, MS_MAIL_CLIENT_ID, MS_MAIL_CLIENT_SECRET, MS_MAIL_SENDER)."
        log.warning("mails not sent: Graph settings are missing")
        return result
    s = _settings()
    try:
        notify._graph_access_token(s["tenant"], s["client_id"], s["secret"])   # one token up front: a bad secret fails once, clearly
    except Exception as exc:
        result["failed"] = [e for e, _, _ in items]
        result["error"] = f"Microsoft Graph sign-in failed: {str(exc)[:200]}"
        log.warning("mails not sent: %s", result["error"])
        return result

    def one(item):
        email, subject, body = item
        return email, notify._send_graph(s["tenant"], s["client_id"], s["secret"], s["sender"], [email], subject, body)

    with ThreadPoolExecutor(max_workers=5) as pool:
        for email, ok in pool.map(one, items):
            (result["sent"] if ok else result["failed"]).append(email)
    if result["failed"]:
        result["error"] = "Microsoft Graph refused some mails (check the app has Mail.Send permission and the sender is a real mailbox)."
    return result


def send_invites(items, reset: bool = False) -> dict:
    """Quiz invitations (or, with reset=True, "your new password" mails). items: [(email, password), ...]"""
    url = _settings()["url"]
    return send_batch([(e, SUBJECT_RESET if reset else SUBJECT, build_html(e, p, url, reset)) for e, p in items])
