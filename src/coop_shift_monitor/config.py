from __future__ import annotations

import os
from datetime import time
from pathlib import Path

import yaml

from .models import NotifyConfig, SmtpCredentials, TimeWindow, User


def load_config(path: str | Path = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def parse_time(s: str) -> time:
    parts = s.split(":")
    return time(int(parts[0]), int(parts[1]))


def _resolve_env(value: str) -> str:
    """If value starts with $, treat it as an env var reference."""
    if value.startswith("$"):
        return os.environ.get(value[1:], "")
    return value


def _parse_smtp(raw: dict) -> SmtpCredentials:
    return SmtpCredentials(
        host=raw.get("host", "smtp.gmail.com"),
        port=int(raw.get("port", 587)),
        username=_resolve_env(raw.get("username", "")),
        password=_resolve_env(raw.get("password", "")),
        from_addr=_resolve_env(raw.get("from", "")),
    )


def parse_users(raw: list[dict]) -> list[User]:
    users: list[User] = []
    for u in raw:
        windows: list[TimeWindow] = []
        for av in u.get("availability", []):
            start = parse_time(av["start"]) if "start" in av else None
            end = parse_time(av["end"]) if "end" in av else None
            if "after" in av:
                start = parse_time(av["after"])
                end = None
            windows.append(TimeWindow(day=av["day"], start=start, end=end))

        notify_raw = u.get("notify", {})
        smtp = _parse_smtp(notify_raw.get("smtp", {}))

        notify = NotifyConfig(
            email=notify_raw.get("email"),
            sms=notify_raw.get("sms"),
            carrier=notify_raw.get("carrier"),
            smtp=smtp,
        )

        users.append(User(
            name=u["name"],
            shift_types=u.get("shift_types", []),
            availability=windows,
            notify=notify,
        ))
    return users
