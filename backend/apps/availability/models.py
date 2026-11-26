"""Availability marked in the calendar, weekly patterns, submissions and text requests."""

from datetime import date

from django.conf import settings
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
# "Nie mogę" is always the whole day (Piotr, 25.11.2026): the hours someone can work are marked as "mogę" instead.
CANNOT_WHOLE_DAY = ~Q(state=AvailabilityState.CANNOT) | Q(from_time__isnull=True, to_time__isnull=True)


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
            models.CheckConstraint(condition=CANNOT_WHOLE_DAY, name="availability_day_cannot_whole_day"),
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
            models.CheckConstraint(condition=CANNOT_WHOLE_DAY, name="availability_pattern_cannot_whole_day"),
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
    # Saved requests: understood by the assistant or left to the manager. Only these carry over when lasting.
    SAVED = (Status.INTERPRETED, Status.NEEDS_MANAGER)

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
    # Reports of other hours the assistant prepared from this message ("zostałem godzinę dłużej"): checked against
    # the person's published shifts, shown under the answer with "Wyślij kierownikowi" (nothing is sent by itself).
    # Each: assignment_id, date, start_time, end_time, planned_start_time, planned_end_time, location_name,
    # position_name, reason.
    hours_reports = models.JSONField("zgłoszenia godzin do wysłania", null=True, blank=True)
    # The assistant was not sure what the person meant and asked them one question back (status `answered`): nothing
    # of this message is saved until they answer. Their next message is read together with it (`answer_to`).
    question = models.TextField("pytanie asystenta do pracownika", max_length=500, blank=True, default="")
    # This message answers the assistant's question on that earlier one: its reading covers both messages, and the
    # manager sees the earlier text and the question with it.
    answer_to = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="answers", verbose_name="odpowiedź na"
    )
    employee_corrected = models.BooleanField("poprawiona przez pracownika", default=False)
    supersedes = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="corrections")
    manager_priority = models.CharField(
        "ważność wg menedżera", max_length=8, choices=ManagerPriority.choices, default=ManagerPriority.NORMAL
    )
    manager_rejected = models.BooleanField("odrzucona przez menedżera", default=False)
    # "Na stałe" (Piotr, 22.11.2026): the request counts in its own period (month) and in every later period of the
    # locations where the person works, until someone ends it. In later periods only its parts without concrete
    # dates count (`interpretation[...]["lasting"]`).
    lasting = models.BooleanField("na stałe", default=False)
    # An ended lasting request stops counting in periods (months) that start on or after this day: the first day of
    # the period or month it was ended from. Empty: still in force.
    ends_from = models.DateField("nie obowiązuje od", null=True, blank=True)
    ended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
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
            ),
            models.CheckConstraint(
                condition=models.Q(ends_from__isnull=True) | models.Q(lasting=True), name="text_request_ends_lasting"
            ),
        ]

    @property
    def location(self):
        """The location this request is about: its period's, or the person's home location for a month request."""
        return self.period.location if self.period_id else self.employee.home_location

    @property
    def starts_on(self) -> date:
        """The first day of the period or month the request was written for."""
        return self.period.start if self.period_id else self.month

    @property
    def can_last(self) -> bool:
        """Whether "na stałe" means anything: a saved request that is not only about concrete days."""
        if self.status == self.Status.NEEDS_MANAGER:
            return True
        data = self.interpretation or {}
        parts = [data, *(data.get("more") or [])]
        return self.status == self.Status.INTERPRETED and any(not part.get("dates") for part in parts)

    def set_lasting(self, lasting: bool) -> None:
        """The person's choice "Tylko ten okres" / "Na stałe" for the whole request (every wish in it that is not
        about concrete days). It starts over: an end set before is gone. The caller saves."""
        self.lasting, self.ends_from, self.ended_by = lasting, None, None
        if self.interpretation:
            data = {**self.interpretation, "lasting": lasting and not self.interpretation.get("dates")}
            if data.get("more"):
                data["more"] = [{**part, "lasting": lasting and not part.get("dates")} for part in data["more"]]
            self.interpretation = data

    @property
    def ended_by_whom(self) -> str:
        """ "" while in force, "employee" when the person ended it themselves, else "manager"."""
        if self.ends_from is None:
            return ""
        return "employee" if self.ended_by_id == self.employee.membership.user_id else "manager"

    def is_own(self, periods=(), month: date | None = None) -> bool:
        """Whether the request was written for one of these periods (or a month they cover), or for this month:
        False for a lasting request carried over from an earlier one."""
        if month is not None:
            return self.period_id is None and self.month == month
        return any(
            self.period_id == p.pk or (self.period_id is None and p.start.replace(day=1) <= self.month <= p.end)
            for p in periods
        )

    @staticmethod
    def lasting_from(day: date, *, ended: bool = False) -> models.Q:
        """Lasting requests that count in a period (or month) starting on `day`: written for it or earlier, and not
        ended before it. `ended`: the ones ended from exactly this day instead (listed as ended there)."""
        started = models.Q(period__start__lte=day) | models.Q(period__isnull=True, month__lte=day)
        saved = models.Q(lasting=True, status__in=TextRequest.SAVED)
        if ended:
            return models.Q(started, saved, ends_from=day)
        return models.Q(started, saved, models.Q(ends_from__isnull=True) | models.Q(ends_from__gt=day))

    @staticmethod
    def for_periods(periods) -> models.Q:
        """Requests that count in these periods: written for them, or for a month they cover, by people who work in
        their location (as their main location or an extra one: a request for a month is about the person), and
        lasting requests of those people written earlier and not ended."""
        from apps.staffing.models import works_in_q

        q = models.Q(period__in=[p.pk for p in periods])
        for p in periods:
            person = works_in_q(p.location_id, prefix="employee__")
            q |= models.Q(person, period__isnull=True, month__gte=p.start.replace(day=1), month__lte=p.end)
            q |= models.Q(person, TextRequest.lasting_from(p.start))
        return q

    def __str__(self) -> str:
        return f"{self.employee}: {self.text[:60]}"
