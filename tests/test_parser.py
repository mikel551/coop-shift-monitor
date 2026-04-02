from datetime import date, time
from pathlib import Path

from coop_shift_monitor.parser import parse_shifts_page

FIXTURE = Path(__file__).parent / "fixtures" / "shift.html"


def test_parse_real_page():
    html = FIXTURE.read_text()
    shifts = parse_shifts_page(html)

    # Page says "Found 589 shifts!"
    assert len(shifts) == 589

    # All shifts should have valid dates in the expected range
    assert all(s.date >= date(2026, 4, 13) for s in shifts)
    assert all(s.date <= date(2026, 4, 19) for s in shifts)


def test_parse_dates_cover_full_week():
    html = FIXTURE.read_text()
    shifts = parse_shifts_page(html)
    dates = sorted({s.date for s in shifts})
    # Should cover Mon-Sun of the displayed week
    assert len(dates) == 7
    assert dates[0] == date(2026, 4, 13)  # Monday
    assert dates[-1] == date(2026, 4, 19)  # Sunday


def test_parse_shift_ids():
    html = FIXTURE.read_text()
    shifts = parse_shifts_page(html)
    # All shift IDs should be numeric (from /shift_claim/{id}/)
    assert all(s.shift_id.isdigit() for s in shifts)
    # All IDs should be unique
    assert len({s.shift_id for s in shifts}) == len(shifts)


def test_parse_times():
    html = FIXTURE.read_text()
    shifts = parse_shifts_page(html)

    # First shift on Monday should be early morning (5:00am)
    monday_shifts = [s for s in shifts if s.date == date(2026, 4, 13)]
    earliest = min(monday_shifts, key=lambda s: s.start_time)
    assert earliest.start_time == time(5, 0)


def test_parse_descriptions():
    html = FIXTURE.read_text()
    shifts = parse_shifts_page(html)

    descriptions = {s.description for s in shifts}
    # Known shift types from the fixture
    assert any("Lifting" in d for d in descriptions)
    assert any("Stocking" in d for d in descriptions)


def test_parse_carrot_shifts():
    html = FIXTURE.read_text()
    shifts = parse_shifts_page(html)
    carrot_shifts = [s for s in shifts if s.is_carrot]
    non_carrot = [s for s in shifts if not s.is_carrot]
    # There should be both carrot and non-carrot shifts
    assert len(carrot_shifts) > 0
    assert len(non_carrot) > 0


def test_slots_all_one():
    """Each <a> tag represents one available slot."""
    html = FIXTURE.read_text()
    shifts = parse_shifts_page(html)
    assert all(s.slots_available == 1 for s in shifts)
