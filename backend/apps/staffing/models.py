"""Location settings: positions, shift types, staffing, and employee profiles."""

from django.db import models
from django.db.models import Q

from apps.tenancy.base import CompanyOwnedModel
from apps.tenancy.models import Location, Membership


class Weekday(models.IntegerChoices):
    MONDAY = 0, "poniedziałek"
    TUESDAY = 1, "wtorek"
    WEDNESDAY = 2, "środa"
    THURSDAY = 3, "czwartek"
    FRIDAY = 4, "piątek"
    SATURDAY = 5, "sobota"
    SUNDAY = 6, "niedziela"


WEEKDAY_RANGE = Q(weekday__gte=0, weekday__lte=6)


class Position(CompanyOwnedModel):
    company_from = "location"

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="positions")
    name = models.CharField("nazwa", max_length=100)

    class Meta:
        verbose_name = "stanowisko"
        verbose_name_plural = "stanowiska"
        ordering = ["location", "name"]
        constraints = [models.UniqueConstraint(fields=["location", "name"], name="position_unique_name")]

    def __str__(self) -> str:
        return f"{self.name} ({self.location})"


class ShiftType(CompanyOwnedModel):
    """A shift with fixed hours, or with flexible hours given in staffing/exceptions. End before start = overnight."""

    class Kind(models.TextChoices):
        FIXED = "fixed", "stałe godziny"
        FLEXIBLE = "flexible", "dowolne godziny"

    company_from = "location"

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="shift_types")
    name = models.CharField("nazwa", max_length=100)
    kind = models.CharField("rodzaj", max_length=16, choices=Kind.choices, default=Kind.FIXED)
    start_time = models.TimeField("początek", null=True, blank=True)
    end_time = models.TimeField("koniec", null=True, blank=True)
    is_closing = models.BooleanField("zmiana zamykająca", default=False)

    class Meta:
        verbose_name = "typ zmiany"
        verbose_name_plural = "typy zmian"
        ordering = ["location", "start_time"]
        constraints = [
            models.UniqueConstraint(fields=["location", "name"], name="shift_type_unique_name"),
            models.CheckConstraint(
                condition=Q(kind="flexible")
                | (Q(start_time__isnull=False, end_time__isnull=False) & ~Q(start_time=models.F("end_time"))),
                name="shift_type_fixed_has_hours",
            ),
        ]

    def __str__(self) -> str:
        if self.start_time and self.end_time:
            return f"{self.name} {self.start_time:%H:%M}–{self.end_time:%H:%M}"
        return self.name

    @property
    def is_overnight(self) -> bool:
        return bool(self.start_time and self.end_time and self.end_time < self.start_time)


class StaffingRule(CompanyOwnedModel):
    """How many people of a position a shift needs on a weekday. Hours only for flexible shift types."""

    company_from = "location"

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="staffing_rules")
    weekday = models.PositiveSmallIntegerField("dzień tygodnia", choices=Weekday.choices)
    shift_type = models.ForeignKey(ShiftType, on_delete=models.CASCADE, related_name="staffing_rules")
    position = models.ForeignKey(Position, on_delete=models.CASCADE, related_name="staffing_rules")
    count = models.PositiveSmallIntegerField("liczba osób")
    start_time = models.TimeField("początek (dowolne godziny)", null=True, blank=True)
    end_time = models.TimeField("koniec (dowolne godziny)", null=True, blank=True)

    class Meta:
        verbose_name = "obsada"
        verbose_name_plural = "obsada"
        ordering = ["location", "weekday", "shift_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["location", "weekday", "shift_type", "position"], name="staffing_rule_unique_slot"
            ),
            models.CheckConstraint(condition=WEEKDAY_RANGE, name="staffing_rule_weekday_range"),
            models.CheckConstraint(
                condition=Q(start_time__isnull=True, end_time__isnull=True)
                | Q(start_time__isnull=False, end_time__isnull=False),
                name="staffing_rule_hours_both_or_none",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_weekday_display()}: {self.shift_type.name} – {self.position.name} × {self.count}"


class StaffingException(CompanyOwnedModel):
    """Staffing on a specific date that replaces the weekday rule (e.g. Christmas Eve, count 0 = closed)."""

    company_from = "location"

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="staffing_exceptions")
    date = models.DateField("data")
    shift_type = models.ForeignKey(ShiftType, on_delete=models.CASCADE, related_name="staffing_exceptions")
    position = models.ForeignKey(Position, on_delete=models.CASCADE, related_name="staffing_exceptions")
    count = models.PositiveSmallIntegerField("liczba osób")
    start_time = models.TimeField("inny początek", null=True, blank=True)
    end_time = models.TimeField("inny koniec", null=True, blank=True)
    note = models.CharField("powód", max_length=200, blank=True)

    class Meta:
        verbose_name = "wyjątek w obsadzie"
        verbose_name_plural = "wyjątki w obsadzie"
        ordering = ["location", "date"]
        constraints = [
            models.UniqueConstraint(
                fields=["location", "date", "shift_type", "position"], name="staffing_exception_unique_slot"
            ),
            models.CheckConstraint(
                condition=Q(start_time__isnull=True, end_time__isnull=True)
                | Q(start_time__isnull=False, end_time__isnull=False),
                name="staffing_exception_hours_both_or_none",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.date}: {self.shift_type.name} – {self.position.name} × {self.count}"


class EmployeeProfile(CompanyOwnedModel):
    """A person who can be put in the schedule. A manager may have one too (e.g. a manager on a shift)."""

    company_from = "membership"

    membership = models.OneToOneField(Membership, on_delete=models.CASCADE, related_name="employee_profile")
    home_location = models.ForeignKey(
        Location, on_delete=models.RESTRICT, related_name="employees", verbose_name="lokal domowy"
    )
    positions = models.ManyToManyField(Position, blank=True, related_name="employees", verbose_name="stanowiska")
    max_hours_month = models.PositiveSmallIntegerField("maks. godzin w miesiącu", null=True, blank=True)
    target_hours_month = models.PositiveSmallIntegerField("cel godzin w miesiącu", null=True, blank=True)
    is_active = models.BooleanField("aktywny", default=True)

    class Meta:
        verbose_name = "pracownik"
        verbose_name_plural = "pracownicy"
        constraints = [
            models.CheckConstraint(
                condition=Q(max_hours_month__isnull=True)
                | Q(target_hours_month__isnull=True)
                | Q(target_hours_month__lte=models.F("max_hours_month")),
                name="employee_target_le_max_hours",
            ),
        ]

    def __str__(self) -> str:
        return str(self.membership.user)
