import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

sender_email = "talib.syed@jhsonsulting.in"
sender_password = "JHS@786@786@11"   # or app password, NOT raw password ideally
receiver_email = "vasu.gadde@jhsassociates.in"

msg = MIMEMultipart()
msg["From"] = sender_email
msg["To"] = receiver_email
msg["Subject"] = "Test Email - Outlook SMTP"

body = "This is a sample test mail sent using Outlook SMTP."
msg.attach(MIMEText(body, "plain"))

try:
    server = smtplib.SMTP("smtp.office365.com", 587)  
    server.starttls()
    server.login(sender_email, sender_password)
    server.send_message(msg)
    server.quit()
    print("Email sent successfully!")

except Exception as e:
    print("Error:", e)
