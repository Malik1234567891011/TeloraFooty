import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent / ".env"


class EmailNotConfigured(RuntimeError):
    pass


def load_env() -> None:
    """Minimal .env loader (KEY=VALUE lines) — avoids a dotenv dependency."""
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def send_clip_email(to: str, subject: str, body: str, attachment: Path) -> None:
    """Send a clip as an email attachment via SMTP (Gmail by default).

    Requires SMTP_USER and SMTP_PASS in backend/.env (for Gmail, an app
    password from https://myaccount.google.com/apppasswords). Optional:
    SMTP_HOST (default smtp.gmail.com), SMTP_PORT (587), SMTP_FROM.
    """
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    if not user or not password:
        raise EmailNotConfigured(
            "Email isn't configured — add SMTP_USER and SMTP_PASS to backend/.env "
            "(for Gmail, create an app password at myaccount.google.com/apppasswords)"
        )
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    sender = os.environ.get("SMTP_FROM", user)

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    msg.add_attachment(
        attachment.read_bytes(), maintype="video", subtype="mp4", filename=attachment.name
    )
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(msg)
