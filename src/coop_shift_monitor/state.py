from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .models import Shift

STATE_FILE = Path("state.json")


def load_state(path: Path = STATE_FILE) -> dict:
    """Load state file. Returns dict with per-user notified IDs and optional stats."""
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def _get_notified(state: dict) -> dict[str, list[str]]:
    """Extract per-user notified shift IDs, supporting both old and new formats."""
    # New format has "notified" and "stats" keys
    if "notified" in state:
        return state["notified"]
    # Old format: the entire dict is {user: [ids]}
    # Exclude known metadata keys
    return {k: v for k, v in state.items() if k != "stats"}


def save_state(state: dict, path: Path = STATE_FILE) -> None:
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def migrate_state(state: dict) -> dict:
    """Migrate old format {user: [ids]} to new format {notified: {...}, stats: [...]}."""
    if "notified" in state:
        state.setdefault("stats", [])
        return state
    # Old format — everything is notified data
    notified = {k: v for k, v in state.items() if k != "stats"}
    return {"notified": notified, "stats": state.get("stats", [])}


def get_new_shifts(
    user_name: str,
    matched_shifts: list[Shift],
    state: dict,
) -> list[Shift]:
    """Return only shifts not yet notified for this user."""
    notified_data = _get_notified(state)
    notified = set(notified_data.get(user_name, []))
    return [s for s in matched_shifts if s.shift_id not in notified]


def mark_notified(
    user_name: str,
    shifts: list[Shift],
    state: dict,
) -> None:
    """Add shift IDs to the user's notified set (mutates state dict)."""
    notified_data = _get_notified(state)
    existing = notified_data.get(user_name, [])
    new_ids = {s.shift_id for s in shifts}
    notified_data[user_name] = list(set(existing) | new_ids)
    # Ensure new format
    if "notified" in state:
        state["notified"] = notified_data
    else:
        # Update in-place for old format
        state.update(notified_data)


def append_run_stats(
    state: dict,
    total_shifts: int,
    user_stats: dict[str, dict[str, int]],
) -> None:
    """Append a run record to state['stats'].

    state must already be in migrated format (call migrate_state first).
    user_stats: {user_name: {"matched": N, "notified": M}}
    """
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "total": total_shifts,
        "users": user_stats,
    }
    state.setdefault("stats", []).append(record)


def export_stats_json(state: dict, output_path: Path) -> None:
    """Write stats list to a JSON file for the web dashboard."""
    stats = state.get("stats", [])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(stats, f, indent=2)


def print_stats(state: dict) -> None:
    """Print a summary of stats to stdout."""
    stats = state.get("stats", [])
    if not stats:
        print("No stats recorded yet.")
        return

    print(f"\n{'='*60}")
    print(f"  Shift Monitor Stats  ({len(stats)} runs)")
    print(f"{'='*60}")

    # Aggregate per-user totals
    user_totals: dict[str, dict[str, int]] = {}
    for record in stats:
        for user, counts in record.get("users", {}).items():
            if user not in user_totals:
                user_totals[user] = {"matched": 0, "notified": 0}
            user_totals[user]["matched"] += counts.get("matched", 0)
            user_totals[user]["notified"] += counts.get("notified", 0)

    print(f"\n{'User':<15} {'Matched':>10} {'Notified':>10}")
    print(f"{'-'*15} {'-'*10} {'-'*10}")
    for user, totals in sorted(user_totals.items()):
        print(f"{user:<15} {totals['matched']:>10} {totals['notified']:>10}")

    # Recent runs
    print(f"\nLast 5 runs:")
    print(f"{'Timestamp':<28} {'Total Shifts':>13}")
    print(f"{'-'*28} {'-'*13}")
    for record in stats[-5:]:
        ts = record["ts"][:19].replace("T", " ")
        print(f"{ts:<28} {record['total']:>13}")

    print()
