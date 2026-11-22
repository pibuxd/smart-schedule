"""Pay next to the hours: the hours that count (`worktime.services.worked_hours`) times the rate of each shift, plus
the supplements for the part of the shift at a time of day (docs/plan.md, section 35).

The rate of a shift is the person's own rate on the shift's position (`PersonalRate`) on the shift's day, when that
step has an amount; else the position's rate on that day (`PositionRate`); else none. A step counts from its
`valid_from` until the next step, so a new rate never changes the months before it. Hours without a rate are
counted apart (`unpriced_hours`), never as 0 zł, and get no supplement. Amounts are złoty before tax and
contributions: the app knows no contracts.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from django.db.models import F

from apps.pay.models import PaySupplement, PersonalRate, PositionRate
from apps.scheduling.models import Assignment

GROSZ = Decimal("0.01")

Steps = list[tuple[date | None, Decimal | None]]


def step_on(steps: Steps, day: date) -> tuple[date | None, Decimal | None] | None:
    """The step that counts on `day` (steps ordered with "from the start" first), or None before the first one."""
    found = None
    for step in steps:
        if step[0] is not None and step[0] > day:
            break
        found = step
    return found


def seconds_inside(supplement: PaySupplement, start_at: datetime, end_at: datetime, tz: ZoneInfo) -> float:
    """Seconds of [start_at, end_at) inside the supplement's hours on its weekdays, in the location's time."""
    total = 0.0
    day = start_at.astimezone(tz).date() - timedelta(days=1)  # hours that started the day before may run into it
    last = end_at.astimezone(tz).date()
    overnight = supplement.end_time <= supplement.start_time
    while day <= last:
        if supplement.weekdays & (1 << day.weekday()):
            window_start = datetime.combine(day, supplement.start_time, tz)
            window_end = datetime.combine(day + timedelta(days=1) if overnight else day, supplement.end_time, tz)
            overlap = (min(end_at, window_end) - max(start_at, window_start)).total_seconds()
            if overlap > 0:
                total += overlap
        day += timedelta(days=1)
    return total


class PayRules:
    """The rates and supplements for a set of assignments, read once. Needs `shift__location` and `shift__position`
    loaded; the hours come from `worked_hours`."""

    def __init__(self, assignments: Iterable[Assignment]):
        rows = [a for a in assignments if a.employee_id]
        self.position_steps: dict = defaultdict(list)
        self.personal_steps: dict = defaultdict(list)
        self.supplements: dict = defaultdict(list)
        if not rows:
            return
        company = rows[0].company_id
        positions = {a.shift.position_id for a in rows}
        first = F("valid_from").asc(nulls_first=True)
        for position_id, valid_from, rate in (
            PositionRate.objects.for_company(company)
            .filter(position_id__in=positions)
            .order_by("position_id", first)
            .values_list("position_id", "valid_from", "hourly_rate")
        ):
            self.position_steps[position_id].append((valid_from, rate))
        for employee_id, position_id, valid_from, rate in (
            PersonalRate.objects.for_company(company)
            .filter(employee_id__in={a.employee_id for a in rows}, position_id__in=positions)
            .order_by("employee_id", "position_id", first)
            .values_list("employee_id", "position_id", "valid_from", "hourly_rate")
        ):
            self.personal_steps[(employee_id, position_id)].append((valid_from, rate))
        for supplement in (
            PaySupplement.objects.for_company(company)
            .filter(location_id__in={a.shift.location_id for a in rows})
            .prefetch_related("positions")
        ):
            chosen = None if supplement.all_positions else {p.pk for p in supplement.positions.all()}
            self.supplements[supplement.location_id].append((supplement, chosen))

    def rate(self, assignment: Assignment) -> Decimal | None:
        shift = assignment.shift
        own = step_on(self.personal_steps.get((assignment.employee_id, shift.position_id), []), shift.date)
        if own is not None and own[1] is not None:
            return own[1]
        step = step_on(self.position_steps.get(shift.position_id, []), shift.date)
        return step[1] if step is not None else None

    def supplement(self, assignment: Assignment, start_at: datetime, end_at: datetime, rate: Decimal) -> Decimal:
        """Złoty of the supplements for the counted hours of the shift (not rounded)."""
        shift = assignment.shift
        total = Decimal(0)
        tz = None
        for supplement, chosen in self.supplements.get(shift.location_id, []):
            if (chosen is not None and shift.position_id not in chosen) or not supplement.valid_on(shift.date):
                continue
            tz = tz or ZoneInfo(shift.location.timezone)
            seconds = seconds_inside(supplement, start_at, end_at, tz)
            if seconds <= 0:
                continue
            per_hour = supplement.value
            if supplement.kind == PaySupplement.Kind.PERCENT:
                per_hour = rate * supplement.value / 100
            total += Decimal(round(seconds)) * per_hour / 3600
        return total

    def add(self, pay: Pay, assignment: Assignment, worked) -> None:
        """Add one published assignment with its `worktime.services.Worked` hours."""
        rate = self.rate(assignment)
        if rate is None:
            pay.add(worked.seconds, None)
        else:
            pay.add(worked.seconds, rate, self.supplement(assignment, worked.start_at, worked.end_at, rate))


def _grosz(value: Decimal) -> Decimal:
    return value.quantize(GROSZ, rounding=ROUND_HALF_UP)


@dataclass
class Pay:
    """The pay of one person (or one month): add every shift, then read the amounts once, rounded to the grosz."""

    base: Decimal = Decimal(0)
    extra: Decimal = Decimal(0)
    priced: bool = False
    unpriced_seconds: float = 0

    def add(self, seconds: float, rate: Decimal | None, extra: Decimal = Decimal(0)) -> None:
        if rate is None:
            self.unpriced_seconds += seconds
            return
        self.base += Decimal(round(seconds)) * rate / 3600
        self.extra += extra
        self.priced = True

    @property
    def amount(self) -> float | None:
        """Złoty with the supplements; None when no hour had a rate (the screens then show no pay at all)."""
        return float(_grosz(self.base) + _grosz(self.extra)) if self.priced else None

    @property
    def supplements(self) -> float | None:
        """The part of `amount` that comes from supplements."""
        return float(_grosz(self.extra)) if self.priced else None

    @property
    def unpriced_hours(self) -> float:
        return round(self.unpriced_seconds / 3600, 2)


def amounts_total(amounts: Iterable[float | None]) -> float | None:
    """The sum of already rounded amounts (so a table adds up), None when none of them is known."""
    known = [Decimal(str(a)) for a in amounts if a is not None]
    return float(sum(known, Decimal(0))) if known else None
