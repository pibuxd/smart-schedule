"""Where a location has fewer experienced people than its staffing asks for on one shift.

Shown to the manager before arranging a schedule. It reports only a sure shortage: the largest "of these,
N experienced" on a single shift of the period against the active people of the location who are experienced
on that position. Availability and days off are not looked at, so no warning is not a promise of a full schedule.
"""

from collections import defaultdict
from datetime import date, timedelta
from uuid import UUID

from ninja import Schema

from apps.staffing.models import (
    EmployeeProfile,
    Experience,
    Position,
    PositionExperience,
    StaffingException,
    StaffingRule,
)


class ExperiencedShortOut(Schema):
    position_id: UUID
    position_name: str
    # The most experienced people one shift of the period needs, and how many the location has.
    needed: int
    available: int


def _needed(company_id, location_id, start: date, end: date) -> dict[UUID, int]:
    """Position -> the largest experienced requirement on one shift of a day in the period."""
    weekdays = {(start + timedelta(days=i)).weekday() for i in range(min((end - start).days + 1, 7))}
    exceptions = {
        (day, shift_type, position): (count, experienced)
        for day, shift_type, position, count, experienced in StaffingException.objects.for_company(company_id)
        .filter(location=location_id, date__range=(start, end))
        .values_list("date", "shift_type_id", "position_id", "count", "experienced")
    }
    needed: dict[UUID, int] = defaultdict(int)
    for (_day, _shift_type, position), (count, experienced) in exceptions.items():
        needed[position] = max(needed[position], min(count, experienced))
    # A weekday rule counts when at least one of its days in the period has no exception in its place.
    replaced: dict[tuple, int] = defaultdict(int)
    for day, shift_type, position in exceptions:
        replaced[(day.weekday(), shift_type, position)] += 1
    days_of: dict[int, int] = defaultdict(int)
    for i in range((end - start).days + 1):
        days_of[(start + timedelta(days=i)).weekday()] += 1
    for weekday, shift_type, position, count, experienced in (
        StaffingRule.objects.for_company(company_id)
        .filter(location=location_id, weekday__in=weekdays, experienced__gt=0)
        .values_list("weekday", "shift_type_id", "position_id", "count", "experienced")
    ):
        if replaced[(weekday, shift_type, position)] < days_of[weekday]:
            needed[position] = max(needed[position], min(count, experienced))
    return {position: n for position, n in needed.items() if n > 0}


def experienced_shortage(company_id, location_id, start: date, end: date) -> list[ExperiencedShortOut]:
    needed = _needed(company_id, location_id, start, end)
    if not needed:
        return []
    people = EmployeeProfile.objects.for_company(company_id).filter(home_location=location_id, is_active=True)
    default = dict(people.values_list("pk", "experience"))
    own = {
        (employee, position): level
        for employee, position, level in PositionExperience.objects.for_company(company_id)
        .filter(employee__in=default, position__in=needed)
        .values_list("employee_id", "position_id", "level")
    }
    available: dict[UUID, int] = defaultdict(int)
    for employee, position in EmployeeProfile.positions.through.objects.filter(
        employeeprofile_id__in=default, position_id__in=needed
    ).values_list("employeeprofile_id", "position_id"):
        if own.get((employee, position), default[employee]) == Experience.EXPERIENCED:
            available[position] += 1
    names = dict(Position.objects.for_company(company_id).filter(pk__in=needed).values_list("pk", "name"))
    return [
        ExperiencedShortOut(
            position_id=position, position_name=names[position], needed=n, available=available[position]
        )
        for position, n in sorted(needed.items(), key=lambda item: names[item[0]].casefold())
        if available[position] < n
    ]
