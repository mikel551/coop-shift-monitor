from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import load_config, parse_users
from .matcher import filter_shifts_for_user
from .notifier import notify_user
from .parser import parse_member_status, parse_shifts_page, save_member_status_html
from .scraper import create_session, fetch_member_status, fetch_shift_pages, login, login_as
from .state import (
    append_run_stats,
    export_stats_json,
    get_new_shifts,
    load_state,
    mark_notified,
    migrate_state,
    print_stats,
    prune_notified,
    prune_stats,
    save_state,
)

log = logging.getLogger(__name__)


def is_quiet_hours(site_config: dict) -> bool:
    """Check if current time falls within configured quiet hours."""
    qh = site_config.get("quiet_hours")
    if not qh:
        return False
    tz = ZoneInfo(qh.get("timezone", "America/New_York"))
    hour = datetime.now(tz).hour
    start, end = qh["start"], qh["end"]
    if start > end:  # crosses midnight (e.g. 23 -> 7)
        return hour >= start or hour < end
    return start <= hour < end


def main() -> None:
    parser = argparse.ArgumentParser(description="PSFC Shift Monitor")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--state", default="state.json", help="Path to state file")
    parser.add_argument("--dry-run", action="store_true", help="Log notifications instead of sending")
    parser.add_argument("--stats", action="store_true", help="Print stats summary and exit")
    parser.add_argument("--stats-out", default="docs/stats.json", help="Path to write dashboard stats JSON")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    state_path = Path(args.state)
    state = load_state(state_path)
    state = migrate_state(state)

    # --stats: just print and exit
    if args.stats:
        print_stats(state)
        return

    config = load_config(args.config)
    site = config["site"]
    users = parse_users(config["users"])

    # Login and fetch shift pages
    session = create_session()
    login(session, site["base_url"])

    pages = fetch_shift_pages(
        session,
        site["base_url"],
        site["shift_path_template"],
        max_weeks=site.get("max_weeks", 6),
    )

    # Parse all pages into shifts
    all_shifts = []
    for page_html in pages:
        all_shifts.extend(parse_shifts_page(page_html))

    log.info("Found %d total shifts across %d pages", len(all_shifts), len(pages))

    # Prune state to current window
    current_shift_ids = {s.shift_id for s in all_shifts}
    pruned = prune_notified(state, current_shift_ids)
    prune_stats(state)

    # Process each user, collecting stats
    user_stats: dict[str, dict[str, int]] = {}
    quiet = is_quiet_hours(site)
    if quiet:
        log.info("Quiet hours — notifications suppressed")

    for user in users:
        matched = filter_shifts_for_user(all_shifts, user)
        new = get_new_shifts(user.name, matched, state)

        user_stats[user.name] = {
            "matched": len(matched),
            "notified": 0,
            "shifts": [
                {
                    "id": s.shift_id,
                    "date": s.date.isoformat(),
                    "start": s.start_time.strftime("%H:%M"),
                    "end": s.end_time.strftime("%H:%M"),
                    "type": s.description,
                }
                for s in matched
            ],
        }

        if not new:
            log.info("No new shifts for %s", user.name)
            continue

        log.info("%d new shifts for %s", len(new), user.name)

        if quiet:
            # Still track shifts as notified so dashboard shows them as available
            mark_notified(user.name, new, state)
            user_stats[user.name]["notified"] = len(new)
            log.info("Quiet hours — marked %d shifts for %s (no text sent)", len(new), user.name)
            continue

        success = notify_user(user, new, dry_run=args.dry_run)
        if success or args.dry_run:
            mark_notified(user.name, new, state)
            user_stats[user.name]["notified"] = len(new)

    # Fetch member status for users with credentials
    member_status: dict[str, dict] = {}
    for user in users:
        if not user.credentials:
            continue
        try:
            ms_session = create_session()
            login_as(ms_session, site["base_url"], user.credentials[0], user.credentials[1])
            status_html = fetch_member_status(ms_session, site["base_url"])
            save_member_status_html(status_html, user.name)
            member_status[user.name] = parse_member_status(status_html)
            log.info("Fetched member status for %s: %s", user.name, member_status[user.name])
        except Exception:
            log.exception("Failed to fetch member status for %s", user.name)

    # Record stats and save
    append_run_stats(state, len(all_shifts), user_stats, pruned=pruned)
    save_state(state, state_path)

    # Export dashboard JSON
    stats_out = Path(args.stats_out)
    export_stats_json(state, stats_out, member_status=member_status)
    log.info("Dashboard stats written to %s", stats_out)

    # Print summary to logs
    log.info(
        "Run complete: %d shifts, %s",
        len(all_shifts),
        ", ".join(f"{u}: {s['matched']}m/{s['notified']}n" for u, s in user_stats.items()),
    )


if __name__ == "__main__":
    main()
