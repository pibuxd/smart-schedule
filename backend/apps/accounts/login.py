"""Login with a 6-digit SMS code: who may get a code, rate limits, and checking the code.

Rules (docs/spec.md, "Logowanie i zaproszenia"):
- a code goes only to a number that has an account or a pending invitation, or when a new manager registers
  a company with a Polish (+48) number; numbers from other countries work once a manager invites them;
- the code lives 5 minutes and allows 5 wrong tries; only its hash is stored;
- a few codes per phone number per hour and a limit per IP address.

Two switches for the store test (Piotr, 28.11.2026; docs/plan.md section 51): while the closed test is on
(`apps/tenancy/testers.py`) a new Polish number may log in and joins the test location, and the store reviewers' number
(`REVIEW_LOGIN_PHONE`) logs in with a fixed code (`REVIEW_LOGIN_CODE`) that is never sent.
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

from apps.accounts.models import POLISH_PREFIX, LoginCode, User, normalize_phone
from apps.accounts.sms import get_sms_sender
from apps.tenancy.models import Invitation, InvitationStatus

logger = logging.getLogger(__name__)

Purpose = Literal["login", "register"]

UNKNOWN_PHONE = (
    "Nie znamy tego numeru. Sprawdź, czy jest wpisany dobrze. "
    "Jeśli tak, poproś kierownika o zaproszenie. Prowadzisz lokal? Załóż firmę."
)
FOREIGN_REGISTRATION = (
    "Nową firmę zakładasz polskim numerem (+48). Masz tylko numer z innego kraju? Poproś administratora "
    "Grafikomatu, żeby dodał Twój numer, a potem załóż firmę. Pracujesz w lokalu? Poproś kierownika o zaproszenie."
)
TOO_MANY_CODES = "Za dużo kodów w krótkim czasie. Spróbuj ponownie za godzinę."
TOO_MANY_REGISTRATIONS = (
    "Z tej sieci w ostatniej godzinie zakładano już kilka nowych kont. "
    "Spróbuj za godzinę albo z innej sieci, na przykład z internetu w telefonie."
)
BAD_CODE = "Ten kod jest nieprawidłowy."
NO_ACTIVE_CODE = "Kod wygasł. Poproś o nowy."
TOO_MANY_ATTEMPTS = "Za dużo błędnych prób. Poproś o nowy kod."
TESTERS_FULL = "Miejsca dla testerów są już zajęte. Napisz do osoby, która zaprosiła Cię do testów."


@dataclass(frozen=True)
class IssuedCode:
    phone_e164: str
    expires_in_s: int
    resend_after_s: int


def parse_phone(raw: str, *, mobile: bool = True) -> str:
    try:
        return normalize_phone(raw, mobile=mobile)
    except ValidationError as exc:
        raise HttpError(400, exc.messages[0]) from exc


def hash_login_code(phone_e164: str, code: str) -> str:
    # A keyed hash: with only 10^6 possible codes a plain hash could be reversed from a database dump.
    return salted_hmac("apps.accounts.login_code", f"{phone_e164}:{code}", algorithm="sha256").hexdigest()


# Why a number may get a code (`may_receive_code`).
ACCOUNT, INVITED, REGISTERING, JOINING_TESTERS = "account", "invited", "registering", "joining_testers"


def review_phone() -> str | None:
    """The store reviewers' number in E.164, or None when their login is off (both settings are needed, and the
    code must be 6 digits; `checks.review_login_is_complete` warns about a half-set one)."""
    raw, code = settings.REVIEW_LOGIN_PHONE, settings.REVIEW_LOGIN_CODE
    if not raw or not (len(code) == 6 and code.isdigit()):
        return None
    try:
        return normalize_phone(raw, mobile=False)
    except ValidationError:
        return None


def may_receive_code(phone_e164: str, purpose: Purpose) -> str | None:
    """Why this number may get a code (ACCOUNT, INVITED, REGISTERING, JOINING_TESTERS), or None when it may not."""
    from apps.tenancy import testers

    user = User.objects.filter(phone_e164=phone_e164).first()
    if user is not None:
        return ACCOUNT if user.is_active else None
    if Invitation.objects.filter(phone_e164=phone_e164, status=InvitationStatus.PENDING).exists():
        return INVITED
    # Registering sends a code to a number nobody vouched for, so only to a Polish one: an SMS abroad costs more and is
    # what SMS fraud is after. Foreign numbers get codes once a manager has invited them. The closed test lets new
    # numbers in the same way, from the plain login screen.
    if not phone_e164.startswith(POLISH_PREFIX):
        return None
    if purpose == "register":
        return REGISTERING
    if testers.may_join():
        return JOINING_TESTERS
    return None


def _lock(key: str) -> None:
    """Serialize requests for one phone number or one IP, so two parallel requests cannot both pass a limit."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [key])


