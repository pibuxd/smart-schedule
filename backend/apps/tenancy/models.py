"""Companies, location groups, locations, memberships and invitations."""

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.tenancy.base import CompanyOwnedModel, UUIDModel


class Company(UUIDModel):
    name = models.CharField("nazwa", max_length=200)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "firma"
        verbose_name_plural = "firmy"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class LocationGroup(CompanyOwnedModel):
    name = models.CharField("nazwa", max_length=200)

    class Meta:
        verbose_name = "grupa lokali"
        verbose_name_plural = "grupy lokali"
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["company", "name"], name="location_group_unique_name")]

    def __str__(self) -> str:
        return self.name


class SchedulePeriodKind(models.TextChoices):
    WEEK = "week", "tydzień"
    MONTH = "month", "miesiąc"


class Location(CompanyOwnedModel):
    company_from = "group"

    name = models.CharField("nazwa", max_length=200)
    address = models.CharField("adres", max_length=300, blank=True)
    group = models.ForeignKey(
        LocationGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name="locations", verbose_name="grupa"
    )
    timezone = models.CharField("strefa czasowa", max_length=64, default="Europe/Warsaw")
    schedule_period = models.CharField(
        "okres grafiku", max_length=8, choices=SchedulePeriodKind.choices, default=SchedulePeriodKind.MONTH
    )
    availability_deadline_days = models.PositiveSmallIntegerField("termin dyspozycji (dni przed okresem)", default=7)

    class Meta:
        verbose_name = "lokal"
        verbose_name_plural = "lokale"
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["company", "name"], name="location_unique_name")]

    def __str__(self) -> str:
        return self.name


class Role(models.TextChoices):
    OWNER = "owner", "właściciel"
    MANAGER = "manager", "menedżer"
    EMPLOYEE = "employee", "pracownik"


class Membership(CompanyOwnedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField("rola", max_length=16, choices=Role.choices, default=Role.EMPLOYEE)
    locations = models.ManyToManyField(
        Location,
        blank=True,
        related_name="managers",
        verbose_name="lokale menedżera",
        help_text="Lokale, którymi zarządza menedżer. Właściciel zarządza wszystkimi.",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "członkostwo"
        verbose_name_plural = "członkostwa"
        constraints = [models.UniqueConstraint(fields=["user", "company"], name="membership_unique_user_company")]

    def __str__(self) -> str:
        return f"{self.user} – {self.get_role_display()}"

    @property
    def is_manager(self) -> bool:
        return self.role in (Role.OWNER, Role.MANAGER)


class InvitationStatus(models.TextChoices):
    PENDING = "pending", "oczekuje"
    ACCEPTED = "accepted", "przyjęte"
    DECLINED = "declined", "odrzucone"
    CANCELLED = "cancelled", "anulowane"


class Invitation(CompanyOwnedModel):
    company_from = "location"

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="invitations")
    phone_e164 = models.CharField("numer telefonu", max_length=16, db_index=True)
    role = models.CharField(
        "rola",
        max_length=16,
        choices=[(Role.MANAGER, Role.MANAGER.label), (Role.EMPLOYEE, Role.EMPLOYEE.label)],
        default=Role.EMPLOYEE,
    )
    status = models.CharField(max_length=16, choices=InvitationStatus.choices, default=InvitationStatus.PENDING)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "zaproszenie"
        verbose_name_plural = "zaproszenia"
        constraints = [
            models.UniqueConstraint(
                fields=["location", "phone_e164"],
                condition=models.Q(status="pending"),
                name="invitation_one_pending_per_location_phone",
            ),
            models.CheckConstraint(
                condition=models.Q(status="pending", decided_at__isnull=True)
                | (~models.Q(status="pending") & models.Q(decided_at__isnull=False)),
                name="invitation_decided_at_matches_status",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.phone_e164} → {self.location} ({self.get_status_display()})"
