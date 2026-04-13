from __future__ import annotations

from .models import Shift, User


def matches_shift_type(shift: Shift, user: User) -> bool:
    if not user.shift_types:
        return True  # No filter = match all
    desc_lower = shift.description.lower()
    return any(st.lower() in desc_lower for st in user.shift_types)


def matches_availability(shift: Shift, user: User) -> bool:
    if not user.availability:
        return True  # No filter = match all
    return any(window.matches(shift) for window in user.availability)


def matches_date_range(shift: Shift, user: User) -> bool:
    if not user.date_range:
        return True
    return user.date_range[0] <= shift.date <= user.date_range[1]


def filter_shifts_for_user(shifts: list[Shift], user: User) -> list[Shift]:
    return [
        s for s in shifts
        if s.slots_available > 0
        and matches_shift_type(s, user)
        and matches_availability(s, user)
        and matches_date_range(s, user)
    ]
