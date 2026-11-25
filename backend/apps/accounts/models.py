"""User accounts. One account per phone number in the whole system; companies come from memberships."""

import phonenumbers
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.crypto import salted_hmac

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


BANK_ACCOUNT_SHAPE = "Numer konta ma 26 cyfr, np. 61 1090 1014 0000 0712 1981 2874."
BANK_ACCOUNT_TYPO = "W tym numerze konta jest błąd. Sprawdź cyfry."
# The letters P and L as IBAN digits (A = 10 … Z = 35): the IBAN check reads "PL" after the account number.
_PL_DIGITS = "2521"


def normalize_bank_account(raw: str | None) -> str:
    """A Polish bank account number (NRB, 26 digits) without spaces, or "" for none; raise ValidationError for a
    wrong one. Takes spaces, dashes and the "PL" of an IBAN. The two first digits are the IBAN check digits, so
    most typos (a wrong or swapped digit) are caught."""
    text = "".join((raw or "").split()).replace("-", "").upper()
    if text.startswith("PL"):
        text = text[2:]
    if not text:
        return ""
    if len(text) != 26 or not text.isascii() or not text.isdigit():
        raise ValidationError(BANK_ACCOUNT_SHAPE)
    if int(text[2:] + _PL_DIGITS + text[:2]) % 97 != 1:
        raise ValidationError(BANK_ACCOUNT_TYPO)
    return text


def bank_account_text(digits: str) -> str:
    """ "61 1090 1014 0000 0712 1981 2874": how banks print it (also keeps a spreadsheet from reading a number)."""
    if not digits:
        return ""
    return " ".join([digits[:2], *(digits[i : i + 4] for i in range(2, len(digits), 4))])


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
    # For pay transfers, optional (docs/plan.md, section 42): 26 digits (`normalize_bank_account`). Like the name it
    # belongs to the person, so every company they work for sees the same number; only the person, the managers of
    # their locations and the superadmin read it, and it never goes to the assistant's model.
    bank_account = models.CharField("numer konta", max_length=26, blank=True)
    is_staff = models.BooleanField("dostęp do panelu admina", default=False)
    is_active = models.BooleanField("aktywne", default=True)
    date_joined = models.DateTimeField("utworzone", default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "phone_e164"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        verbose_name = "użytkownik"
        verbose_name_plural = "użytkownicy"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(bank_account="") | models.Q(bank_account__regex=r"^[0-9]{26}$"),
                name="user_bank_account_26_digits",
            )
        ]

    def __str__(self) -> str:
        name = self.full_name
        return f"{name} ({self.phone_e164})" if name else self.phone_e164

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def clean(self) -> None:
        super().clean()
        self.phone_e164 = normalize_phone(self.phone_e164)
        try:
            self.bank_account = normalize_bank_account(self.bank_account)
        except ValidationError as exc:
            raise ValidationError({"bank_account": exc.messages}) from exc

    def _get_session_auth_hash(self, secret=None):
        # The phone number is the identity. When the superadmin changes it, every existing session of
        # this account stops working, so whoever still holds the old phone or an old device is logged out.
        return salted_hmac(
            "apps.accounts.User.session_auth_hash",
            f"{self.password}|{self.phone_e164}",
            secret=secret,
            algorithm="sha256",
        ).hexdigest()


class LoginCode(UUIDModel):
    """One SMS login code. Only the hash is stored (logic in `apps/accounts/login.py`)."""

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
