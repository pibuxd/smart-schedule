"""What the manager tells the assistant in words, and what stays of it.

- `AssistantCommand`: one message of the manager ("Ania i Kasia nie razem, to ważniejsze niż równe weekendy").
  The assistant (a language model, in the worker) turns it into a plan: changes on the location's rule list and
  instructions about people. Nothing changes until the manager accepts the plan.
- `ManagerInstruction`: an accepted instruction about one person. The generator scores it with the manager's
  rules; its place on the list of instructions is its importance, so "everything most important" cannot be said.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.staffing.models import EmployeeProfile
from apps.tenancy.base import CompanyOwnedModel
from apps.tenancy.models import Location


class AssistantRuleSet(CompanyOwnedModel):
    """Agreed settings for one availability period, or waiting for the next request."""

    company_from = "location"
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="assistant_rule_sets")
    period = models.OneToOneField("scheduling.SchedulePeriod", on_delete=models.CASCADE, null=True, blank=True)
    # None until the first approval, or for legacy sets whose original snapshot is unknown.
    rules = models.JSONField(null=True, blank=True)
    changed_codes = models.JSONField(default=list)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    def validate_same_company(self):
        super().validate_same_company()
        if self.period_id and self.period.location_id != self.location_id:
            raise ValidationError({"period": "Okres należy do innego lokalu."})

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["location"], condition=Q(period__isnull=True), name="one_pending_assistant_set"
            ),
            models.CheckConstraint(
                condition=Q(consumed_at__isnull=True) | Q(period__isnull=False),
                name="consumed_assistant_set_has_period",
            ),
        ]


class ManagerInstruction(CompanyOwnedModel):
    company_from = "location"

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="instructions")
    rule_set = models.ForeignKey(
        AssistantRuleSet, on_delete=models.CASCADE, null=True, blank=True, related_name="instructions"
    )
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

    def validate_same_company(self):
        super().validate_same_company()
        if self.rule_set_id and self.rule_set.location_id != self.location_id:
            raise ValidationError({"rule_set": "Zestaw zasad należy do innego lokalu."})

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
    rule_set = models.ForeignKey(
        AssistantRuleSet, on_delete=models.CASCADE, null=True, blank=True, related_name="commands"
    )
    text = models.TextField("polecenie", max_length=1000)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    # The checked plan: reply, question, rule_changes, new_instructions, remove_instructions, notes.
    plan = models.JSONField("plan", null=True, blank=True)
    # The assistant's own answer before checking, or {"error": ...}: kept for the superadmin's list of misses.
    assistant_answer = models.JSONField("odpowiedź asystenta", null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)
    # The arranging the accepted plan started ("ułóż inny grafik"), so the chat can follow it.
    generation_run = models.ForeignKey(
        "scheduling.GenerationRun", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    def validate_same_company(self):
        super().validate_same_company()
        if self.rule_set_id and self.rule_set.location_id != self.location_id:
            raise ValidationError({"rule_set": "Zestaw zasad należy do innego lokalu."})

    class Meta:
        verbose_name = "polecenie dla asystenta"
        verbose_name_plural = "polecenia dla asystenta"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["location", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.location}: {self.text[:60]}"
