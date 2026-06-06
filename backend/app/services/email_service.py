"""SMTP clip emailing (ported from the MVP backend's emailer.py).

Requires SMTP_USER and SMTP_PASS in backend/.env (for Gmail, an app password
from https://myaccount.google.com/apppasswords). Optional: SMTP_HOST
(default smtp.gmail.com), SMTP_PORT (587), SMTP_FROM.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from pathlib import Path

from app.config import settings


class EmailNotConfigured(RuntimeError):
    pass


def send_clip_email(to: str, subject: str, body: str, attachment: Path) -> None:
    """Send a clip as an email attachment via SMTP (Gmail by default)."""
    if not settings.smtp_user or not settings.smtp_pass:
        raise EmailNotConfigured(
            "Email isn't configured — add SMTP_USER and SMTP_PASS to backend/.env "
            "(for Gmail, create an app password at myaccount.google.com/apppasswords)"
        )
    sender = settings.smtp_from or settings.smtp_user
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    msg.add_attachment(
        attachment.read_bytes(), maintype="video", subtype="mp4", filename=attachment.name
    )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_pass)
        smtp.send_message(msg)
