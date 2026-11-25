"""Hours worked in a month, from published schedules, split by location, with the pay; also as a CSV file for
payroll.

Approved other hours of a shift (overtime, leaving early; `apps.worktime`) count instead of the schedule's. Pay is
those hours times the rate of each shift on its day, plus supplements (`apps.pay.services`)."""

import csv
import io
from collections import defaultdict
from uuid import UUID

from django.db.models import Max
from django.http import HttpResponse
from ninja import Router, Schema

from apps.accounts.models import bank_account_text
from apps.core.months import month_range
from apps.core.schemas import ErrorOut
from apps.pay.services import Pay, PayRules, amounts_total
from apps.scheduling.models import Assignment, ScheduleVersion
from apps.tenancy.context import tenant_context
from apps.worktime.services import worked_hours

router = Router(tags=["reports"])

ELSEWHERE_NOTE = "pracuje też w lokalach, których nie prowadzisz; suma niepełna"


class LocationColumnOut(Schema):
    id: UUID
    name: str


class LocationHoursOut(Schema):
    location_id: UUID
    hours: float


class EmployeeHoursOut(Schema):
    employee_id: UUID
    name: str
    home_location_name: str
    shifts: int
    # Hours that count: the schedule's, or the approved other hours of a shift (overtime, a shorter shift).
    total: float
    # Of the total: hours above the schedule (approved overtime) and hours below it (shorter shifts), both >= 0.
    longer: float = 0
    shorter: float = 0
    by_location: list[LocationHoursOut]
    # Also worked this month in locations this manager does not run: the total here is not the whole month.
    elsewhere: bool
    # Pay in złoty before tax (hours that count × the shift's rate, plus supplements); None when no shift had a rate.
    pay: float | None = None
    # Of `pay`: the supplements (e.g. for nights).
    supplements_pay: float | None = None
    # Hours on shifts without a rate (not in `pay`).
    unpriced_hours: float = 0
    # Where to send the pay (as written, any bank; "" when the person has not given it).
    bank_account: str = ""


class HoursReportOut(Schema):
    month: str
    locations: list[LocationColumnOut]
    rows: list[EmployeeHoursOut]
    total: float
    # Sum of the people's pay; None when no shift of the month had a rate (the screen then says where to set one).
    pay: float | None = None
    supplements_pay: float | None = None
    unpriced_hours: float = 0
    # The newest month with published shifts ("YYYY-MM"; None: nothing published yet), so an empty month can
    # point there.
    latest_month: str | None


