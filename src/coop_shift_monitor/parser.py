from __future__ import annotations

import re
from datetime import date, time

from bs4 import BeautifulSoup, Tag

from .models import Shift


def parse_shifts_page(html: str) -> list[Shift]:
    """Parse the PSFC shift calendar HTML page into a list of Shift objects.

    Page structure:
      div.grid-container
        div.col  (one per day)
          p > b   "Mon&nbsp;4/13/2026"
          a.shift (one per available slot)
            b     "5:00am"
            text  "Lifting" (with possible emoji)
    """
    soup = BeautifulSoup(html, "html.parser")
    shifts: list[Shift] = []

    for col in soup.select(".grid-container .col"):
        shift_date = _parse_col_date(col)
        if not shift_date:
            continue

        for link in col.select("a.shift"):
            # Skip already-filled shifts
            classes = link.get("class", [])
            if "worker" in classes or "my_shift" in classes:
                continue

            shift = _parse_shift_link(link, shift_date)
            if shift:
                shifts.append(shift)

    return shifts


def _parse_col_date(col: Tag) -> date | None:
    """Extract date from column header like 'Mon&nbsp;4/13/2026'."""
    p = col.find("p")
    if not p:
        return None
    b = p.find("b")
    if not b:
        return None

    text = b.get_text()
    # Handle nbsp and extract "4/13/2026" portion
    text = text.replace("\xa0", " ").strip()
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if not match:
        return None
    month, day, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    return date(year, month, day)


def _parse_shift_link(link: Tag, shift_date: date) -> Shift | None:
    """Parse a single <a class="shift"> element."""
    # Shift ID from href: /services/shift_claim/1099485/
    href = (link.get("href") or "").strip()
    id_match = re.search(r"/shift_claim/(\d+)/", href)
    shift_id = id_match.group(1) if id_match else href

    # Start time from <b> tag: "5:00am"
    b = link.find("b")
    if not b:
        return None
    start_time = _parse_time(b.get_text(strip=True))
    if not start_time:
        return None

    # Description: all text except the time and emoji markers
    full_text = link.get_text(" ", strip=True)
    # Remove the time portion
    time_text = b.get_text(strip=True)
    description = full_text.replace(time_text, "").strip()
    # Remove carrot emoji marker if present
    description = description.replace("\U0001f955", "").strip()  # carrot emoji
    # Clean up extra whitespace
    description = re.sub(r"\s+", " ", description).strip()

    is_carrot = "carrot" in (link.get("class") or [])

    return Shift(
        shift_id=shift_id,
        date=shift_date,
        start_time=start_time,
        end_time=start_time,  # site doesn't show end time
        description=description,
        slots_available=1,  # each <a> is one slot
        is_carrot=is_carrot,
    )


import logging

log = logging.getLogger(__name__)


def parse_member_status(html: str) -> dict:
    """Extract member status, scheduled shifts, and credit bank from /services/ page.

    The page uses a table layout: labels like "MEMBER STATUS:" in one <td>,
    values in the next <td>.

    Returns a dict with keys: member_status, scheduled_shifts, credit_bank.
    Missing fields are set to None.
    """
    soup = BeautifulSoup(html, "html.parser")
    result: dict = {
        "member_status": None,
        "scheduled_shifts": None,
        "credit_bank": None,
    }

    for label_text, key in [
        ("member status", "member_status"),
        ("scheduled shifts", "scheduled_shifts"),
        ("shift credit bank", "credit_bank"),
    ]:
        # Find any element whose text matches the label (case-insensitive)
        label_el = soup.find(string=re.compile(re.escape(label_text), re.IGNORECASE))
        if not label_el:
            log.warning("Could not find '%s' on /services/ page", label_text)
            continue

        # Walk up to the nearest <td> or <th> (table cell containing the label)
        cell = label_el.find_parent(["td", "th"])
        if cell:
            # Value is in the next sibling <td> in the same row
            value_cell = cell.find_next_sibling("td")
            if value_cell:
                value = value_cell.get_text(" ", strip=True)
                if value:
                    result[key] = value
                    log.info("Parsed '%s' = '%s'", label_text, value)
                    continue

        # Fallback: walk up to <dt> (definition list)
        dt = label_el.find_parent("dt")
        if dt:
            dd = dt.find_next_sibling("dd")
            if dd:
                value = dd.get_text(" ", strip=True)
                if value:
                    result[key] = value
                    log.info("Parsed '%s' = '%s' (from dl)", label_text, value)
                    continue

        # Fallback: walk up to any parent and check its next sibling
        parent = label_el.find_parent()
        if parent:
            next_sib = parent.find_next_sibling()
            if next_sib:
                value = next_sib.get_text(" ", strip=True)
                if value:
                    result[key] = value
                    log.info("Parsed '%s' = '%s' (from sibling)", label_text, value)
                    continue

        log.warning("Found '%s' label but could not extract value", label_text)

    return result


def save_member_status_html(html: str, name: str) -> None:
    """Save raw member status HTML for debugging."""
    from pathlib import Path
    debug_dir = Path("docs")
    debug_dir.mkdir(parents=True, exist_ok=True)
    path = debug_dir / f"debug_member_status_{name.lower()}.html"
    path.write_text(html)
    log.info("Saved member status HTML for %s to %s", name, path)


def _parse_time(s: str) -> time | None:
    s = s.strip().lower()
    match = re.match(r"(\d{1,2}):(\d{2})(am|pm)", s)
    if not match:
        return None
    hour, minute, ampm = int(match.group(1)), int(match.group(2)), match.group(3)
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    return time(hour, minute)
