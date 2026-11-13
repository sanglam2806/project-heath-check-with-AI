"""
Sends invite emails via stdlib smtplib — no new dependency. Optional, like
DATABASE_URL/OPENAI_API_KEY: if SMTP_* isn't configured in server/.env,
callers should still create the invite for real and just skip the send,
surfacing the invite link for the admin to share manually instead.
"""
import logging
import os
import smtplib
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or 587)
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
SMTP_FROM = os.getenv("SMTP_FROM", "").strip() or SMTP_USER
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5173").strip().rstrip("/")


def is_configured() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD)


def build_invite_link(token: str) -> str:
    return f"{APP_BASE_URL}/#/accept-invite/{token}"


def send_invite_email(
    to_email: str,
    to_name: str,
    invite_link: str,
    inviter_name: str,
    group_name: Optional[str] = None,
) -> None:
    """Raises on failure — callers decide whether that's fatal to the
    request or just means "email_sent: false" in the response."""
    group_line = f' as part of the "{group_name}" team' if group_name else ""
    body = (
        f"Hi {to_name},\n\n"
        f"{inviter_name} invited you to join Project Health Checker{group_line}.\n\n"
        f"Click the link below to set your password and activate your account:\n"
        f"{invite_link}\n\n"
        f"This link expires in 7 days.\n"
    )
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "You're invited to Project Health Checker"
    msg["From"] = SMTP_FROM
    msg["To"] = to_email

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM, [to_email], msg.as_string())
    logger.info("Sent invite email to %s", to_email)
