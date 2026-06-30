"""
Test the SMTP / email setup independently of the web app.

    python test_email.py [recipient@example.com]

Sends one test email using the settings in your .env. Prints either success or
the exact error so email problems can be diagnosed without going through the
whole forgot-password flow. Defaults to sending to SMTP_FROM (yourself).
"""

import sys

import config
import mailer


def main():
    to = sys.argv[1] if len(sys.argv) > 1 else config.SMTP_FROM
    print("Using settings:")
    print(f"  SMTP_HOST = {config.SMTP_HOST}")
    print(f"  SMTP_PORT = {config.SMTP_PORT}")
    print(f"  SMTP_USER = {config.SMTP_USER}")
    print(f"  SMTP_FROM = {config.SMTP_FROM}")
    print(f"  password set = {bool(config.SMTP_PASSWORD)} (length {len(config.SMTP_PASSWORD or '')})")
    print(f"  sending test message to: {to}")
    print("-" * 50)
    try:
        mailer.send_email(
            to,
            "Test email — Business Scraping Agent",
            "This is a test message. If you received it, your SMTP settings work.",
        )
        print(f"SUCCESS: test email sent to {to}. Check the inbox (and spam folder).")
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
