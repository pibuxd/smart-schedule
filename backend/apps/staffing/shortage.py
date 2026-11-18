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
    ShiftType,
    StaffingException,
    StaffingRule,
    works_in_q,
)


class ExperiencedShortOut(Schema):
    position_id: UUID
    position_name: str
    # The most experienced people one shift of the period needs, and how many the location has.
    needed: int
    available: int
    # The first day and the shift with that need, so the manager knows where to look.
    day: date
    shift_name: str


def _needed(company_id, location_id, start: date, end: date) -> dict[UUID, tuple[int, date, UUID]]:
    """Position -> the largest experienced requirement on one shift of the period, with its first day and shift."""
    weekly: dict[int, dict[tuple, int]] = defaultdict(dict)
    for weekday, shift_type, position, count, experienced in (
        StaffingRule.objects.for_company(company_id)
        .filter(location=location_id)
        .values_list("weekday", "shift_type_id", "position_id", "count", "experienced")
    ):
        weekly[weekday][(shift_type, position)] = min(count, experienced)
    exceptions: dict[date, dict[tuple, int]] = defaultdict(dict)
    for day, shift_type, position, count, experienced in (
        StaffingException.objects.for_company(company_id)
        .filter(location=location_id, date__range=(start, end))
        .values_list("date", "shift_type_id", "position_id", "count", "experienced")
    ):
        exceptions[day][(shift_type, position)] = min(count, experienced)

    needed: dict[UUID, tuple[int, date, UUID]] = {}
    for i in range((end - start).days + 1):
        day = start + timedelta(days=i)
        # A date exception replaces the weekday's staffing of that shift and position, as in the generator.
        demand = {**weekly.get(day.weekday(), {}), **exceptions.get(day, {})}
        for (shift_type, position), experienced in sorted(demand.items(), key=str):
            if experienced > needed.get(position, (0,))[0]:
                needed[position] = (experienced, day, shift_type)
    return needed


def experienced_shortage(company_id, location_id, start: date, end: date) -> list[ExperiencedShortOut]:
    needed = _needed(company_id, location_id, start, end)
    if not needed:
        return []
    people = EmployeeProfile.objects.for_company(company_id).filter(works_in_q(location_id), is_active=True)
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
    shifts = dict(
        ShiftType.objects.for_company(company_id)
        .filter(pk__in=[shift_type for _n, _day, shift_type in needed.values()])
        .values_list("pk", "name")
    )
    return [
        ExperiencedShortOut(
            position_id=position,
            position_name=names[position],
            needed=n,
            available=available[position],
            day=day,
            shift_name=shifts[shift_type],
        )
        for position, (n, day, shift_type) in sorted(needed.items(), key=lambda item: names[item[0]].casefold())
        if available[position] < n
    ]
