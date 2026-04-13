from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Shift

log = logging.getLogger(__name__)

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
    pruned: int = 0,
) -> None:
    """Append a run record to state['stats'].

    state must already be in migrated format (call migrate_state first).
    user_stats: {user_name: {"matched": N, "notified": M}}
    """
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "total": total_shifts,
        "users": user_stats,
        "pruned": pruned,
    }
    state.setdefault("stats", []).append(record)


def prune_notified(state: dict, current_shift_ids: set[str]) -> int:
    """Remove shift IDs that are no longer in the current calendar. Returns total pruned."""
    notified = state.get("notified", {})
    total_pruned = 0
    for user in notified:
        before = len(notified[user])
        notified[user] = [sid for sid in notified[user] if sid in current_shift_ids]
        removed = before - len(notified[user])
        if removed:
            total_pruned += removed
            log.info("Pruned %d stale shift IDs for %s (%d -> %d)", removed, user, before, len(notified[user]))
    return total_pruned


def prune_stats(state: dict, weeks: int = 6) -> None:
    """Keep only recent stats, aggregate older ones into previous_period."""
    stats = state.get("stats", [])
    cutoff = (datetime.now(timezone.utc) - timedelta(weeks=weeks)).isoformat()

    old_records = [r for r in stats if r["ts"] < cutoff]
    if old_records:
        prev = {"total_runs": len(old_records), "users": {}}
        for r in old_records:
            for user, counts in r.get("users", {}).items():
                if user not in prev["users"]:
                    prev["users"][user] = {"matched": 0, "notified": 0}
                prev["users"][user]["matched"] += counts.get("matched", 0)
                prev["users"][user]["notified"] += counts.get("notified", 0)
        # Merge with any existing previous_period data
        existing = state.get("previous_period", {})
        if existing:
            prev["total_runs"] += existing.get("total_runs", 0)
            for user, counts in existing.get("users", {}).items():
                if user not in prev["users"]:
                    prev["users"][user] = {"matched": 0, "notified": 0}
                prev["users"][user]["matched"] += counts.get("matched", 0)
                prev["users"][user]["notified"] += counts.get("notified", 0)
        state["previous_period"] = prev

    state["stats"] = [r for r in stats if r["ts"] >= cutoff]
    if old_records:
        log.info("Pruned %d old stats records (before %s), %d remaining", len(old_records), cutoff[:10], len(state["stats"]))


def export_stats_json(
    state: dict,
    output_path: Path,
    member_status: dict[str, dict] | None = None,
    shift_type_counts: dict[str, int] | None = None,
    user_config: list[dict] | None = None,
) -> None:
    """Write stats, previous_period, available shifts, and member status to a JSON file for the web dashboard."""
    # Build available shifts: notified IDs matched with shift details from latest run
    available: dict[str, list[dict]] = {}
    notified = state.get("notified", {})
    stats = state.get("stats", [])
    # Get shift details from the latest run
    latest_shifts: dict[str, dict] = {}
    if stats:
        latest = stats[-1]
        for user, u in latest.get("users", {}).items():
            for s in u.get("shifts", []):
                latest_shifts[s["id"]] = s

    for user, ids in notified.items():
        user_shifts = []
        for sid in ids:
            if sid in latest_shifts:
                user_shifts.append(latest_shifts[sid])
            else:
                # ID is notified but no details in latest run — include with ID only
                user_shifts.append({"id": sid})
        if user_shifts:
            available[user] = sorted(user_shifts, key=lambda s: (s.get("date", ""), s.get("start", "")))

    data = {
        "stats": stats,
        "previous_period": state.get("previous_period", {}),
        "available_shifts": available,
        "member_status": member_status or {},
        "shift_type_counts": shift_type_counts or {},
        "user_config": user_config or [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)


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
