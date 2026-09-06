"""
EmailProvider. Never claims a send succeeded unless it actually did.
Dry-run is the safe default and is clearly labelled to the caller and user.
"""
from __future__ import annotations
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from dataclasses import dataclass


@dataclass
class EmailResult:
    status: str  # "SENT" | "DRY_RUN" | "FAILED"
    detail: str


def is_smtp_configured() -> bool:
    return all(os.environ.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS"))


def send_email(to_addr: str, subject: str, body: str, attachment_bytes: bytes | None = None, attachment_name: str = "proposal.pdf") -> EmailResult:
    if not to_addr or "@" not in to_addr:
        return EmailResult("FAILED", "Invalid recipient address.")

    if not is_smtp_configured():
        return EmailResult(
            "DRY_RUN",
            "SMTP not configured (SMTP_HOST/SMTP_USER/SMTP_PASS). No email was actually sent — "
            "this is a safe dry run. Configure SMTP env vars to enable real sending.",
        )

    try:
        host = os.environ["SMTP_HOST"]
        port = int(os.environ.get("SMTP_PORT", "587"))
        user = os.environ["SMTP_USER"]
        password = os.environ["SMTP_PASS"]

        msg = MIMEMultipart()
        msg["From"] = user
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        if attachment_bytes:
            part = MIMEApplication(attachment_bytes, Name=attachment_name)
            part["Content-Disposition"] = f'attachment; filename="{attachment_name}"'
            msg.attach(part)

        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(user, [to_addr], msg.as_string())
        return EmailResult("SENT", f"Email sent to {to_addr}.")
    except Exception as e:
        return EmailResult("FAILED", f"SMTP send failed: {type(e).__name__}: {e}")
