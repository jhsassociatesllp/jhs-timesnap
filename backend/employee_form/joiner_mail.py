# backend/employee_form/joiner_mail.py
"""
Login mail for new joiners of the Employee Application Form.

When HR clicks "Generate password" under New Joiner Access, every joiner is e-mailed the link, their login
e-mail and their password (a brand-new login, or a new password when HR regenerates it). Sent through Microsoft
Graph with the same settings as the quiz invitations (see backend/hr_policy_quiz/mailer.py):
MS_MAIL_TENANT_ID, MS_MAIL_CLIENT_ID, MS_MAIL_CLIENT_SECRET, MS_MAIL_SENDER. Optional: EMPLOYEE_FORM_LOGIN_URL
(default https://jhstimesnap.in/login).

A mail that cannot be sent never undoes the login: the result lists who did not get one, so HR can share it by hand.
"""
import html
import os

from backend.hr_policy_quiz import mailer

DEFAULT_URL = "https://jhstimesnap.in/login"
SUBJECT_NEW = "Employee Application Form — JHS Associates"
SUBJECT_RESET = "Your new password — Employee Application Form, JHS Associates"


def build_html(email: str, password: str, reset: bool = False, url: str = DEFAULT_URL) -> str:
    e, p, u = html.escape(email), html.escape(password), html.escape(url, quote=True)
    intro = ("HR has generated a <strong>new password</strong> for you. Your old password no longer works."
             if reset else
             "<strong>Please fill in the Employee Application Form as part of your onboarding process.</strong>")
    return f"""{mailer.HTML_OPEN}
<body bgcolor="#f3f4f8" style="margin:0;padding:0;background:#f3f4f8;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f8;padding:24px 0;">
 <tr><td align="center">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;font-family:Segoe UI,Arial,sans-serif;color:#2c3e50;">
   {mailer.header_html("Employee Application Form")}
   <tr><td style="padding:26px 28px 8px 28px;font-size:15px;line-height:1.6;">
     <p style="margin:0 0 14px 0;">Hello,</p>
     <p style="margin:0 0 14px 0;">{intro}</p>
     <p style="margin:0 0 18px 0;">Click on the link below, sign in with your <strong>personal email</strong> and the password given here, and open the Employee Application Form:</p>
     <div style="margin:0 0 22px 0;">{mailer.button_html(url, "Sign in and fill the form")}</div>
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
       <tr><td style="padding:12px 18px;"><strong>Please note:</strong> you can save a draft and continue later. Once you <strong>submit</strong> the form it is locked; to change anything after that, please contact HR.</td></tr>
     </table>
   </td></tr>
   <tr><td style="padding:18px 28px 26px 28px;font-size:14px;color:#2c3e50;">Regards,<br>HR Team, JHS Associates</td></tr>
  </table>
 </td></tr>
</table>
</body></html>"""


def send_logins(results) -> dict:
    """results: the rows of POST /admin/joiners ({"email", "password", "status": "created" | "reset"})."""
    url = os.getenv("EMPLOYEE_FORM_LOGIN_URL", "").strip() or DEFAULT_URL
    items = []
    for r in results:
        reset = r["status"] == "reset"
        items.append((r["email"], SUBJECT_RESET if reset else SUBJECT_NEW, build_html(r["email"], r["password"], reset, url)))
    return mailer.send_batch(items)
