from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time


@dataclass(frozen=True)
class Shift:
    shift_id: str
    date: date
    start_time: time
    end_time: time
    description: str
    slots_available: int = 0
    is_carrot: bool = False

    @property
    def day_name(self) -> str:
        return self.date.strftime("%A")


@dataclass
class TimeWindow:
    day: str  # e.g. "Saturday"
    start: time | None = None
    end: time | None = None

    def matches(self, shift: Shift) -> bool:
        if shift.day_name.lower() != self.day.lower():
            return False
        if self.start is not None and shift.start_time < self.start:
            return False
        if self.end is not None and shift.start_time > self.end:
            return False
        return True


CARRIER_GATEWAYS = {
    "tmobile": "tmomail.net",
    "t-mobile": "tmomail.net",
    "att": "txt.att.net",
    "verizon": "vtext.com",
    "sprint": "messaging.sprintpcs.com",
}


@dataclass
class SmtpCredentials:
    host: str = "smtp.gmail.com"
    port: int = 587
    username: str = ""
    password: str = ""
    from_addr: str = ""


@dataclass
class NotifyConfig:
    email: str | None = None
    sms: str | None = None
    carrier: str | None = None
    smtp: SmtpCredentials = field(default_factory=SmtpCredentials)

    @property
    def sms_email(self) -> str | None:
        """Convert phone + carrier to an email-to-SMS gateway address."""
        if not self.sms or not self.carrier:
            return None
        domain = CARRIER_GATEWAYS.get(self.carrier.lower())
        if not domain:
            return None
        digits = "".join(c for c in self.sms if c.isdigit())
        return f"{digits}@{domain}"


@dataclass
class User:
    name: str
    shift_types: list[str] = field(default_factory=list)
    availability: list[TimeWindow] = field(default_factory=list)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
