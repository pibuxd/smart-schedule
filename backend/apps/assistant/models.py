"""What the manager tells the assistant in words, and what stays of it.

- `AssistantCommand`: one message of the manager ("Ania i Kasia nie razem, to ważniejsze niż równe weekendy").
  The assistant (Claude, in the worker) turns it into a plan: changes on the location's rule list and
  instructions about people. Nothing changes until the manager accepts the plan.
- `ManagerInstruction`: an accepted instruction about one person. The generator scores it with the manager's
  rules; its place on the list of instructions is its importance, so "everything most important" cannot be said.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.staffing.models import EmployeeProfile
from apps.tenancy.base import CompanyOwnedModel
from apps.tenancy.models import Location


class ManagerInstruction(CompanyOwnedModel):
    company_from = "location"

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="instructions")
    employee = models.ForeignKey(
        EmployeeProfile, on_delete=models.CASCADE, related_name="manager_instructions", verbose_name="kogo dotyczy"
    )
    # Same shape as `TextRequest.interpretation`: type, subject_employee, shift_type, avoid, max_hours, dates,
    # weekdays (see apps.assistant.readings).
    data = models.JSONField("treść")
    position = models.PositiveSmallIntegerField("miejsce na liście", help_text="1 = najważniejsze.")
    source_text = models.TextField("polecenie kierownika", max_length=1000, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "polecenie kierownika"
        verbose_name_plural = "polecenia kierownika"
        ordering = ["location", "position", "created_at"]
        constraints = [models.CheckConstraint(condition=Q(position__gte=1), name="instruction_position_positive")]

    def __str__(self) -> str:
        return f"{self.position}. {self.employee} ({self.location})"


class AssistantCommand(CompanyOwnedModel):
    class Status(models.TextChoices):
        QUEUED = "queued", "czeka na asystenta"
        READY = "ready", "plan do akceptacji"
        UNAVAILABLE = "unavailable", "asystent wyłączony"
        FAILED = "failed", "nie udało się"
        APPLIED = "applied", "zastosowane"
        DISMISSED = "dismissed", "odrzucone"

    company_from = "location"

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="assistant_commands")
    text = models.TextField("polecenie", max_length=1000)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    # The checked plan: reply, question, rule_changes, new_instructions, remove_instructions, notes.
    plan = models.JSONField("plan", null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "polecenie dla asystenta"
        verbose_name_plural = "polecenia dla asystenta"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["location", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.location}: {self.text[:60]}"
