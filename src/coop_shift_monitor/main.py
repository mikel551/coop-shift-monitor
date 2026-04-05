from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import load_config, parse_users
from .matcher import filter_shifts_for_user
from .notifier import notify_user
from .parser import parse_shifts_page
from .scraper import create_session, fetch_shift_pages, login
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
    prune_notified(state, current_shift_ids)
    prune_stats(state)

    # Process each user, collecting stats
    user_stats: dict[str, dict[str, int]] = {}

    for user in users:
        matched = filter_shifts_for_user(all_shifts, user)
        new = get_new_shifts(user.name, matched, state)

        user_stats[user.name] = {"matched": len(matched), "notified": 0}

        if not new:
            log.info("No new shifts for %s", user.name)
            continue

        log.info("%d new shifts for %s", len(new), user.name)

        success = notify_user(user, new, dry_run=args.dry_run)
        if success or args.dry_run:
            mark_notified(user.name, new, state)
            user_stats[user.name]["notified"] = len(new)

    # Record stats and save
    append_run_stats(state, len(all_shifts), user_stats)
    save_state(state, state_path)

    # Export dashboard JSON
    stats_out = Path(args.stats_out)
    export_stats_json(state, stats_out)
    log.info("Dashboard stats written to %s", stats_out)

    # Print summary to logs
    log.info(
        "Run complete: %d shifts, %s",
        len(all_shifts),
        ", ".join(f"{u}: {s['matched']}m/{s['notified']}n" for u, s in user_stats.items()),
    )


if __name__ == "__main__":
    main()
