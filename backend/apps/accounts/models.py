"""User accounts. One account per phone number in the whole system; companies come from memberships."""

import phonenumbers
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.crypto import salted_hmac

from apps.tenancy.base import UUIDModel

POLISH_PREFIX = "+48"
NOT_A_PHONE = "To nie wygląda na numer telefonu."
WRONG_PHONE = "Sprawdź numer. Polski ma 9 cyfr. Numer z innego kraju zacznij od + i kierunkowego, na przykład +380."
WRONG_FOREIGN_PHONE = "Sprawdź numer. Nie pasuje do numerów z kraju o tym kierunkowym."
NOT_MOBILE = "Kod logowania przychodzi SMS-em, więc podaj numer komórki."
# Number types that can get an SMS. Polish numbers are taken as before (any valid one); a foreign one must be a mobile,
# which also keeps premium-rate and other costly numbers out of the SMS budget.
SMS_NUMBER_TYPES = frozenset({phonenumbers.PhoneNumberType.MOBILE, phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE})


def normalize_phone(raw: str, *, mobile: bool = True) -> str:
    """Return a phone number in E.164 form, or raise ValidationError. A number without a country code is Polish
    (+48); one from another country is written with its code ("+380 50 123 4567", "00380…") and must be a mobile
    (Piotr, 25.11.2026: people from Ukraine and elsewhere keep their own numbers).

    `mobile=False` skips the mobile check: for the account itself, the admin (who may let in a real mobile the
    metadata misreads) and login, which sends codes only to numbers that already have an account or an invitation.
    Numbers enter through invitations, which keep the check."""
    try:
        number = phonenumbers.parse(str(raw), "PL")
    except phonenumbers.NumberParseException as exc:
        raise ValidationError(NOT_A_PHONE) from exc
    if not phonenumbers.is_valid_number(number):
        raise ValidationError(WRONG_PHONE if number.country_code == 48 else WRONG_FOREIGN_PHONE)
    if mobile and number.country_code != 48 and phonenumbers.number_type(number) not in SMS_NUMBER_TYPES:
        raise ValidationError(NOT_MOBILE)
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def phone_for_text(e164: str) -> str:
    """How a stored number is written for people: "512 345 678" for a Polish one, "+380 50 123 4567" for another
    country. Non-breaking spaces keep it on one line."""
    if e164.startswith(POLISH_PREFIX) and len(e164) == 12:
        digits = e164.removeprefix(POLISH_PREFIX)
        return " ".join(digits[i : i + 3] for i in range(0, 9, 3))
    try:
        number = phonenumbers.parse(e164, None)
    except phonenumbers.NumberParseException:
        return e164
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL).replace(" ", " ")


BANK_ACCOUNT_MAX = 100
BANK_ACCOUNT_TOO_LONG = f"Numer konta może mieć najwyżej {BANK_ACCOUNT_MAX} znaków."


def normalize_bank_account(raw: str | None) -> str:
    """The bank account number for pay as the person wrote it, with the spaces tidied, or "" for none. Any bank
    (Polish, Revolut, Ukrainian…), so it is plain text and not checked (Piotr, 25.11.2026)."""
    text = " ".join((raw or "").split())
    if len(text) > BANK_ACCOUNT_MAX:
        raise ValidationError(BANK_ACCOUNT_TOO_LONG)
    return text


def bank_account_text(account: str) -> str:
    """The number for a spreadsheet: digits alone are grouped ("61 1090 1014 0000 0712 1981 2874"), so Excel does
    not read them as a number like 6,11E+25; anything else stays as written."""
    if not account.isascii() or not account.isdigit():
        return account
    head = 2 if len(account) == 26 else 0  # a Polish number starts with its two check digits
    groups = [account[:head]] if head else []
    return " ".join([*groups, *(account[i : i + 4] for i in range(head, len(account), 4))])


def bank_account_ending(account: str) -> str:
    """The last four characters (without spaces): enough to recognise the number, never the whole of it."""
    return "".join(account.split())[-4:]


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, phone_e164: str, password: str | None = None, **extra):
        user = self.model(phone_e164=normalize_phone(phone_e164, mobile=False), **extra)
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
    # For pay transfers, optional (docs/plan.md, section 42): plain text as written (`normalize_bank_account`), since
    # people use any bank. Like the name it belongs to the person, so every company they work for sees the same
    # number; only the person, the managers of their locations and the superadmin read it, and it never goes to the
    # assistant's model.
    bank_account = models.CharField("numer konta", max_length=BANK_ACCOUNT_MAX, blank=True)
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
        self.phone_e164 = normalize_phone(self.phone_e164, mobile=False)
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
