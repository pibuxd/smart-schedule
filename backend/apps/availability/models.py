"""Availability marked in the calendar, weekly patterns, submissions and text requests."""

from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.scheduling.models import SchedulePeriod
from apps.staffing.models import WEEKDAY_RANGE, EmployeeProfile, Weekday
from apps.tenancy.base import CompanyOwnedModel


class AvailabilityState(models.TextChoices):
    CANNOT = "cannot", "nie mogę"
    PREFER_NOT = "prefer_not", "wolę nie"
    NEUTRAL = "neutral", "obojętnie"
    PREFER = "prefer", "chętnie"


HOURS_IN_ORDER = Q(from_time__isnull=True) | Q(to_time__isnull=True) | Q(from_time__lt=models.F("to_time"))


class AvailabilityDay(CompanyOwnedModel):
    """State for one employee and day; optional hours ("chętnie od 14:00"). No row = nothing submitted."""

    class Source(models.TextChoices):
        MANUAL = "manual", "ręcznie"
        PATTERN = "pattern", "co tydzień"
        COPY = "copy", "skopiowane"

    company_from = "employee"

    employee = models.ForeignKey(EmployeeProfile, on_delete=models.CASCADE, related_name="availability_days")
    date = models.DateField()
    state = models.CharField(max_length=16, choices=AvailabilityState.choices)
    from_time = models.TimeField(null=True, blank=True)
    to_time = models.TimeField(null=True, blank=True)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.MANUAL)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "dyspozycyjność"
        verbose_name_plural = "dyspozycyjność"
        ordering = ["employee", "date"]
        constraints = [
            models.UniqueConstraint(fields=["employee", "date"], name="availability_day_unique"),
            models.CheckConstraint(condition=HOURS_IN_ORDER, name="availability_day_hours_in_order"),
        ]

    def __str__(self) -> str:
        return f"{self.employee} {self.date}: {self.get_state_display()}"


class AvailabilityPattern(CompanyOwnedModel):
    """ "Repeat every week until [date]"; expanded into AvailabilityDay rows when saved (stage 6)."""

    company_from = "employee"

    employee = models.ForeignKey(EmployeeProfile, on_delete=models.CASCADE, related_name="availability_patterns")
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    state = models.CharField(max_length=16, choices=AvailabilityState.choices)
    from_time = models.TimeField(null=True, blank=True)
    to_time = models.TimeField(null=True, blank=True)
    repeat_until = models.DateField("powtarzaj do")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "powtarzana dyspozycyjność"
        verbose_name_plural = "powtarzana dyspozycyjność"
        constraints = [
            models.CheckConstraint(condition=WEEKDAY_RANGE, name="availability_pattern_weekday_range"),
            models.CheckConstraint(condition=HOURS_IN_ORDER, name="availability_pattern_hours_in_order"),
        ]


class AvailabilitySubmission(CompanyOwnedModel):
    """Marks that an employee finished their availability for a period (for "who has not submitted")."""

    company_from = "employee"

    employee = models.ForeignKey(EmployeeProfile, on_delete=models.CASCADE, related_name="submissions")
    period = models.ForeignKey(SchedulePeriod, on_delete=models.CASCADE, related_name="submissions")
    submitted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "zgłoszona dyspozycyjność"
        verbose_name_plural = "zgłoszone dyspozycyjności"
        constraints = [models.UniqueConstraint(fields=["employee", "period"], name="submission_unique")]


class TextRequest(CompanyOwnedModel):
    """A request written as text. Seen only by managers. Interpretation by the LLM arrives in stage 10."""

    class Status(models.TextChoices):
        NEW = "new", "nowa"
        INTERPRETED = "interpreted", "zrozumiana"
        NEEDS_MANAGER = "needs_manager", "do decyzji menedżera"
        REJECTED = "rejected", "odrzucona"

    class ManagerPriority(models.TextChoices):
        LOWER = "lower", "mniej ważna"
        NORMAL = "normal", "zwykła"
        HIGHER = "higher", "ważniejsza"

    company_from = "employee"

    employee = models.ForeignKey(EmployeeProfile, on_delete=models.CASCADE, related_name="text_requests")
    period = models.ForeignKey(SchedulePeriod, on_delete=models.CASCADE, related_name="text_requests")
    text = models.TextField("treść", max_length=1000)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW)
    interpretation = models.JSONField(
        "interpretacja",
        null=True,
        blank=True,
        help_text="type, subject_employee, dates, level, confidence, summary",
    )
    employee_corrected = models.BooleanField("poprawiona przez pracownika", default=False)
    manager_priority = models.CharField(
        "ważność wg menedżera", max_length=8, choices=ManagerPriority.choices, default=ManagerPriority.NORMAL
    )
    manager_rejected = models.BooleanField("odrzucona przez menedżera", default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "prośba"
        verbose_name_plural = "prośby"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["period", "status"])]

    def __str__(self) -> str:
        return f"{self.employee}: {self.text[:60]}"
