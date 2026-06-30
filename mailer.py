"""
Outgoing email — used to send password-reset links.

All connection details come from config.py / the environment (.env), so no
secrets live in code. Uses only the Python standard library (smtplib, ssl,
email), so there is nothing extra to install.

Gmail quick setup (.env):
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=you@gmail.com
    SMTP_PASSWORD=<16-character Google App Password>   # NOT your normal password
    SMTP_FROM=you@gmail.com
"""

import smtplib
import ssl
from email.message import EmailMessage

import config


def is_configured() -> bool:
    """True when enough SMTP settings are present to attempt a send."""
    return bool(config.SMTP_HOST and config.SMTP_FROM)


def send_email(to: str, subject: str, body_text: str, body_html: str = None):
    """Send one email. Raises if SMTP isn't configured or the server rejects it."""
    if not is_configured():
        raise RuntimeError(
            "Email is not configured. Set SMTP_HOST, SMTP_FROM (and for Gmail "
            "SMTP_USER/SMTP_PASSWORD) in your .env file."
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"]    = config.SMTP_FROM
    msg["To"]      = to
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    context = ssl.create_default_context()
    if config.SMTP_USE_SSL:
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=context, timeout=20) as server:
            if config.SMTP_USER:
                server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(msg)
    else:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as server:
            server.starttls(context=context)
            if config.SMTP_USER:
                server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(msg)


def send_password_reset(to: str, reset_url: str, username: str):
    """Send the password-reset email containing the one-time link."""
    ttl = config.RESET_TOKEN_TTL_MIN
    subject = "Reset your Business Scraping Agent password"

    text = (
        f"Hello {username},\n\n"
        f"A password reset was requested for your account. Use the link below to "
        f"choose a new password. It expires in {ttl} minutes.\n\n"
        f"{reset_url}\n\n"
        f"If you didn't request this, you can safely ignore this email — your "
        f"password will stay the same.\n"
    )

    html = f"""\
<div style="font-family:Segoe UI,Arial,sans-serif;color:#1F2937;line-height:1.5;">
  <p>Hello {username},</p>
  <p>A password reset was requested for your account. Click the button below to
     choose a new password. This link expires in {ttl} minutes.</p>
  <p style="margin:22px 0;">
    <a href="{reset_url}"
       style="background:#1A43BF;color:#fff;padding:11px 18px;border-radius:8px;
              text-decoration:none;font-weight:600;display:inline-block;">
      Reset password
    </a>
  </p>
  <p style="font-size:13px;color:#6B7280;">Or paste this link into your browser:<br>
    <a href="{reset_url}" style="color:#1A43BF;">{reset_url}</a></p>
  <p style="font-size:12px;color:#6B7280;">If you didn't request this, you can
     safely ignore this email — your password will stay the same.</p>
</div>"""

    send_email(to, subject, text, html)
