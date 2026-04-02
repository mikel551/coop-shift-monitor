from datetime import date, time

from coop_shift_monitor.matcher import filter_shifts_for_user
from coop_shift_monitor.models import NotifyConfig, Shift, TimeWindow, User


def _shift(desc: str, d: date, start: time, slots: int = 1) -> Shift:
    return Shift(
        shift_id=f"{d}_{start}_{desc}",
        date=d,
        start_time=start,
        end_time=start,
        description=desc,
        slots_available=slots,
    )


SAT = date(2026, 4, 18)   # Saturday
SUN = date(2026, 4, 19)   # Sunday
THU = date(2026, 4, 16)   # Thursday


SHIFTS = [
    _shift("Cart Return and Sidewalk Maintenance", SAT, time(9, 0)),
    _shift("Cart Return and Sidewalk Maintenance", SAT, time(10, 0)),
    _shift("Cashier", SAT, time(14, 0), slots=0),
    _shift("Office", SUN, time(10, 0)),
    _shift("Checkout", SUN, time(11, 0)),
    _shift("Cart Return and Sidewalk Maintenance", SUN, time(15, 0)),
    _shift("Cashier", THU, time(18, 0)),
    _shift("Office", THU, time(19, 0)),
    _shift("Dairy Lifting", THU, time(17, 0)),
]


def test_mike_filters():
    """Mike wants Cart Return on Sat (all day) or Sun 9-14."""
    mike = User(
        name="Mike",
        shift_types=["Cart Return"],
        availability=[
            TimeWindow(day="Saturday"),
            TimeWindow(day="Sunday", start=time(9, 0), end=time(14, 0)),
        ],
        notify=NotifyConfig(sms="+15551234567"),
    )
    result = filter_shifts_for_user(SHIFTS, mike)
    descs = [(s.description, s.date) for s in result]

    assert ("Cart Return and Sidewalk Maintenance", SAT) in descs
    # Sunday Cart Return at 15:00 is outside 9-14 window
    assert ("Cart Return and Sidewalk Maintenance", SUN) not in descs
    assert len(result) == 2  # Two Saturday slots


def test_nancy_filters():
    """Nancy wants Cashier/Checkout/Office on Thu after 18:00 or Sun 9-14."""
    nancy = User(
        name="Nancy",
        shift_types=["Cashier", "Checkout", "Office"],
        availability=[
            TimeWindow(day="Thursday", start=time(18, 0)),
            TimeWindow(day="Sunday", start=time(9, 0), end=time(14, 0)),
        ],
        notify=NotifyConfig(email="nancy@example.com", sms="+15559876543"),
    )
    result = filter_shifts_for_user(SHIFTS, nancy)
    descs = [(s.description, s.date) for s in result]

    assert ("Office", SUN) in descs
    assert ("Checkout", SUN) in descs
    assert ("Cashier", THU) in descs
    assert ("Office", THU) in descs
    assert ("Dairy Lifting", THU) not in descs
    assert len(result) == 4


def test_zero_slots_excluded():
    user = User(
        name="Anyone",
        shift_types=["Cashier"],
        availability=[TimeWindow(day="Saturday")],
        notify=NotifyConfig(email="a@b.com"),
    )
    result = filter_shifts_for_user(SHIFTS, user)
    assert len(result) == 0


def test_no_filters_matches_all_with_slots():
    user = User(name="All", notify=NotifyConfig(email="a@b.com"))
    result = filter_shifts_for_user(SHIFTS, user)
    assert len(result) == len([s for s in SHIFTS if s.slots_available > 0])


def test_partial_type_match():
    """'Office' matches 'Office'."""
    user = User(
        name="Partial",
        shift_types=["Office"],
        notify=NotifyConfig(email="a@b.com"),
    )
    result = filter_shifts_for_user(SHIFTS, user)
    assert all("Office" in s.description for s in result)
    assert len(result) == 2


def test_integration_with_real_html():
    """Test matcher against parsed real HTML."""
    from pathlib import Path
    from coop_shift_monitor.parser import parse_shifts_page

    fixture = Path(__file__).parent / "fixtures" / "shift.html"
    html = fixture.read_text()
    all_shifts = parse_shifts_page(html)

    user = User(
        name="Test",
        shift_types=["Lifting", "Stocking"],
        availability=[
            TimeWindow(day="Saturday"),
            TimeWindow(day="Sunday", start=time(9, 0), end=time(14, 0)),
        ],
        notify=NotifyConfig(sms="+15551234567"),
    )
    result = filter_shifts_for_user(all_shifts, user)
    # Should find matching shifts (Lifting/Stocking exist on Sat/Sun)
    assert len(result) > 0
    # All should be on Saturday or Sunday
    for s in result:
        assert s.day_name in ("Saturday", "Sunday")
    # All should match the type filter
    for s in result:
        assert any(t.lower() in s.description.lower() for t in user.shift_types)
