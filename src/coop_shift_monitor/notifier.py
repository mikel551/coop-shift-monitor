from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

from .models import Shift, SmtpCredentials, User

log = logging.getLogger(__name__)


def format_shift_list(shifts: list[Shift]) -> str:
    lines: list[str] = []
    for s in sorted(shifts, key=lambda s: (s.date, s.start_time)):
        day = s.date.strftime("%A %b %d")
        start = s.start_time.strftime("%-I:%M %p")
        carrot = " [carrot]" if s.is_carrot else ""
        lines.append(f"  - {day}: {s.description} ({start}){carrot}")
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
        f"{format_shift_list(shifts)}\n\n"
        f"Sign up at https://members.foodcoop.com\n"
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


def send_sms(user: User, shifts: list[Shift], dry_run: bool = False) -> None:
    sms_addr = user.notify.sms_email
    if not sms_addr:
        log.warning("No SMS gateway for %s (carrier=%s)", user.name, user.notify.carrier)
        return

    body = (
        f"PSFC shifts for {user.name}:\n"
        f"{format_shift_list(shifts)}\n"
        f"Sign up: members.foodcoop.com"
    )
    if dry_run:
        log.info("DRY RUN SMS to %s (%s):\n%s", user.notify.sms, sms_addr, body)
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
