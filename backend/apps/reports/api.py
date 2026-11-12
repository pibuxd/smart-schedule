"""Hours worked in a month, from published schedules, split by location; also as a CSV file for payroll."""

import csv
import io
from collections import defaultdict
from datetime import date
from uuid import UUID

from django.http import HttpResponse
from ninja import Router, Schema
from ninja.errors import HttpError

from apps.core.schemas import ErrorOut
from apps.scheduling.models import Assignment, ScheduleVersion
from apps.tenancy.context import tenant_context

router = Router(tags=["reports"])

CONTRACT_WORDS = {"civil": "umowa zlecenie", "employment": "umowa o pracę"}


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
    contract: str
    shifts: int
    total: float
    by_location: list[LocationHoursOut]


class HoursReportOut(Schema):
    month: str
    locations: list[LocationColumnOut]
    rows: list[EmployeeHoursOut]
    total: float


def _month(value: str) -> tuple[date, date]:
    try:
        first = date.fromisoformat(f"{value}-01")
    except ValueError:
        raise HttpError(400, "Podaj miesiąc w postaci RRRR-MM, np. 2026-12.") from None
    nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return first, nxt


def _report(request, company_id: UUID, month: str) -> HoursReportOut:
    ctx = tenant_context(request, company_id)
    ctx.require_manager()
    first, nxt = _month(month)
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
        .select_related("shift", "employee__membership__user", "employee__home_location")
    )
    hours: dict = defaultdict(lambda: defaultdict(float))
    shifts: dict = defaultdict(int)
    people = {}
    for assignment in rows:
        shift = assignment.shift
        hours[assignment.employee_id][shift.location_id] += (shift.end_at - shift.start_at).total_seconds() / 3600
        shifts[assignment.employee_id] += 1
        people[assignment.employee_id] = assignment.employee
    used = [loc for loc in locations if any(loc.pk in h for h in hours.values())]
    result = []
    for employee_id, profile in people.items():
        result.append(
            EmployeeHoursOut(
                employee_id=employee_id,
                name=profile.membership.user.full_name or "Bez imienia",
                home_location_name=profile.home_location.name,
                contract=profile.contract,
                shifts=shifts[employee_id],
                total=round(sum(hours[employee_id].values()), 2),
                by_location=[
                    LocationHoursOut(location_id=loc.pk, hours=round(hours[employee_id][loc.pk], 2))
                    for loc in used
                    if hours[employee_id].get(loc.pk)
                ],
            )
        )
    result.sort(key=lambda r: (r.home_location_name, r.name))
    return HoursReportOut(
        month=f"{first:%Y-%m}",
        locations=[LocationColumnOut(id=loc.pk, name=loc.name) for loc in used],
        rows=result,
        total=round(sum(r.total for r in result), 2),
    )


@router.get("/reports/hours", response={200: HoursReportOut, 400: ErrorOut, 403: ErrorOut, 404: ErrorOut})
def hours_report(request, company_id: UUID, month: str):
    """Hours of published shifts in a month, per person and location (the locations this manager runs)."""
    return _report(request, company_id, month)


def _number(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


@router.get("/reports/hours.csv", response={200: str, 400: ErrorOut, 403: ErrorOut, 404: ErrorOut})
def hours_report_csv(request, company_id: UUID, month: str):
    """The same report as a CSV file (semicolons and decimal commas, so a Polish spreadsheet opens it as is)."""
    report = _report(request, company_id, month)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["Osoba", "Lokal domowy", "Umowa", "Zmiany", *[loc.name for loc in report.locations], "Razem"])
    for row in report.rows:
        by_location = {h.location_id: h.hours for h in row.by_location}
        writer.writerow(
            [
                row.name,
                row.home_location_name,
                CONTRACT_WORDS.get(row.contract, row.contract),
                row.shifts,
                *[_number(by_location.get(loc.id, 0.0)) for loc in report.locations],
                _number(row.total),
            ]
        )
    response = HttpResponse("﻿" + buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="godziny-{report.month}.csv"'
    return response
