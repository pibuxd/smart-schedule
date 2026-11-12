"""Giving away shifts: an employee offers a shift, others claim it, a manager approves."""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.scheduling.models import Assignment
from apps.staffing.models import EmployeeProfile
from apps.tenancy.base import CompanyOwnedModel


class ShiftOffer(CompanyOwnedModel):
    class Status(models.TextChoices):
        OPEN = "open", "otwarta"
        CLAIMED = "claimed", "ktoś chce wziąć"
        APPROVED = "approved", "zatwierdzona"
        REJECTED = "rejected", "odrzucona"
        CANCELLED = "cancelled", "anulowana"
        EXPIRED = "expired", "wygasła"

    company_from = "assignment"

    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="offers")
    offered_by = models.ForeignKey(EmployeeProfile, on_delete=models.CASCADE, related_name="+")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "oddana zmiana"
        verbose_name_plural = "oddane zmiany"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["assignment"],
                condition=Q(status__in=["open", "claimed"]),
                name="shift_offer_one_active_per_assignment",
            ),
        ]


class ShiftClaim(CompanyOwnedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "czeka na menedżera"
        APPROVED = "approved", "zatwierdzone"
        REJECTED = "rejected", "odrzucone"
        WITHDRAWN = "withdrawn", "wycofane"

    company_from = "offer"

    offer = models.ForeignKey(ShiftOffer, on_delete=models.CASCADE, related_name="claims")
    employee = models.ForeignKey(EmployeeProfile, on_delete=models.CASCADE, related_name="+")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "chęć wzięcia zmiany"
        verbose_name_plural = "chęci wzięcia zmian"
        constraints = [
            models.UniqueConstraint(fields=["offer", "employee"], name="shift_claim_unique_per_employee"),
            models.UniqueConstraint(
                fields=["offer"], condition=Q(status="approved"), name="shift_claim_one_approved_per_offer"
            ),
        ]
