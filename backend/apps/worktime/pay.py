"""Estimated pay: the hours that count (`services.worked_hours`) times the hourly rate of each shift.

A shift's rate is the person's own rate on its position (`staffing.PersonalRate`), else the position's
(`Position.hourly_rate`). Hours with neither are counted apart (`unpriced_hours`), never as 0 zł. Rates are read as
they are now, so a new rate changes past months too (docs/plan.md, section 35). Amounts are złoty before tax and
contributions: the app knows no contracts, so this is only an estimate.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from apps.scheduling.models import Assignment
from apps.staffing.models import PersonalRate

GROSZ = Decimal("0.01")


def shift_rates(assignments: Iterable[Assignment]) -> dict:
    """assignment id -> the hourly rate of the shift for its person (Decimal), or None without one.
    Needs `shift__position` loaded."""
    rows = [a for a in assignments if a.employee_id]
    if not rows:
        return {}
    personal = {
        (employee_id, position_id): rate
        for employee_id, position_id, rate in PersonalRate.objects.for_company(rows[0].company_id)
        .filter(employee_id__in={a.employee_id for a in rows}, position_id__in={a.shift.position_id for a in rows})
        .values_list("employee_id", "position_id", "hourly_rate")
    }
    return {a.pk: personal.get((a.employee_id, a.shift.position_id), a.shift.position.hourly_rate) for a in rows}


@dataclass
class Pay:
    """The pay of one person (or one month): add every shift, then read the total once, rounded to the grosz."""

    total: Decimal = Decimal(0)
    priced: bool = False
    unpriced_seconds: float = 0

    def add(self, seconds: float, rate: Decimal | None) -> None:
        if rate is None:
            self.unpriced_seconds += seconds
            return
        self.total += Decimal(round(seconds)) * rate / 3600
        self.priced = True

    @property
    def amount(self) -> float | None:
        """Złoty, rounded to the grosz; None when no hour had a rate (the screens then show no pay at all)."""
        return float(self.total.quantize(GROSZ, rounding=ROUND_HALF_UP)) if self.priced else None

    @property
    def unpriced_hours(self) -> float:
        return round(self.unpriced_seconds / 3600, 2)


def amounts_total(amounts: Iterable[float | None]) -> float | None:
    """The sum of already rounded amounts (so a table adds up), None when none of them is known."""
    known = [Decimal(str(a)) for a in amounts if a is not None]
    return float(sum(known, Decimal(0))) if known else None
