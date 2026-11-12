"""Login with a 6-digit SMS code: who may get a code, rate limits, and checking the code.

Rules (docs/spec.md, "Logowanie i zaproszenia"):
- a code goes only to a +48 number that has an account or a pending invitation, or when a new manager registers;
- the code lives 5 minutes and allows 5 wrong tries; only its hash is stored;
- a few codes per phone number per hour and a limit per IP address.
"""

import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from ninja.errors import HttpError

from apps.accounts.models import LoginCode, User, normalize_phone
from apps.accounts.sms import get_sms_sender
from apps.tenancy.models import Invitation, InvitationStatus

logger = logging.getLogger(__name__)

Purpose = Literal["login", "register"]

UNKNOWN_PHONE = "Nie znamy tego numeru. Poproś kierownika o zaproszenie albo załóż firmę, jeśli sam układasz grafik."
TOO_MANY_CODES = "Za dużo kodów w krótkim czasie. Spróbuj ponownie za godzinę."
BAD_CODE = "Ten kod jest nieprawidłowy."
NO_ACTIVE_CODE = "Kod wygasł. Poproś o nowy."
TOO_MANY_ATTEMPTS = "Za dużo błędnych prób. Poproś o nowy kod."


@dataclass(frozen=True)
class IssuedCode:
    phone_e164: str
    expires_in_s: int
    resend_after_s: int


def parse_phone(raw: str) -> str:
    try:
        return normalize_phone(raw)
    except ValidationError as exc:
        raise HttpError(400, exc.messages[0]) from exc


def hash_login_code(phone_e164: str, code: str) -> str:
    # A keyed hash: with only 10^6 possible codes a plain hash could be reversed from a database dump.
    return salted_hmac("apps.accounts.login_code", f"{phone_e164}:{code}", algorithm="sha256").hexdigest()


def may_receive_code(phone_e164: str, purpose: Purpose) -> bool:
    user = User.objects.filter(phone_e164=phone_e164).first()
    if user is not None:
        return user.is_active
    if purpose == "register":
        return True
    return Invitation.objects.filter(phone_e164=phone_e164, status=InvitationStatus.PENDING).exists()


def _lock(key: str) -> None:
    """Serialize requests for one phone number or one IP, so two parallel requests cannot both pass a limit."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [key])


def request_login_code(raw_phone: str, purpose: Purpose, ip: str | None) -> IssuedCode:
    phone = parse_phone(raw_phone)
    now = timezone.now()
    hour_ago = now - timedelta(hours=1)

    with transaction.atomic():
        if ip:
            _lock(f"login-ip:{ip}")
            if LoginCode.objects.filter(ip=ip, created_at__gt=hour_ago).count() >= settings.LOGIN_CODES_PER_IP_PER_HOUR:
                raise HttpError(429, TOO_MANY_CODES)
        # The IP limit is checked before we say whether a number is known, and refused numbers count
        # against it too, so the answer cannot be used to test a long list of numbers.
        allowed = may_receive_code(phone, purpose)
        if allowed:
            _issue_code(phone, ip, now)
        elif ip:
            # A row without a code (empty hash, already "used"): it can never log anyone in.
            LoginCode.objects.create(
                phone_e164=phone,
                code_hash="",
                created_at=now,
                expires_at=now + timedelta(seconds=1),
                used_at=now,
                ip=ip,
            )
    if not allowed:
        # Raised after the block, so the row above is kept.
        raise HttpError(404, UNKNOWN_PHONE)
    return IssuedCode(phone, settings.LOGIN_CODE_TTL_S, settings.LOGIN_CODE_RESEND_AFTER_S)


def _issue_code(phone: str, ip: str | None, now) -> None:
    _lock(f"login-phone:{phone}")
    recent = list(
        LoginCode.objects.filter(phone_e164=phone, created_at__gt=now - timedelta(hours=1))
        .exclude(code_hash="")
        .order_by("-created_at")
        .values_list("created_at", flat=True)
    )
    if len(recent) >= settings.LOGIN_CODES_PER_PHONE_PER_HOUR:
        raise HttpError(429, TOO_MANY_CODES)
    if recent:
        wait = settings.LOGIN_CODE_RESEND_AFTER_S - int((now - recent[0]).total_seconds())
        if wait > 0:
            raise HttpError(429, f"Kod został już wysłany. Kolejny możesz dostać za {wait} s.")

    code = f"{secrets.randbelow(10**6):06d}"
    LoginCode.objects.create(
        phone_e164=phone,
        code_hash=hash_login_code(phone, code),
        created_at=now,
        expires_at=now + timedelta(seconds=settings.LOGIN_CODE_TTL_S),
        ip=ip,
    )
    try:
        get_sms_sender().send(phone, f"Grafikomat: kod logowania {code}. Ważny 5 minut. Nie podawaj go nikomu.")
    except Exception as exc:
        # Rolls back the row above, so a failed delivery does not use up the person's limit.
        logger.exception("sending the login code failed")
        raise HttpError(503, "Nie udało się wysłać SMS-a z kodem. Spróbuj ponownie za chwilę.") from exc


def verify_login_code(raw_phone: str, raw_code: str) -> User:
    """Check the code and return the account (created on first login). Raises HttpError when the code is wrong."""
    phone = parse_phone(raw_phone)
    submitted = "".join(ch for ch in str(raw_code) if not ch.isspace())
    now = timezone.now()
    error: HttpError | None = None
    user: User | None = None

    # Errors are raised after the block: raising inside would roll back the attempt counter.
    with transaction.atomic():
        login_code = (
            LoginCode.objects.select_for_update()
            .filter(phone_e164=phone, used_at__isnull=True, expires_at__gt=now)
            .order_by("-created_at")
            .first()
        )
        if login_code is None:
            error = HttpError(400, NO_ACTIVE_CODE)
        elif login_code.attempts >= settings.LOGIN_CODE_MAX_ATTEMPTS:
            error = HttpError(429, TOO_MANY_ATTEMPTS)
        elif not constant_time_compare(login_code.code_hash, hash_login_code(phone, submitted)):
            login_code.attempts += 1
            login_code.save(update_fields=["attempts"])
            left = settings.LOGIN_CODE_MAX_ATTEMPTS - login_code.attempts
            error = HttpError(400, f"{BAD_CODE} Pozostało prób: {left}." if left else TOO_MANY_ATTEMPTS)
        else:
            login_code.used_at = now
            login_code.save(update_fields=["used_at"])
            user = User.objects.filter(phone_e164=phone).first()
            if user is None:
                # First login of an invited person or of a manager who is registering.
                user = User.objects.create_user(phone)
            elif not user.is_active:
                error = HttpError(403, "To konto jest wyłączone.")

    if error is not None:
        raise error
    assert user is not None  # noqa: S101 - narrowing for the type checker
    return user
