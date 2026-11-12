"""Subscription state of a company and redeeming free-access codes."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil

from django.conf import settings
from django.utils import timezone
from ninja.errors import HttpError

from apps.billing.codes import hash_code, normalize_code
from apps.billing.models import AccessCode, CodeAttempt, CodeRedemption, GenerationUsage, Subscription
from apps.tenancy.models import Company

EXPIRED_MESSAGE = (
    "Dostęp tej firmy wygasł, więc dane można tylko oglądać. Kierownik może wpisać nowy kod w ustawieniach."
)
TRIAL_ENDED_MESSAGE = (
    "Okres próbny tej firmy minął, więc dane można tylko oglądać. Kierownik może wpisać kod dostępu w ustawieniach."
)
NOT_STARTED_MESSAGE = (
    "Ta firma nie ma jeszcze kodu dostępu, więc niczego nie można zmieniać. Kierownik wpisuje kod w ustawieniach."
)


@dataclass(frozen=True)
class SubscriptionState:
    ends_at: datetime | None
    is_active: bool
    days_left: int
    expiring_soon: bool
    # True while (or after) the company uses the free trial and has not entered a code yet.
    trial: bool = False

    @property
    def read_only(self) -> bool:
        return not self.is_active

    @property
    def read_only_message(self) -> str:
        """Access that never started is not "expired": a new manager must be told to enter a code."""
        if self.ends_at is None:
            return NOT_STARTED_MESSAGE
        return TRIAL_ENDED_MESSAGE if self.trial else EXPIRED_MESSAGE


def subscription_state(company_id, now: datetime | None = None) -> SubscriptionState:
    """A company without a subscription row (registered without a code) is read-only, like an expired one."""
    now = now or timezone.now()
    row = Subscription.objects.for_company(company_id).values_list("ends_at", "source").first()
    ends_at, source = row if row else (None, "")
    trial = source == Subscription.Source.TRIAL
    if ends_at is None or ends_at <= now:
        return SubscriptionState(ends_at=ends_at, is_active=False, days_left=0, expiring_soon=False, trial=trial)
    days_left = ceil((ends_at - now) / timedelta(days=1))
    return SubscriptionState(ends_at, True, days_left, days_left <= settings.SUBSCRIPTION_BANNER_DAYS, trial)


def start_trial(company: Company, user, now: datetime | None = None) -> Subscription | None:
    """Full access for `TRIAL_DAYS` for a company registered without a code (decision of 12.11.2026).

    Only the first company a person registers gets it, so registering again does not give endless free access.
    Call it inside the transaction that creates the company. Returns None when no trial is given.
    """
    if settings.TRIAL_DAYS <= 0:
        return None
    earlier = Company.objects.filter(created_by=user).exclude(pk=company.pk)  # tenant-ok: the person's own companies
    if earlier.exists():
        return None
    now = now or timezone.now()
    return Subscription.objects.create(
        company=company, ends_at=now + timedelta(days=settings.TRIAL_DAYS), source=Subscription.Source.TRIAL
    )


def generations_used_this_month(company_id, now: datetime | None = None) -> int:
    month = timezone.localdate(now or timezone.now()).replace(day=1)
    count = GenerationUsage.objects.for_company(company_id).filter(month=month).values_list("count", flat=True).first()
    return count or 0


class CodeRejected(Exception):
    """The code cannot be used; the message is shown to the manager."""


def redeem_code(company: Company, user, raw_code: str) -> Subscription:
    """Use a code for a company: extends access from the current end date (or from now, if it has passed).

    Call it inside `transaction.atomic()`. Raises CodeRejected; counting failed attempts is the caller's job
    (see `code_attempts`), because a rejected code usually rolls the surrounding transaction back.
    """
    now = timezone.now()
    normalized = normalize_code(raw_code)
    # The company row is the lock for its subscription, also when the subscription does not exist yet.
    Company.objects.select_for_update().get(pk=company.pk)
    code = (
        AccessCode.objects.select_for_update().filter(code_hash=hash_code(normalized)).first() if normalized else None
    )
    if code is None:
        raise CodeRejected("Nie ma takiego kodu. Sprawdź, czy jest dobrze przepisany.")
    if code.valid_until is not None and code.valid_until <= now:
        raise CodeRejected("Ten kod stracił ważność.")
    if CodeRedemption.objects.for_company(company).filter(code=code).exists():
        raise CodeRejected("Ten kod był już użyty w tej firmie.")
    if code.uses >= code.max_uses:
        raise CodeRejected("Ten kod został już wykorzystany.")

    subscription = Subscription.objects.for_company(company).first()
    if subscription is None:
        subscription = Subscription(company=company, ends_at=now)
    subscription.ends_at = max(subscription.ends_at, now) + timedelta(days=code.days)
    subscription.source = Subscription.Source.CODE
    subscription.save()

    code.uses += 1
    code.save(update_fields=["uses"])
    CodeRedemption.objects.create(company=company, code=code, user=user, redeemed_at=now, days_added=code.days)
    return subscription


def check_code_attempt_limit(user, ip: str | None) -> None:
    hour_ago = timezone.now() - timedelta(hours=1)
    failures = CodeAttempt.objects.filter(success=False, at__gt=hour_ago)
    too_many = failures.filter(user=user).count() >= settings.ACCESS_CODE_FAILURES_PER_USER_PER_HOUR or (
        ip is not None and failures.filter(ip=ip).count() >= settings.ACCESS_CODE_FAILURES_PER_IP_PER_HOUR
    )
    if too_many:
        raise HttpError(429, "Za dużo błędnych kodów. Spróbuj ponownie za godzinę.")


def record_code_attempt(user, ip: str | None, success: bool) -> None:
    CodeAttempt.objects.create(user=user, ip=ip, success=success)
