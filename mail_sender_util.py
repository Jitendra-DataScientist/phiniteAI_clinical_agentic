import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_gmail(sender_email, app_password, recipient_email, subject, body):
    try:
        # Create message
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = recipient_email
        msg['Subject'] = subject

        msg.attach(MIMEText(body, 'plain'))

        # Gmail SMTP setup
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()  # Upgrade to secure connection
        server.login(sender_email, app_password)
        server.send_message(msg)
        server.quit()

        print("✅ Email sent successfully.")

    except Exception as e:
        print("❌ Failed to send email:", e)


def send_gmail_html_multi(sender_email, app_password, recipient_list, subject, html_body, max_retries=3):
    """
    Send HTML email to multiple recipients via Gmail SMTP with retry logic.

    Args:
        sender_email: Sender email address
        app_password: Gmail app password
        recipient_list: List of recipient email addresses
        subject: Email subject line
        html_body: HTML content for email body
        max_retries: Number of retry attempts (default: 3)

    Returns:
        bool: True if email sent successfully, False otherwise
    """
    for attempt in range(1, max_retries + 2):  # 1, 2, 3, 4 (default)
        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = sender_email
            msg['To'] = ', '.join(recipient_list)
            msg['Subject'] = subject

            # Attach HTML body
            msg.attach(MIMEText(html_body, 'html'))

            # Gmail SMTP setup
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(sender_email, app_password)
            server.send_message(msg)
            server.quit()

            print(f"✓ Email sent successfully on attempt {attempt}")
            return True

        except Exception as e:
            if attempt < max_retries + 1:
                print(f"✗ Attempt {attempt} failed: {e}. Retrying...")
            else:
                print(f"✗ All {max_retries + 1} attempts failed. Final error: {e}")
                return False

    return False
