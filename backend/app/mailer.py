"""Outgoing email. SMTP (STARTTLS) when JYOTISH_SMTP_HOST is set; otherwise the
message is logged (dev mode). In prod without SMTP only a stub line is logged,
because bodies contain single-use tokens."""
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

from .config import settings

log = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> bool:
    """Best-effort send; never raises. Returns True if handed to SMTP."""
    if not settings.SMTP_HOST:
        if os.environ.get("JYOTISH_ENV") == "prod":
            log.warning("SMTP not configured; email %r to %s not sent", subject, to)
        else:
            log.info("[dev mail] to=%s subject=%s\n%s", to, subject, body)
        return False
    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as s:
            s.starttls(context=ssl.create_default_context())
            if settings.SMTP_USER:
                s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            s.send_message(msg)
        return True
    except Exception as exc:  # network/auth errors must not break the request
        log.error("email to %s failed: %s", to, type(exc).__name__)
        return False
