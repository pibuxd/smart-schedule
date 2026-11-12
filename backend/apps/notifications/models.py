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
