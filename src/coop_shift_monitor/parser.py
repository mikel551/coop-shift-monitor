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


def _find_category_value_col(soup: BeautifulSoup, label_text: str) -> Tag | None:
    """Find the value column div for a given <span class="category"> label."""
    label_span = soup.find("span", class_="category", string=re.compile(re.escape(label_text), re.IGNORECASE))
    if not label_span:
        label_span = soup.find("p", class_="category", string=re.compile(re.escape(label_text), re.IGNORECASE))
    if not label_span:
        log.warning("Could not find category label '%s' on /services/ page", label_text)
        return None

    label_col = label_span.find_parent("div", class_=re.compile(r"col-"))
    if not label_col:
        return None

    return label_col.find_next_sibling("div", class_=re.compile(r"col-"))


def _parse_scheduled_shifts(soup: BeautifulSoup) -> list[dict] | None:
    """Parse scheduled shifts into a list of {date, start_time, description}."""
    value_col = _find_category_value_col(soup, "Scheduled Shifts:")
    if not value_col:
        return None

    shifts = []
    for card in value_col.select(".shiftcard"):
        datecard = card.select_one(".datecard")
        if not datecard:
            continue

        month = datecard.select_one(".month")
        day = datecard.select_one(".date")
        weekday = datecard.select_one(".day")
        date_str = ""
        if weekday and month and day:
            date_str = f"{weekday.get_text(strip=True)} {month.get_text(strip=True)} {day.get_text(strip=True)}"

        # Get start time from timecard (just the start, before the dash)
        start_time = ""
        timecard = card.select_one(".timecard")
        if timecard:
            time_text = timecard.get_text(strip=True)
            # "6:00pm - 8:45pm" -> "6:00pm"
            start_time = time_text.split("-")[0].strip()

        # Description: text in the shift detail col, excluding the timecard and links
        detail_col = timecard.find_parent("div") if timecard else None
        description = ""
        if detail_col:
            # Get text nodes and spans, skip .small divs (which have "View in Shift Calendar")
            parts = []
            for child in detail_col.children:
                if isinstance(child, Tag):
                    if "small" in child.get("class", []):
                        continue
                    if child.name == "span" and "timecard" in child.get("class", []):
                        continue
                    if child.name == "br":
                        continue
                    parts.append(child.get_text(strip=True))
                else:
                    text = child.strip()
                    if text:
                        parts.append(text)
            description = " ".join(parts).strip()

        shifts.append({
            "date": date_str,
            "start_time": start_time,
            "description": description,
        })

    log.info("Parsed %d scheduled shift(s)", len(shifts))
    return shifts if shifts else None


def _parse_cancel_tickets(soup: BeautifulSoup) -> int | None:
    """Parse cancel tickets count from the Cancel Tickets row."""
    value_col = _find_category_value_col(soup, "Cancel Tickets:")
    if not value_col:
        return None

    # Look for bold text like "1 cancel ticket"
    bold = value_col.find("b")
    if bold:
        text = bold.get_text(strip=True)
        match = re.search(r"(\d+)\s+cancel\s+ticket", text, re.IGNORECASE)
        if match:
            count = int(match.group(1))
            log.info("Parsed cancel tickets: %d", count)
            return count

    return None


def parse_member_status(html: str) -> dict:
    """Extract member status, scheduled shifts, credit bank, and cancel tickets
    from the /services/ page.

    The page uses Bootstrap grid rows with <span class="category"> labels in one
    column and values in the sibling column.
    """
    soup = BeautifulSoup(html, "html.parser")
    result: dict = {
        "member_status": None,
        "scheduled_shifts": None,
        "credit_bank": None,
        "cancel_tickets": None,
    }

    # Member Status: simple text extraction
    value_col = _find_category_value_col(soup, "Member Status:")
    if value_col:
        # Get status text (e.g. "Active") from the <span class="status ...">
        status_span = value_col.find("span", class_="status")
        if status_span:
            result["member_status"] = status_span.get_text(strip=True)
        else:
            result["member_status"] = value_col.get_text(" ", strip=True)
        log.info("Parsed Member Status: %s", result["member_status"])

    # Shift Credit Bank: get the number from <span class="membernumber">
    value_col = _find_category_value_col(soup, "Shift Credit Bank:")
    if value_col:
        num_span = value_col.find("span", class_="membernumber")
        if num_span:
            result["credit_bank"] = num_span.get_text(strip=True)
        else:
            result["credit_bank"] = value_col.get_text(" ", strip=True)
        log.info("Parsed Shift Credit Bank: %s", result["credit_bank"])

    # Scheduled Shifts: structured extraction
    result["scheduled_shifts"] = _parse_scheduled_shifts(soup)

    # Cancel Tickets: just the number
    result["cancel_tickets"] = _parse_cancel_tickets(soup)

    return result


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
