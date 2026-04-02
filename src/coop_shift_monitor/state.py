from __future__ import annotations

import json
from pathlib import Path

from .models import Shift

STATE_FILE = Path("state.json")


def load_state(path: Path = STATE_FILE) -> dict[str, list[str]]:
    """Load per-user notified shift IDs. Returns {user_name: [shift_id, ...]}."""
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def save_state(state: dict[str, list[str]], path: Path = STATE_FILE) -> None:
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def get_new_shifts(
    user_name: str,
    matched_shifts: list[Shift],
    state: dict[str, list[str]],
) -> list[Shift]:
    """Return only shifts not yet notified for this user."""
    notified = set(state.get(user_name, []))
    return [s for s in matched_shifts if s.shift_id not in notified]


def mark_notified(
    user_name: str,
    shifts: list[Shift],
    state: dict[str, list[str]],
) -> None:
    """Add shift IDs to the user's notified set (mutates state dict)."""
    existing = state.get(user_name, [])
    new_ids = {s.shift_id for s in shifts}
    state[user_name] = list(set(existing) | new_ids)
