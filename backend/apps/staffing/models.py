"""Location settings: positions, shift types, staffing, and employee profiles."""

from django.core.validators import MinValueValidator
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


def hourly_rate_field(verbose_name: str) -> models.DecimalField:
    """Złoty per hour before tax (an estimate of pay, docs/plan.md section 35); empty = no rate."""
    return models.DecimalField(
        verbose_name,
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0.01)],
    )


RATE_POSITIVE = Q(hourly_rate__isnull=True) | Q(hourly_rate__gt=0)


class Position(CompanyOwnedModel):
    company_from = "location"

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="positions")
    name = models.CharField("nazwa", max_length=100)
    # What an hour on this position pays (a person may have their own rate here, `PersonalRate`). Only for the
    # estimate of pay next to the hours; the generator never reads it.
    hourly_rate = hourly_rate_field("stawka za godzinę")
    # A position used in a saved schedule cannot be deleted, so "Usuń" hides it instead: it leaves staffing,
    # people and every list, and only old schedules still show its name. Read live positions with `removed_at=None`.
    removed_at = models.DateTimeField("usunięte", null=True, blank=True)

    class Meta:
        verbose_name = "stanowisko"
        verbose_name_plural = "stanowiska"
        ordering = ["location", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["location", "name"], condition=Q(removed_at__isnull=True), name="position_unique_name"
            ),
            models.CheckConstraint(condition=RATE_POSITIVE, name="position_rate_positive"),
        ]

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
    # How many of `count` must be experienced on this position (hard, like the position itself).
    experienced = models.PositiveSmallIntegerField("w tym doświadczonych", default=0)
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
                condition=Q(experienced__lte=models.F("count")), name="staffing_rule_experienced_le_count"
            ),
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
    experienced = models.PositiveSmallIntegerField("w tym doświadczonych", default=0)
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
                condition=Q(experienced__lte=models.F("count")), name="staffing_exception_experienced_le_count"
            ),
            models.CheckConstraint(
                condition=Q(start_time__isnull=True, end_time__isnull=True)
                | Q(start_time__isnull=False, end_time__isnull=False),
                name="staffing_exception_hours_both_or_none",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.date}: {self.shift_type.name} – {self.position.name} × {self.count}"


class LocationClosure(CompanyOwnedModel):
    """A day the location is closed: nobody is scheduled there, whatever the staffing table says."""

    company_from = "location"

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="closures")
    date = models.DateField("data")
    note = models.CharField("powód", max_length=200, blank=True)

    class Meta:
        verbose_name = "dzień zamknięcia"
        verbose_name_plural = "dni zamknięcia"
        ordering = ["location", "date"]
        constraints = [models.UniqueConstraint(fields=["location", "date"], name="location_closure_unique_day")]

    def __str__(self) -> str:
        return f"{self.location.name}: zamknięte {self.date}"


class Experience(models.IntegerChoices):
    """Set by the manager, never shown to the employee; used by the rule experience_mix."""

    BEGINNER = 1, "początkujący"
    SKILLED = 2, "samodzielny"
    EXPERIENCED = 3, "doświadczony"


