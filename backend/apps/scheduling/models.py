"""Schedule periods, versions, shifts (slots), assignments, their history, and generation runs."""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.staffing.models import EmployeeProfile, Position, ShiftType
from apps.tenancy.base import CompanyOwnedModel, exactly_one_scope_constraint
from apps.tenancy.models import Location, LocationGroup


class SchedulePeriod(CompanyOwnedModel):
    class Status(models.TextChoices):
        COLLECTING = "collecting", "zbieranie dyspozycji"
        DRAFT = "draft", "szkic"
        PUBLISHED = "published", "opublikowany"

    company_from = "location"

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="periods")
    start = models.DateField("od")
    end = models.DateField("do")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.COLLECTING)

    class Meta:
        verbose_name = "okres grafiku"
        verbose_name_plural = "okresy grafiku"
        ordering = ["location", "-start"]
        constraints = [
            models.UniqueConstraint(fields=["location", "start"], name="period_unique_start"),
            models.CheckConstraint(condition=Q(end__gte=models.F("start")), name="period_end_after_start"),
        ]

    def __str__(self) -> str:
        return f"{self.location}: {self.start:%d.%m}–{self.end:%d.%m.%Y}"


class GenerationRun(CompanyOwnedModel):
    """One solver job for a location or a whole group. Each resulting version points back via `from_run`."""

    class Status(models.TextChoices):
        QUEUED = "queued", "w kolejce"
        RUNNING = "running", "w trakcie"
        SUCCEEDED = "succeeded", "gotowe"
        FAILED = "failed", "błąd"

    class SolverStatus(models.TextChoices):
        OPTIMAL = "optimal", "optymalny"
        FEASIBLE = "feasible", "dopuszczalny"
        TIMEOUT_NO_SOLUTION = "timeout_no_solution", "brak rozwiązania w limicie czasu"

    company_from = "location"

    location = models.ForeignKey(Location, on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    group = models.ForeignKey(LocationGroup, on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    periods = models.ManyToManyField(SchedulePeriod, related_name="generation_runs")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    solver_status = models.CharField(max_length=24, choices=SolverStatus.choices, blank=True)
    time_ms = models.PositiveIntegerField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        verbose_name = "generowanie grafiku"
        verbose_name_plural = "generowania grafiku"
        ordering = ["-created_at"]
        constraints = [exactly_one_scope_constraint("generation_run_one_scope")]

    def _fill_company(self) -> None:
        if self.company_id is None and self.group_id is not None:
            self.company_id = self.group.company_id
        super()._fill_company()


class ScheduleVersion(CompanyOwnedModel):
    """Publishing creates a new version; older ones stay as history (superseded)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "szkic"
        PUBLISHED = "published", "opublikowana"
        SUPERSEDED = "superseded", "zastąpiona"

    company_from = "period"

    period = models.ForeignKey(SchedulePeriod, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField("numer")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    from_run = models.ForeignKey(
        GenerationRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="versions"
    )
    scores = models.JSONField("ocena", default=dict, blank=True)
    is_complete = models.BooleanField("kompletny (bez dziur)", default=False)
    created_at = models.DateTimeField(default=timezone.now)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "wersja grafiku"
        verbose_name_plural = "wersje grafiku"
        ordering = ["period", "-number"]
        constraints = [
            models.UniqueConstraint(fields=["period", "number"], name="version_unique_number"),
            models.UniqueConstraint(
                fields=["period"], condition=Q(status="published"), name="version_one_published_per_period"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.period} v{self.number} ({self.get_status_display()})"


class Shift(CompanyOwnedModel):
    """One staffing slot (one seat). Hours are copied so later setting changes do not alter old schedules."""

    company_from = "version"

    version = models.ForeignKey(ScheduleVersion, on_delete=models.CASCADE, related_name="shifts")
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="+")
    date = models.DateField()
    shift_type = models.ForeignKey(ShiftType, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    position = models.ForeignKey(Position, on_delete=models.PROTECT, related_name="+")
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    slot_key = models.CharField(
        max_length=120, help_text="Stały klucz miejsca (data, zmiana, stanowisko, numer) między wersjami."
    )

    class Meta:
        verbose_name = "zmiana"
        verbose_name_plural = "zmiany"
        ordering = ["date", "start_at"]
        indexes = [models.Index(fields=["location", "date"])]
        constraints = [
            models.UniqueConstraint(fields=["version", "slot_key"], name="shift_unique_slot_in_version"),
            models.CheckConstraint(condition=Q(end_at__gt=models.F("start_at")), name="shift_end_after_start"),
        ]

    def __str__(self) -> str:
        return f"{self.date} {self.start_at:%H:%M}–{self.end_at:%H:%M} {self.position.name}"


class Assignment(CompanyOwnedModel):
    """Who works a slot. `employee` empty = an unfilled slot (a hole)."""

    company_from = "shift"

    shift = models.OneToOneField(Shift, on_delete=models.CASCADE, related_name="assignment")
    employee = models.ForeignKey(
        EmployeeProfile, on_delete=models.PROTECT, null=True, blank=True, related_name="assignments"
    )
    pinned = models.BooleanField("przypięte", default=False)
    borrowed = models.BooleanField("z innego lokalu", default=False)

    class Meta:
        verbose_name = "przypisanie"
        verbose_name_plural = "przypisania"
        constraints = [
            models.CheckConstraint(
                condition=Q(employee__isnull=False) | Q(pinned=False), name="assignment_hole_not_pinned"
            ),
        ]


class AssignmentEvent(CompanyOwnedModel):
    """History of who held a slot; the basis for shift swaps later."""

    class Reason(models.TextChoices):
        GENERATED = "generated", "generator"
        MANUAL = "manual", "ręczna zmiana"
        OFFER = "offer", "oddana zmiana"
        SWAP = "swap", "zamiana"

    company_from = "location"

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="+")
    period = models.ForeignKey(SchedulePeriod, on_delete=models.CASCADE, related_name="assignment_events")
    slot_key = models.CharField(max_length=120)
    from_employee = models.ForeignKey(
        EmployeeProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    to_employee = models.ForeignKey(EmployeeProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    reason = models.CharField(max_length=16, choices=Reason.choices)
    at = models.DateTimeField(default=timezone.now)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = "historia przypisania"
        verbose_name_plural = "historia przypisań"
        ordering = ["-at"]
        indexes = [models.Index(fields=["period", "slot_key"])]
