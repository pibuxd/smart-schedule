"""What hours pay (docs/plan.md, section 35): hourly rates of positions and people's own rates on a position, each
from a day on, and supplements for hours at a time of day on chosen weekdays (e.g. nights). Only for the pay next to
the hours; the generator, the validator and the scores never read them."""

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from apps.staffing.models import EmployeeProfile, Position
from apps.tenancy.base import CompanyOwnedModel
from apps.tenancy.models import Location

RATE_POSITIVE = Q(hourly_rate__isnull=True) | Q(hourly_rate__gt=0)
ALL_WEEKDAYS = 0b1111111  # bit 0 = Monday … bit 6 = Sunday


def _rate_field() -> models.DecimalField:
    return models.DecimalField(
        "stawka za godzinę",
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0.01)],
    )


class PositionRate(CompanyOwnedModel):
    """The hourly rate of a position from `valid_from` on (None = from the start: the first rate counts for every
    shift). Each day the rate changes has one row; an empty rate means "no rate" from that day."""

    company_from = "position"

    position = models.ForeignKey(Position, on_delete=models.CASCADE, related_name="rates")
    valid_from = models.DateField("od dnia", null=True, blank=True)
    hourly_rate = _rate_field()

    class Meta:
        verbose_name = "stawka stanowiska"
        verbose_name_plural = "stawki stanowisk"
        ordering = ["position", models.F("valid_from").asc(nulls_first=True)]
        constraints = [
            models.UniqueConstraint(
                fields=["position", "valid_from"], nulls_distinct=False, name="position_rate_one_per_day"
            ),
            models.CheckConstraint(condition=RATE_POSITIVE, name="position_rate_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.position.name}: {self.hourly_rate or 'bez stawki'} od {self.valid_from or 'początku'}"


class PersonalRate(CompanyOwnedModel):
    """A person's own hourly rate on one position from `valid_from` on, instead of the position's: someone with a
    longer record at the oven earns more there. An empty rate means the position's rate again from that day. Set by
    the manager of the position's location; kept when the person loses the position, for their past shifts."""

    company_from = "employee"

    employee = models.ForeignKey(EmployeeProfile, on_delete=models.CASCADE, related_name="personal_rates")
    position = models.ForeignKey(Position, on_delete=models.CASCADE, related_name="personal_rates")
    valid_from = models.DateField("od dnia", null=True, blank=True)
    hourly_rate = _rate_field()

    class Meta:
        verbose_name = "stawka osoby na stanowisku"
        verbose_name_plural = "stawki osób na stanowiskach"
        ordering = ["employee", "position", models.F("valid_from").asc(nulls_first=True)]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "position", "valid_from"], nulls_distinct=False, name="personal_rate_one_per_day"
            ),
            models.CheckConstraint(condition=RATE_POSITIVE, name="personal_rate_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.employee}: {self.position.name} – {self.hourly_rate or 'stawka stanowiska'}"


class PaySupplement(CompanyOwnedModel):
    """Extra pay for the part of a shift between `start_time` and `end_time` on chosen weekdays, e.g. nights
    22:00–06:00 +6 zł an hour. An end at or before the start runs past midnight; equal times are the whole day. The
    weekday is the day the hours start. A change of the amount or the hours ends this row the day before and starts
    a new one, so past months keep what they paid."""

    company_from = "location"

    class Kind(models.TextChoices):
        AMOUNT = "amount", "zł za godzinę"
        PERCENT = "percent", "procent stawki"

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="pay_supplements")
    name = models.CharField("nazwa", max_length=60)
    start_time = models.TimeField("od godziny")
    end_time = models.TimeField("do godziny")
    weekdays = models.PositiveSmallIntegerField("dni tygodnia (bity, 0 = poniedziałek)", default=ALL_WEEKDAYS)
    kind = models.CharField("rodzaj", max_length=10, choices=Kind.choices, default=Kind.AMOUNT)
    value = models.DecimalField("kwota albo procent", max_digits=7, decimal_places=2)
    # Every position of the location, or only `positions` (kept apart, so deleting the only chosen position never
    # turns the supplement into one for everybody).
    all_positions = models.BooleanField("wszystkie stanowiska", default=True)
    positions = models.ManyToManyField(Position, blank=True, related_name="+", verbose_name="stanowiska")
    valid_from = models.DateField("od dnia", null=True, blank=True)
    valid_until = models.DateField("do dnia", null=True, blank=True)

    class Meta:
        verbose_name = "dodatek"
        verbose_name_plural = "dodatki"
        ordering = ["location", "start_time", "name"]
        constraints = [
            models.CheckConstraint(condition=Q(value__gt=0), name="supplement_value_positive"),
            models.CheckConstraint(condition=Q(weekdays__gte=1, weekdays__lte=ALL_WEEKDAYS), name="supplement_days"),
            models.CheckConstraint(
                condition=Q(valid_from__isnull=True)
                | Q(valid_until__isnull=True)
                | Q(valid_until__gte=models.F("valid_from")),
                name="supplement_dates_in_order",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.location})"

    def weekday_list(self) -> list[int]:
        return [day for day in range(7) if self.weekdays & (1 << day)]

    def valid_on(self, day) -> bool:
        return (self.valid_from is None or self.valid_from <= day) and (
            self.valid_until is None or day <= self.valid_until
        )
