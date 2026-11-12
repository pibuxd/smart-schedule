"""Free-access codes and subscriptions. No payment provider yet; `source` leaves room for Stripe later."""

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.tenancy.base import CompanyOwnedModel, UUIDModel


class AccessCode(UUIDModel):
    """A code created by the superadmin. Global (no company); only the hash is stored (generation in stage 3)."""

    class Days(models.IntegerChoices):
        D30 = 30, "30 dni"
        D60 = 60, "60 dni"

    code_hash = models.CharField(max_length=128, unique=True, editable=False)
    prefix = models.CharField("początek kodu", max_length=4, editable=False, help_text="Do rozpoznania kodu w panelu.")
    days = models.PositiveSmallIntegerField("długość dostępu", choices=Days.choices, default=Days.D30)
    max_uses = models.PositiveSmallIntegerField("maks. liczba użyć", default=1)
    uses = models.PositiveSmallIntegerField("użycia", default=0, editable=False)
    valid_until = models.DateTimeField("kod ważny do", null=True, blank=True)
    note = models.CharField("notatka", max_length=200, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "kod dostępu"
        verbose_name_plural = "kody dostępu"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(days__in=[30, 60]), name="access_code_days_30_or_60"),
            models.CheckConstraint(condition=models.Q(max_uses__gte=1), name="access_code_max_uses_positive"),
            models.CheckConstraint(condition=models.Q(uses__lte=models.F("max_uses")), name="access_code_uses_le_max"),
        ]

    def __str__(self) -> str:
        return f"{self.prefix}… ({self.days} dni, {self.uses}/{self.max_uses})"


class CodeAttempt(UUIDModel):
    """Every attempt to enter a code, for rate limiting (stage 3)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    ip = models.GenericIPAddressField(null=True, blank=True)
    at = models.DateTimeField(default=timezone.now)
    success = models.BooleanField(default=False)

    class Meta:
        verbose_name = "próba wpisania kodu"
        verbose_name_plural = "próby wpisania kodu"
        indexes = [models.Index(fields=["user", "at"]), models.Index(fields=["ip", "at"])]


class CodeRedemption(CompanyOwnedModel):
    code = models.ForeignKey(AccessCode, on_delete=models.PROTECT, related_name="redemptions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    redeemed_at = models.DateTimeField(default=timezone.now)
    days_added = models.PositiveSmallIntegerField()

    class Meta:
        verbose_name = "użycie kodu"
        verbose_name_plural = "użycia kodów"
        constraints = [models.UniqueConstraint(fields=["code", "company"], name="code_redemption_once_per_company")]


class Subscription(CompanyOwnedModel):
    class Source(models.TextChoices):
        CODE = "code", "kod"
        STRIPE = "stripe", "Stripe"

    # One subscription per company (the unique constraint below); next codes extend `ends_at`.
    ends_at = models.DateTimeField("koniec dostępu")
    source = models.CharField("źródło", max_length=16, choices=Source.choices, default=Source.CODE)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "subskrypcja"
        verbose_name_plural = "subskrypcje"
        constraints = [models.UniqueConstraint(fields=["company"], name="subscription_one_per_company")]

    def __str__(self) -> str:
        return f"do {self.ends_at:%Y-%m-%d} ({self.status_label})"

    @property
    def is_active(self) -> bool:
        return self.ends_at > timezone.now()

    @property
    def status_label(self) -> str:
        return "aktywna" if self.is_active else "wygasła"


class GenerationUsage(CompanyOwnedModel):
    """Number of schedule generations per company and calendar month (limit GENERATION_MONTHLY_LIMIT)."""

    month = models.DateField("miesiąc", help_text="Pierwszy dzień miesiąca.")
    count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "użycie generatora"
        verbose_name_plural = "użycie generatora"
        constraints = [
            models.UniqueConstraint(fields=["company", "month"], name="generation_usage_unique_month"),
            models.CheckConstraint(condition=models.Q(month__day=1), name="generation_usage_month_first_day"),
        ]
