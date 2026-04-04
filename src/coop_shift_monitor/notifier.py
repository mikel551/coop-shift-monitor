from __future__ import annotations

import logging
import os
import smtplib
from email.mime.text import MIMEText

from .models import Shift, SmtpCredentials, User

log = logging.getLogger(__name__)


BASE_URL = "https://members.foodcoop.com"


def format_shift_list(shifts: list[Shift], include_links: bool = False) -> str:
    lines: list[str] = []
    for s in sorted(shifts, key=lambda s: (s.date, s.start_time)):
        day = s.date.strftime("%A %b %d")
        start = s.start_time.strftime("%-I:%M %p")
        carrot = " [carrot]" if s.is_carrot else ""
        line = f"  - {day}: {s.description} ({start}){carrot}"
        if include_links:
            line += f"\n    {BASE_URL}/services/shift_claim/{s.shift_id}/"
        lines.append(line)
    return "\n".join(lines)


def _send_via_smtp(
    smtp: SmtpCredentials,
    to_addr: str,
    subject: str,
    body: str,
) -> None:
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = smtp.from_addr or smtp.username
    msg["To"] = to_addr

    with smtplib.SMTP(smtp.host, smtp.port) as server:
        server.starttls()
        server.login(smtp.username, smtp.password)
        server.send_message(msg)


def send_email(user: User, shifts: list[Shift], dry_run: bool = False) -> None:
    body = (
        f"Hi {user.name},\n\n"
        f"New open shifts matching your preferences:\n\n"
        f"{format_shift_list(shifts, include_links=True)}\n"
    )
    if dry_run:
        log.info("DRY RUN email to %s:\n%s", user.notify.email, body)
        return

    _send_via_smtp(
        user.notify.smtp,
        user.notify.email,
        f"PSFC: {len(shifts)} new open shift(s)",
        body,
    )
    log.info("Email sent to %s (%d shifts)", user.notify.email, len(shifts))


def _send_sms_twilio(
    to_number: str,
    body: str,
) -> None:
    from twilio.rest import Client

    account_sid = os.environ["TWILIO_ACCOUNT_SID"]
    auth_token = os.environ["TWILIO_AUTH_TOKEN"]
    from_number = os.environ["TWILIO_FROM_NUMBER"]

    client = Client(account_sid, auth_token)
    message = client.messages.create(
        body=body,
        from_=from_number,
        to=to_number,
    )
    log.info("Twilio SMS sent to %s (sid=%s)", to_number, message.sid)


def send_sms(user: User, shifts: list[Shift], dry_run: bool = False) -> None:
    use_twilio = bool(os.environ.get("TWILIO_ACCOUNT_SID"))

    # Twilio has a 1600 char limit — skip links for SMS
    body = (
        f"PSFC shifts for {user.name}:\n"
        f"{format_shift_list(shifts, include_links=not use_twilio)}\n"
    )

    if dry_run:
        method = "Twilio" if use_twilio else "email gateway"
        log.info("DRY RUN SMS (%s) to %s:\n%s", method, user.notify.sms, body)
        return

    if use_twilio:
        # Truncate to 1600 chars if still too long
        if len(body) > 1600:
            body = body[:1597] + "..."
        _send_sms_twilio(user.notify.sms, body)
    else:
        sms_addr = user.notify.sms_email
        if not sms_addr:
            log.warning("No SMS gateway for %s (carrier=%s)", user.name, user.notify.carrier)
            return
        _send_via_smtp(
            user.notify.smtp,
            sms_addr,
            "",  # SMS gateway ignores subject
            body,
        )
        log.info("SMS sent to %s via %s (%d shifts)", user.notify.sms, sms_addr, len(shifts))


def notify_user(user: User, shifts: list[Shift], dry_run: bool = False) -> bool:
    """Send notifications to user. Returns True if all succeeded."""
    success = True

    if user.notify.email:
        try:
            send_email(user, shifts, dry_run=dry_run)
        except Exception:
            log.exception("Failed to email %s", user.name)
            success = False

    if user.notify.sms:
        try:
            send_sms(user, shifts, dry_run=dry_run)
        except Exception:
            log.exception("Failed to SMS %s", user.name)
            success = False

    return success
