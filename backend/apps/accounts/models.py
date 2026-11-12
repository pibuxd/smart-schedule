"""User accounts. One account per phone number in the whole system; companies come from memberships."""

import phonenumbers
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.tenancy.base import UUIDModel


def normalize_phone(raw: str) -> str:
    """Return a Polish (+48) mobile or landline number in E.164 form, or raise ValidationError."""
    try:
        number = phonenumbers.parse(str(raw), "PL")
    except phonenumbers.NumberParseException as exc:
        raise ValidationError("To nie wygląda na numer telefonu.") from exc
    if number.country_code != 48 or not phonenumbers.is_valid_number(number):
        raise ValidationError("Podaj polski numer telefonu (+48).")
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, phone_e164: str, password: str | None = None, **extra):
        user = self.model(phone_e164=normalize_phone(phone_e164), **extra)
        if password:
            user.set_password(password)
        else:
            # App users log in with an SMS code only; a password exists only for the Django admin.
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone_e164: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self.create_user(phone_e164, password, **extra)


class User(UUIDModel, AbstractBaseUser, PermissionsMixin):
    phone_e164 = models.CharField("numer telefonu", max_length=16, unique=True)
    first_name = models.CharField("imię", max_length=80, blank=True)
    last_name = models.CharField("nazwisko", max_length=120, blank=True)
    is_staff = models.BooleanField("dostęp do panelu admina", default=False)
    is_active = models.BooleanField("aktywne", default=True)
    date_joined = models.DateTimeField("utworzone", default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "phone_e164"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        verbose_name = "użytkownik"
        verbose_name_plural = "użytkownicy"

    def __str__(self) -> str:
        name = self.full_name
        return f"{name} ({self.phone_e164})" if name else self.phone_e164

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def clean(self) -> None:
        super().clean()
        self.phone_e164 = normalize_phone(self.phone_e164)


class LoginCode(UUIDModel):
    """One SMS login code. Only the hash is stored (logic in stage 3)."""

    phone_e164 = models.CharField(max_length=16, db_index=True)
    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = "kod logowania"
        verbose_name_plural = "kody logowania"
        indexes = [models.Index(fields=["phone_e164", "created_at"]), models.Index(fields=["ip", "created_at"])]
        constraints = [
            models.CheckConstraint(condition=models.Q(attempts__lte=5), name="login_code_max_5_attempts"),
            models.CheckConstraint(
                condition=models.Q(expires_at__gt=models.F("created_at")), name="login_code_expires"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.phone_e164} @ {self.created_at:%Y-%m-%d %H:%M}"
