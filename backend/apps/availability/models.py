"""Availability marked in the calendar, weekly patterns, submissions and text requests."""

from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.scheduling.models import SchedulePeriod
from apps.staffing.models import WEEKDAY_RANGE, EmployeeProfile, Weekday
from apps.tenancy.base import CompanyOwnedModel


class AvailabilityState(models.TextChoices):
    CANNOT = "cannot", "nie mogę"
    # A day without a mark ("mogę"). Stored only when it carries hours ("mogę tylko w tych godzinach") or after
    # the employee cleared a mark; for the generator it is the same as no row.
    NEUTRAL = "neutral", "bez zaznaczenia"
    PREFER = "prefer", "chętnie"


# An end at or before the start means the next morning (night shifts); only an empty window is refused.
HOURS_NOT_EMPTY = Q(from_time__isnull=True) | Q(to_time__isnull=True) | ~Q(from_time=models.F("to_time"))


class AvailabilityDay(CompanyOwnedModel):
    """State for one employee and day, with optional hours (see `engine.problem.Availability`).

    No row = nothing submitted.
    """

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
    # A second window the same day ("6–10 lub 16–22"); `one_shift` ("albo"): at most one shift that day.
    from_time_2 = models.TimeField(null=True, blank=True)
    to_time_2 = models.TimeField(null=True, blank=True)
    one_shift = models.BooleanField(default=False)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.MANUAL)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "dyspozycyjność"
        verbose_name_plural = "dyspozycyjność"
        ordering = ["employee", "date"]
        constraints = [
            models.UniqueConstraint(fields=["employee", "date"], name="availability_day_unique"),
            models.CheckConstraint(condition=HOURS_NOT_EMPTY, name="availability_day_hours_not_empty"),
            models.CheckConstraint(
                condition=Q(from_time_2__isnull=True, to_time_2__isnull=True)
                | (
                    Q(from_time_2__isnull=False, to_time_2__isnull=False)
                    & ~Q(from_time_2=models.F("to_time_2"))
                    & (Q(from_time__isnull=False) | Q(to_time__isnull=False))
                ),
                name="availability_day_second_window",
            ),
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
            models.CheckConstraint(condition=HOURS_NOT_EMPTY, name="availability_pattern_hours_not_empty"),
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
    """An employee message, its reading/reply, and any correction history. Requests are shared with managers."""

    class Status(models.TextChoices):
        NEW = "new", "nowa"
        INTERPRETED = "interpreted", "zrozumiana"
        NEEDS_MANAGER = "needs_manager", "do decyzji menedżera"
        REJECTED = "rejected", "odrzucona"
        ANSWERED = "answered", "odpowiedź informacyjna"
        SUPERSEDED = "superseded", "zastąpiona"

    # Statuses that take a place in the limit per period (`TEXT_REQUESTS_PER_PERIOD`). Questions the assistant
    # answered, refused messages and replaced requests do not.
    COUNTED = (Status.NEW, Status.INTERPRETED, Status.NEEDS_MANAGER)

    class ManagerPriority(models.TextChoices):
        LOWER = "lower", "mniej ważna"
        NORMAL = "normal", "zwykła"
        HIGHER = "higher", "ważniejsza"

    company_from = "employee"

    employee = models.ForeignKey(EmployeeProfile, on_delete=models.CASCADE, related_name="text_requests")
    # A request written while the manager has asked for a period belongs to it. One written for a month with no
    # period yet has only `month` (its first day) and counts in every period of the person's home location that
    # covers that month (see `for_periods`).
    period = models.ForeignKey(
        SchedulePeriod, on_delete=models.CASCADE, related_name="text_requests", null=True, blank=True
    )
    month = models.DateField("miesiąc (bez okresu)", null=True, blank=True)
    text = models.TextField("treść", max_length=1000)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW)
    interpretation = models.JSONField(
        "interpretacja",
        null=True,
        blank=True,
        help_text="type, subject_employee, dates, level, confidence, summary",
    )

    class UnreadReason(models.TextChoices):
        NONE = "", "—"
        OFF = "off", "asystent wyłączony"
        UNSURE = "unsure", "asystent nie był pewny"
        FAILED = "failed", "błąd asystenta"
        # The assistant refused the message as off-topic and the person handed its text to the manager.
        REJECTED = "rejected", "odrzucona przez asystenta, przekazana"

    # Why a request is left to the manager without an interpretation (empty when it was understood or is new).
    unread_reason = models.CharField(
        "dlaczego bez interpretacji", max_length=8, choices=UnreadReason.choices, default="", blank=True
    )
    # For the superadmin's list of misses: what the assistant answered when its reading could not be used, with
    # "why", or {"error": ...} when the call failed. Empty when the request was understood.
    assistant_answer = models.JSONField("odpowiedź asystenta (nieużyta)", null=True, blank=True)
    # What the assistant said to the person (an answer to a question, or a word about the saved request).
    reply = models.TextField("odpowiedź asystenta dla pracownika", max_length=2000, blank=True, default="")
    employee_corrected = models.BooleanField("poprawiona przez pracownika", default=False)
    supersedes = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="corrections")
    manager_priority = models.CharField(
        "ważność wg menedżera", max_length=8, choices=ManagerPriority.choices, default=ManagerPriority.NORMAL
    )
    manager_rejected = models.BooleanField("odrzucona przez menedżera", default=False)
    created_at = models.DateTimeField(default=timezone.now)
    # When the person last wrote the text again ("Popraw"); empty when it is as first sent. `updated_at` also moves
    # when the assistant or the manager handles the request, so it cannot say when the words were written.
    text_edited_at = models.DateTimeField("treść poprawiona", null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def written_at(self):
        """When the current text was written: "jutro" in it counts from this moment."""
        return self.text_edited_at or self.created_at

    class Meta:
        verbose_name = "prośba"
        verbose_name_plural = "prośby"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["period", "status"]), models.Index(fields=["employee", "month"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(period__isnull=False, month__isnull=True)
                | models.Q(period__isnull=True, month__isnull=False),
                name="text_request_period_or_month",
            )
        ]

    @property
    def location(self):
        """The location this request is about: its period's, or the person's home location for a month request."""
        return self.period.location if self.period_id else self.employee.home_location

    @staticmethod
    def for_periods(periods) -> models.Q:
        """Requests that count in these periods: written for them, or for a month they cover, by people who work in
        their location (as their main location or an extra one: a request for a month is about the person)."""
        from apps.staffing.models import works_in_q

        q = models.Q(period__in=[p.pk for p in periods])
        for p in periods:
            q |= models.Q(
                works_in_q(p.location_id, prefix="employee__"),
                period__isnull=True,
                month__gte=p.start.replace(day=1),
                month__lte=p.end,
            )
        return q

    def __str__(self) -> str:
        return f"{self.employee}: {self.text[:60]}"
