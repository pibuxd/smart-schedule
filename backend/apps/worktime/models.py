"""Hours worked other than the published schedule says: longer (overtime) or shorter (leaving early).

An employee reports the hours of one of their published shifts and the manager approves or rejects; the manager
can also set them alone. The published schedule itself stays the plan (generator, validator and scores read it);
reports of hours and "Mój grafik" count the approved hours instead (`services.worked_hours`).
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.availability.models import TextRequest
from apps.scheduling.models import SchedulePeriod
from apps.staffing.models import EmployeeProfile
from apps.tenancy.base import CompanyOwnedModel
from apps.tenancy.models import Location


class HoursChange(CompanyOwnedModel):
    """Other hours for one person on one shift. The shift is (period, slot key), stable between versions, like
    `AssignmentEvent`: a corrected schedule keeps the change as long as the same person has the shift."""

    class Status(models.TextChoices):
        PENDING = "pending", "czeka na kierownika"
        APPROVED = "approved", "zatwierdzone"
        REJECTED = "rejected", "odrzucone"
        CANCELLED = "cancelled", "wycofane"
        # Newer hours of the same shift were approved, or the manager set other hours over a waiting report.
        REPLACED = "replaced", "zastąpione"

    company_from = "location"

    # RESTRICT like the schedule history: a location or period with history is archived, not deleted.
    location = models.ForeignKey(Location, on_delete=models.RESTRICT, related_name="+")
    period = models.ForeignKey(SchedulePeriod, on_delete=models.RESTRICT, related_name="hours_changes")
    slot_key = models.CharField(max_length=120)
    employee = models.ForeignKey(EmployeeProfile, on_delete=models.CASCADE, related_name="hours_changes")
    date = models.DateField("dzień zmiany")
    # The published hours when the change was written (for the history; the current plan is the shift itself).
    planned_start_at = models.DateTimeField("początek w grafiku")
    planned_end_at = models.DateTimeField("koniec w grafiku")
    start_at = models.DateTimeField("początek naprawdę")
    end_at = models.DateTimeField("koniec naprawdę")
    reason = models.TextField("powód", max_length=300, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    # The manager set the hours alone (approved at once), not the employee's report.
    by_manager = models.BooleanField("ustawione przez kierownika", default=False)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    # The chat message the report came from ("Wyślij kierownikowi" under the assistant's answer).
    source_request = models.ForeignKey(
        TextRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name="hours_changes"
    )

    class Meta:
        verbose_name = "zmiana godzin"
        verbose_name_plural = "zmiany godzin"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["location", "status"]),
            models.Index(fields=["period", "slot_key"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(end_at__gt=models.F("start_at")), name="hours_change_end_after_start"),
            models.UniqueConstraint(
                fields=["period", "slot_key", "employee"],
                condition=Q(status="pending"),
                name="hours_change_one_pending",
            ),
            models.UniqueConstraint(
                fields=["period", "slot_key", "employee"],
                condition=Q(status="approved"),
                name="hours_change_one_approved",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.employee} {self.date}: {self.start_at:%H:%M}–{self.end_at:%H:%M} ({self.get_status_display()})"

    @property
    def key(self) -> tuple[str, str, str]:
        return (str(self.period_id), self.slot_key, str(self.employee_id))
