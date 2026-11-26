"""In-app notifications only (no SMS or e-mail besides login codes)."""

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.tenancy.base import CompanyOwnedModel


class Notification(CompanyOwnedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField("rodzaj", max_length=48)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "powiadomienie"
        verbose_name_plural = "powiadomienia"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "read_at"])]


class PushDevice(models.Model):
    """A phone with the iOS or Android app that gets push notifications (docs/mobile.md).

    It belongs to the person, not to a company: one phone gets the notifications of all their companies. It is
    tied to the session it registered from, so logging out there, or that session ending, unpins it.
    """

    class Platform(models.TextChoices):
        IOS = "ios", "iOS"
        ANDROID = "android", "Android"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_devices")
    platform = models.CharField("system", max_length=8, choices=Platform.choices)
    # APNs device token (iOS) or Firebase registration token (Android).
    token = models.CharField(max_length=512, unique=True)
    session_key = models.CharField(max_length=40, db_index=True)
    # iOS only: a build from Xcode, whose token works with Apple's sandbox service.
    sandbox = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    seen_at = models.DateTimeField("ostatnio zgłoszony", default=timezone.now)

    class Meta:
        verbose_name = "telefon z aplikacją"
        verbose_name_plural = "telefony z aplikacją"

    def __str__(self) -> str:
        return f"{self.get_platform_display()} …{self.token[-6:]}"