def _report(request, company_id: UUID, month: str) -> HoursReportOut:
    ctx = tenant_context(request, company_id)
    ctx.require_manager()
    first, nxt = month_range(month)
    locations = list(ctx.managed_locations().order_by("name"))
    rows = (
        ctx.qs(Assignment)
        .filter(
            employee__isnull=False,
            shift__version__status=ScheduleVersion.Status.PUBLISHED,
            shift__location__in=locations,
            shift__date__gte=first,
            shift__date__lt=nxt,
        )
        .select_related(
            "shift__version",
            "shift__position",
            "shift__location",
            "employee__membership__user",
            "employee__home_location",
        )
    )
    rows = list(rows)
    worked = worked_hours(rows)
    rules = PayRules(rows)
    pay: dict = defaultdict(Pay)
    seconds: dict = defaultdict(lambda: defaultdict(float))  # summed first, rounded once
    shifts: dict = defaultdict(int)
    longer: dict = defaultdict(int)  # minutes
    shorter: dict = defaultdict(int)
    people = {}
    for assignment in rows:
        shift, counted = assignment.shift, worked[assignment.pk]
        seconds[assignment.employee_id][shift.location_id] += counted.seconds
        rules.add(pay[assignment.employee_id], assignment, counted)
        difference = counted.difference_minutes(shift)
        if difference > 0:
            longer[assignment.employee_id] += difference
        else:
            shorter[assignment.employee_id] -= difference
        shifts[assignment.employee_id] += 1
        people[assignment.employee_id] = assignment.employee
    elsewhere = set(
        ctx.qs(Assignment)
        .filter(
            employee_id__in=list(people),
            shift__version__status=ScheduleVersion.Status.PUBLISHED,
            shift__date__gte=first,
            shift__date__lt=nxt,
        )
        .exclude(shift__location__in=locations)
        .values_list("employee_id", flat=True)
    )
    hours = {
        employee_id: {location_id: value / 3600 for location_id, value in by_location.items()}
        for employee_id, by_location in seconds.items()
    }
    used = [loc for loc in locations if any(loc.pk in h for h in hours.values())]
    result = []
    for employee_id, profile in people.items():
        result.append(
            EmployeeHoursOut(
                employee_id=employee_id,
                name=profile.membership.user.full_name or "Bez imienia",
                home_location_name=profile.home_location.name,
                shifts=shifts[employee_id],
                total=round(sum(hours[employee_id].values()), 2),
                longer=round(longer[employee_id] / 60, 2),
                shorter=round(shorter[employee_id] / 60, 2),
                by_location=[
                    LocationHoursOut(location_id=loc.pk, hours=round(hours[employee_id][loc.pk], 2))
                    for loc in used
                    if hours[employee_id].get(loc.pk)
                ],
                elsewhere=employee_id in elsewhere,
                pay=pay[employee_id].amount,
                supplements_pay=pay[employee_id].supplements,
                unpriced_hours=pay[employee_id].unpriced_hours,
                bank_account=profile.membership.user.bank_account,
            )
        )
    result.sort(key=lambda r: (r.home_location_name, r.name))
    latest = (
        ctx.qs(Assignment)
        .filter(
            employee__isnull=False,
            shift__version__status=ScheduleVersion.Status.PUBLISHED,
            shift__location__in=locations,
        )
        .aggregate(day=Max("shift__date"))["day"]
    )
    return HoursReportOut(
        month=f"{first:%Y-%m}",
        locations=[LocationColumnOut(id=loc.pk, name=loc.name) for loc in used],
        rows=result,
        total=round(sum(r.total for r in result), 2),
        latest_month=f"{latest:%Y-%m}" if latest else None,
        pay=amounts_total(r.pay for r in result),
        supplements_pay=amounts_total(r.supplements_pay for r in result),
        unpriced_hours=round(sum(p.unpriced_seconds for p in pay.values()) / 3600, 2),
    )


@router.get("/reports/hours", response={200: HoursReportOut, 400: ErrorOut, 403: ErrorOut, 404: ErrorOut})
def hours_report(request, company_id: UUID, month: str):
    """Hours of published shifts in a month, per person and location (the locations this manager runs). Approved
    other hours of a shift (overtime, a shorter shift) count instead of the schedule's; `longer`/`shorter` show them.
    `pay` is what to pay before tax (hours × the shift's rate on its day, plus supplements, `supplements_pay` of it);
    hours without a rate are `unpriced_hours`."""
    return _report(request, company_id, month)


FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _text(value: str) -> str:
    """A name a spreadsheet must show as text: a leading = + - @ would make Excel run it as a formula."""
    return "'" + value if value.startswith(FORMULA_START) else value


def _number(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


@router.get("/reports/hours.csv", response={200: str, 400: ErrorOut, 403: ErrorOut, 404: ErrorOut})
def hours_report_csv(request, company_id: UUID, month: str):
    """The same report as a CSV file (semicolons and decimal commas, so a Polish spreadsheet opens it as is)."""
    report = _report(request, company_id, month)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(
        [
            "Osoba",
            "Lokal domowy",
            "Zmiany",
            *[_text(loc.name) for loc in report.locations],
            "Razem",
            "Nadgodziny (ponad grafik)",
            "Krótsze zmiany",
            "Wypłata brutto, zł",
            "W tym dodatki, zł",
            "Godziny bez stawki",
            "Numer konta",
            "Uwagi",
        ]
    )
    for row in report.rows:
        by_location = {h.location_id: h.hours for h in row.by_location}
        writer.writerow(
            [
                _text(row.name),
                _text(row.home_location_name),
                row.shifts,
                *[_number(by_location.get(loc.id, 0.0)) for loc in report.locations],
                _number(row.total),
                _number(row.longer),
                _number(row.shorter),
                _number(row.pay) if row.pay is not None else "",
                _number(row.supplements_pay) if row.supplements_pay is not None else "",
                _number(row.unpriced_hours),
                bank_account_text(row.bank_account),
                ELSEWHERE_NOTE if row.elsewhere else "",
            ]
        )
    response = HttpResponse("﻿" + buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="godziny-{report.month}.csv"'
    return response
