"""SMTP e-mail sending.

Failures are logged and swallowed: an e-mail problem must never roll back a
financial operation. In APP_ENV=test nothing is sent; messages are collected in
``OUTBOX`` so tests can assert on them.
"""
import logging
import smtplib
from email.message import EmailMessage
from typing import Dict, List

from app.config import settings

logger = logging.getLogger(__name__)

OUTBOX: List[Dict[str, str]] = []


def send_email(to_address: str, subject: str, body: str) -> bool:
    if settings.is_test:
        OUTBOX.append({"to": to_address, "subject": subject, "body": body})
        return True
    if not settings.smtp_host:
        logger.info("SMTP not configured; e-mail to %s skipped: %s", to_address, subject)
        return False
    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_port in (587, 25):
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
        return True
    except Exception:
        logger.exception("Failed to send e-mail to %s (%s)", to_address, subject)
        return False