def request_login_code(raw_phone: str, purpose: Purpose, ip: str | None) -> IssuedCode:
    phone = parse_phone(raw_phone, mobile=False)  # codes go only to known numbers (or +48 registering)
    now = timezone.now()
    hour_ago = now - timedelta(hours=1)

    with transaction.atomic():
        if ip:
            _lock(f"login-ip:{ip}")
            if LoginCode.objects.filter(ip=ip, created_at__gt=hour_ago).count() >= settings.LOGIN_CODES_PER_IP_PER_HOUR:
                raise HttpError(429, TOO_MANY_CODES)
        # The IP limit is checked before we say whether a number is known, and refused numbers count
        # against it too, so the answer cannot be used to test a long list of numbers.
        reason = may_receive_code(phone, purpose)
        allowed = reason is not None
        if allowed and ip and _is_new_number(phone):
            _check_new_numbers_limit(ip, hour_ago)
        if allowed:
            _issue_code(phone, ip, for_testers=reason == JOINING_TESTERS)
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
        if purpose == "register" and not phone.startswith(POLISH_PREFIX):
            raise HttpError(400, FOREIGN_REGISTRATION)
        if purpose == "login" and phone.startswith(POLISH_PREFIX) and _testers_full(phone):
            raise HttpError(404, TESTERS_FULL)
        raise HttpError(404, UNKNOWN_PHONE)
    return IssuedCode(phone, settings.LOGIN_CODE_TTL_S, settings.LOGIN_CODE_RESEND_AFTER_S)


def _testers_full(phone: str) -> bool:
    """A new number on the login screen while the closed test is on but full (an account or invitation never is)."""
    from apps.tenancy import testers

    return _is_new_number(phone) and testers.is_full()


def _is_new_number(phone: str) -> bool:
    """A number with no account and no invitation: only "register a company" sends codes to it."""
    return (
        not User.objects.filter(phone_e164=phone).exists()
        and not Invitation.objects.filter(phone_e164=phone, status=InvitationStatus.PENDING).exists()
    )


def _check_new_numbers_limit(ip: str, hour_ago) -> None:
    """Registering sends an SMS to any +48 number, so one address may do it only a few times an hour
    (protects the SMS budget and strangers' phones). Numbers that became accounts no longer count."""
    recent = (
        LoginCode.objects.filter(ip=ip, created_at__gt=hour_ago)
        .exclude(code_hash="")
        .exclude(phone_e164__in=User.objects.values("phone_e164"))
        .exclude(phone_e164__in=Invitation.objects.filter(status=InvitationStatus.PENDING).values("phone_e164"))
        .values("phone_e164")
        .distinct()
        .count()
    )
    if recent >= settings.REGISTER_NUMBERS_PER_IP_PER_HOUR:
        raise HttpError(429, TOO_MANY_REGISTRATIONS)


def _issue_code(phone: str, ip: str | None, *, for_testers: bool = False) -> None:
    _lock(f"login-phone:{phone}")
    now = timezone.now()
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

    # The reviewers' code is fixed and never sent; every other rule (expiry, tries, limits) is the same.
    reviewer = phone == review_phone()
    code = settings.REVIEW_LOGIN_CODE if reviewer else f"{secrets.randbelow(10**6):06d}"
    LoginCode.objects.create(
        phone_e164=phone,
        code_hash=hash_login_code(phone, code),
        created_at=now,
        expires_at=now + timedelta(seconds=settings.LOGIN_CODE_TTL_S),
        ip=ip,
        for_testers=for_testers,
    )
    if reviewer:
        return
    try:
        get_sms_sender().send(phone, f"Grafikomat: kod logowania {code}. Ważny 5 minut. Nie podawaj go nikomu.")
    except Exception as exc:
        # Rolls back the row above, so a failed delivery does not use up the person's limit.
        logger.exception("sending the login code failed")
        raise HttpError(503, "Nie udało się wysłać SMS-a z kodem. Spróbuj ponownie za chwilę.") from exc


def verify_login_code(raw_phone: str, raw_code: str) -> User:
    """Check the code and return the account (created on first login). Raises HttpError when the code is wrong."""
    phone = parse_phone(raw_phone, mobile=False)  # codes go only to known numbers (or +48 registering)
    submitted = "".join(ch for ch in str(raw_code) if not ch.isspace())
    error: HttpError | None = None
    user: User | None = None

    # Errors are raised after the block: raising inside would roll back the attempt counter.
    with transaction.atomic():
        _lock(f"login-phone:{phone}")
        now = timezone.now()
        login_code = (
            LoginCode.objects.select_for_update()
            .filter(phone_e164=phone)
            .exclude(code_hash="")
            .order_by("-created_at")
            .first()
        )
        if login_code is None or login_code.used_at is not None or login_code.expires_at <= now:
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
                # First login of an invited person, of a manager who is registering, or of a tester.
                user = _create_account(phone, login_code.for_testers)
                if user is None:
                    error = HttpError(400, TESTERS_FULL)
            elif not user.is_active:
                error = HttpError(403, "To konto jest wyłączone.")

    if error is not None:
        raise error
    assert user is not None  # noqa: S101 - narrowing for the type checker
    return user


class _NoPlace(Exception):
    pass


def _create_account(phone: str, for_testers: bool) -> User | None:
    """The new account; a tester's also joins the test location. None (and no account) when the test filled up
    between the code and the login."""
    if not for_testers:
        return User.objects.create_user(phone)
    from apps.tenancy import testers

    try:
        with transaction.atomic():
            user = User.objects.create_user(phone)
            if not testers.join(user):
                raise _NoPlace
    except _NoPlace:
        return None
    return user