class EmployeeProfile(CompanyOwnedModel):
    """A person who can be put in the schedule. A manager may have one too (e.g. a manager on a shift)."""

    company_from = "membership"

    membership = models.OneToOneField(Membership, on_delete=models.CASCADE, related_name="employee_profile")
    home_location = models.ForeignKey(
        Location, on_delete=models.RESTRICT, related_name="employees", verbose_name="lokal domowy"
    )
    # Other locations of the company where the person also works (docs/plan.md, section 27). The generator of each of
    # them may put the person in; availability and hours are shared.
    extra_locations = models.ManyToManyField(
        Location, blank=True, related_name="extra_employees", verbose_name="lokale dodatkowe"
    )
    positions = models.ManyToManyField(Position, blank=True, related_name="employees", verbose_name="stanowiska")
    experience = models.PositiveSmallIntegerField(
        "stopień doświadczenia", choices=Experience.choices, default=Experience.SKILLED
    )
    max_hours_month = models.PositiveSmallIntegerField("maks. godzin w miesiącu", null=True, blank=True)
    target_hours_month = models.PositiveSmallIntegerField("cel godzin w miesiącu", null=True, blank=True)
    is_active = models.BooleanField("aktywny", default=True)
    # Removed from the location by a manager, but kept because old schedules point at the person (always with
    # `is_active=False`). Hidden from every list; a plain employee loses access to the company until invited again.
    removed_at = models.DateTimeField("usunięty z lokalu", null=True, blank=True)

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
            models.CheckConstraint(condition=Q(experience__gte=1, experience__lte=3), name="employee_experience_level"),
            models.CheckConstraint(
                condition=Q(removed_at__isnull=True) | Q(is_active=False), name="employee_removed_is_inactive"
            ),
        ]

    def __str__(self) -> str:
        return str(self.membership.user)

    def location_ids(self) -> set:
        """The main location and every extra one."""
        return {self.home_location_id, *self.extra_locations.values_list("pk", flat=True)}

    def works_in(self, location) -> bool:
        location_id = getattr(location, "pk", location)
        return self.home_location_id == location_id or self.extra_locations.filter(pk=location_id).exists()


def works_in_q(locations, prefix: str = "") -> Q:
    """People (EmployeeProfile, or a model with `prefix` + "home_location") working in any of `locations`:
    as their main location or an extra one. A subquery, so there are no duplicate rows."""
    ids = [getattr(loc, "pk", loc) for loc in locations] if isinstance(locations, list | tuple | set) else None
    if ids is None:
        ids = [getattr(locations, "pk", locations)]
    extra = EmployeeProfile.extra_locations.through.objects.filter(location_id__in=ids).values("employeeprofile_id")
    pk = f"{prefix}pk" if prefix else "pk"
    return Q(**{f"{prefix}home_location__in": ids}) | Q(**{f"{pk}__in": extra})


class PositionExperience(CompanyOwnedModel):
    """A level on one position that differs from the person's default (`EmployeeProfile.experience`):
    someone experienced at the oven can be a beginner at the till. Rows equal to the default are not kept."""

    company_from = "employee"

    employee = models.ForeignKey(EmployeeProfile, on_delete=models.CASCADE, related_name="position_levels")
    position = models.ForeignKey(Position, on_delete=models.CASCADE, related_name="employee_levels")
    level = models.PositiveSmallIntegerField("stopień na stanowisku", choices=Experience.choices)

    class Meta:
        verbose_name = "stopień na stanowisku"
        verbose_name_plural = "stopnie na stanowiskach"
        constraints = [
            models.UniqueConstraint(fields=["employee", "position"], name="position_experience_unique"),
            models.CheckConstraint(condition=Q(level__gte=1, level__lte=3), name="position_experience_level"),
        ]

    def __str__(self) -> str:
        return f"{self.employee}: {self.position.name} – {self.get_level_display()}"


class PersonalRate(CompanyOwnedModel):
    """A person's own hourly rate on one position, instead of the position's (`Position.hourly_rate`): someone
    experienced may earn more at the till than the till's usual rate. No row = the position's rate. Set by the
    manager of the position's location, like the person's positions there."""

    company_from = "employee"

    employee = models.ForeignKey(EmployeeProfile, on_delete=models.CASCADE, related_name="personal_rates")
    position = models.ForeignKey(Position, on_delete=models.CASCADE, related_name="personal_rates")
    hourly_rate = models.DecimalField(
        "stawka za godzinę", max_digits=7, decimal_places=2, validators=[MinValueValidator(0.01)]
    )

    class Meta:
        verbose_name = "stawka osoby na stanowisku"
        verbose_name_plural = "stawki osób na stanowiskach"
        constraints = [
            models.UniqueConstraint(fields=["employee", "position"], name="personal_rate_unique"),
            models.CheckConstraint(condition=Q(hourly_rate__gt=0), name="personal_rate_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.employee}: {self.position.name} – {self.hourly_rate} zł/h"
