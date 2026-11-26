"""Push notifications to the iOS and Android apps (docs/mobile.md).

A notification is still a row first (`services.notify`). When someone it is for has a phone with the app, the same
transaction queues `tasks.send_push`; the worker then sends the notification's text to each of their phones:
iPhones through Apple's APNs, Android phones through Firebase Cloud Messaging (FCM v1). Tapping it opens the
screen of the shift or period it is about (`services.push_path`).

- A phone is registered after login from the app (`POST /me/push-devices`) and tied to that session: logging out
  (`forget_session`), the session ending or the account being switched off unpins it, so a phone where nobody is
  logged in gets nothing.
- A notification goes out only while its person still has access to its company (a removed employee keeps a
  membership for the schedule history, but no access); the phone keeps getting the person's other companies.
- One deadline for the services too: a push that is not on the phone `PUSH_MAX_AGE_S` after the notification was
  written is dropped by APNs and FCM as well (a phone back online does not get yesterday's offer). It is checked
  right before every request, because FCM reads `ttl: 0s` as "deliver now or never", not "already too late".
- A token the service no longer knows (app removed) is deleted. Other failures are logged and not retried: the
  notification is in the app anyway, and a retry would repeat it on the phones that already got it.
- Credentials come only from files named in the environment (settings `PUSH_*`); without them nothing is sent.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from importlib import import_module
from pathlib import Path

import httpx2
import jwt
from django.conf import settings
from django.contrib.auth import HASH_SESSION_KEY, SESSION_KEY
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from apps.notifications.models import Notification, PushDevice
from apps.tenancy.context import removed_from_company
from apps.tenancy.models import Membership

logger = logging.getLogger(__name__)

TITLE = "Grafikomat"
# Android notification channel the app creates (src/native/push.ts): its name is what the phone's settings show.
ANDROID_CHANNEL = "grafik"
TIMEOUT_S = 10


@dataclass(frozen=True)
class Message:
    notification_id: str
    company_id: str
    body: str
    # Route of the app to open on tap, e.g. "/grafik?dzien=2026-12-04".
    path: str
    # Unix time after which the push is not worth showing any more (`PUSH_MAX_AGE_S` after the notification).
    expires_at: int

    def seconds_left(self) -> int:
        return max(0, self.expires_at - int(time.time()))


class Outcome(Enum):
    SENT = "sent"
    GONE = "gone"  # the service does not know the token any more: forget the phone
    FAILED = "failed"
    # The deadline passed before this phone's turn (an earlier phone or a token refresh took the time): not sent.
    EXPIRED = "expired"


# ----------------------------------------------------------------------------------------------- registering


def register_device(user, session_key: str, platform: str, token: str) -> PushDevice:
    """This phone gets my notifications from now on (a token seen before moves to me and this session)."""
    device, _ = PushDevice.objects.update_or_create(
        token=token,
        defaults={"user": user, "platform": platform, "session_key": session_key, "seen_at": timezone.now()},
    )
    return device


def forget_session(user, session_key: str | None) -> int:
    """Logging out: phones registered from this session stop getting notifications."""
    if not session_key or user is None or not user.is_authenticated:
        return 0
    deleted, _ = PushDevice.objects.filter(user=user, session_key=session_key).delete()
    return deleted


def queue(notifications: list[Notification]) -> None:
    """Called where notifications are written, inside the same transaction: the job is saved with them."""
    if not notifications:
        return
    users = {n.user_id for n in notifications}
    if not PushDevice.objects.filter(user_id__in=users).exists():
        return
    from apps.notifications.tasks import send_push

    send_push.defer(notification_ids=[str(n.pk) for n in notifications])


# ----------------------------------------------------------------------------------------------- sending


def deliver(notification_ids: list[str]) -> int:
    """Send these notifications to the phones of the people they are for. Returns how many pushes went out."""
    from apps.notifications.services import push_path, push_text

    senders = configured_senders()
    if not senders:
        logger.warning("push: no APNs or FCM credentials, %s notifications stay in the app", len(notification_ids))
        return 0
    oldest = timezone.now() - timedelta(seconds=settings.PUSH_MAX_AGE_S)
    # Seen or removed in the meantime, or too old: only in the app.
    rows = Notification.objects.filter(  # tenant-ok: the job's own notifications, by id
        pk__in=notification_ids, read_at__isnull=True, created_at__gte=oldest
    )
    sent = 0
    devices_of: dict = {}
    allowed: dict = {}
    for note in rows:
        key = (note.user_id, note.company_id)
        if key not in allowed:
            allowed[key] = _has_access(note.user_id, note.company_id)
        if not allowed[key]:
            continue
        message = Message(
            notification_id=str(note.pk),
            company_id=str(note.company_id),
            body=push_text(note.kind, note.payload),
            path=push_path(note.kind, note.payload),
            expires_at=int((note.created_at + timedelta(seconds=settings.PUSH_MAX_AGE_S)).timestamp()),
        )
        if message.seconds_left() <= 0:
            continue
        if note.user_id not in devices_of:
            devices_of[note.user_id] = _signed_in_devices(note.user_id)
        for device in devices_of[note.user_id]:
            sender = senders.get(device.platform)
            if sender is None:
                continue
            outcome = sender.send(device, message)
            if outcome is Outcome.SENT:
                sent += 1
            elif outcome is Outcome.GONE:
                logger.info("push: %s token unknown to the service, phone unpinned", device.platform)
                device.delete()
                devices_of[note.user_id] = [d for d in devices_of[note.user_id] if d.pk != device.pk]
    return sent


def _has_access(user_id, company_id) -> bool:
    """The person may still open this company in the app (the same check as `tenant_context`)."""
    membership = Membership.objects.filter(user_id=user_id, company_id=company_id).first()
    return membership is not None and not removed_from_company(membership)


def _signed_in_devices(user_id) -> list[PushDevice]:
    """The person's phones whose session still logs them in; the others are unpinned here. A switched-off account
    (`is_active=False`) logs nobody in, whatever its sessions hold (`ModelBackend.get_user`)."""
    store_class = import_module(settings.SESSION_ENGINE).SessionStore
    result = []
    for device in PushDevice.objects.filter(user_id=user_id).select_related("user"):
        data = store_class(session_key=device.session_key).load()  # {} once the session ended or expired
        hash_now = device.user.get_session_auth_hash()
        if (
            device.user.is_active
            and data.get(SESSION_KEY) == str(device.user_id)
            and constant_time_compare(data.get(HASH_SESSION_KEY, ""), hash_now)
        ):
            result.append(device)
        else:
            device.delete()
    return result


_senders: dict | None = None


def configured_senders() -> dict:
    """{"ios": ApnsSender, "android": FcmSender} for the services with credentials (built once per process)."""
    global _senders
    if _senders is None:
        _senders = {}
        if settings.PUSH_APNS_KEY_FILE and settings.PUSH_APNS_KEY_ID and settings.PUSH_APNS_TEAM_ID:
            _senders["ios"] = ApnsSender(
                key=Path(settings.PUSH_APNS_KEY_FILE).read_text(),
                key_id=settings.PUSH_APNS_KEY_ID,
                team_id=settings.PUSH_APNS_TEAM_ID,
                topic=settings.PUSH_APNS_TOPIC,
                sandbox=settings.PUSH_APNS_SANDBOX,
            )
        if settings.PUSH_FCM_CREDENTIALS_FILE:
            _senders["android"] = FcmSender(json.loads(Path(settings.PUSH_FCM_CREDENTIALS_FILE).read_text()))
    return _senders


def reset_senders() -> None:
    """Tests and a changed configuration: build the senders again on the next send."""
    global _senders
    _senders = None


class ApnsSender:
    """Apple Push Notification service over HTTP/2 with a token (.p8 key) signed by the team."""

    PRODUCTION = "https://api.push.apple.com"
    SANDBOX = "https://api.sandbox.push.apple.com"
    # Apple wants a new signed token at most every 20 minutes and refuses one older than an hour.
    TOKEN_LIFETIME_S = 45 * 60

    def __init__(self, *, key: str, key_id: str, team_id: str, topic: str, sandbox: bool = False, client=None):
        self.key, self.key_id, self.team_id, self.topic, self.sandbox = key, key_id, team_id, topic, sandbox
        self.client = client or httpx2.Client(http2=True, timeout=TIMEOUT_S)
        self._token: tuple[str, float] | None = None

    def _bearer(self) -> str:
        now = time.time()
        if self._token is None or now - self._token[1] > self.TOKEN_LIFETIME_S:
            signed = jwt.encode(
                {"iss": self.team_id, "iat": int(now)}, self.key, algorithm="ES256", headers={"kid": self.key_id}
            )
            self._token = (signed, now)
        return self._token[0]

    def payload(self, message: Message) -> dict:
        return {
            "aps": {"alert": {"title": TITLE, "body": message.body}, "sound": "default"},
            "path": message.path,
            "company_id": message.company_id,
            "notification_id": message.notification_id,
        }

    def _post(self, sandbox: bool, device: PushDevice, message: Message):
        """The request, or None when the deadline has passed (nothing is sent)."""
        if message.seconds_left() <= 0:
            return None
        host = self.SANDBOX if sandbox else self.PRODUCTION
        return self.client.post(
            f"{host}/3/device/{device.token}",
            json=self.payload(message),
            headers={
                "authorization": f"bearer {self._bearer()}",
                "apns-topic": self.topic,
                "apns-push-type": "alert",
                "apns-priority": "10",
                # Not on the phone by then (phone off): dropped, the app shows it anyway.
                "apns-expiration": str(message.expires_at),
                "apns-collapse-id": message.notification_id[:64],
            },
        )

    def send(self, device: PushDevice, message: Message) -> Outcome:
        sandbox = device.sandbox or self.sandbox
        try:
            response = self._post(sandbox, device, message)
            if response is None:
                return Outcome.EXPIRED
            reason = _apns_reason(response)
            if response.status_code == 400 and reason == "BadDeviceToken":
                # A token of the other environment (an Xcode build against the production service, or the reverse).
                response = self._post(not sandbox, device, message)
                if response is None:
                    return Outcome.EXPIRED
                reason = _apns_reason(response)
                if response.status_code == 200 and device.sandbox != (not sandbox):
                    device.sandbox = not sandbox
                    device.save(update_fields=["sandbox"])
        except httpx2.HTTPError as exc:
            logger.warning("push: APNs request failed: %s", exc)
            return Outcome.FAILED
        if response.status_code == 200:
            return Outcome.SENT
        if response.status_code == 410 or reason in ("BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic"):
            return Outcome.GONE
        logger.warning("push: APNs answered %s %s", response.status_code, reason)
        return Outcome.FAILED


def _apns_reason(response) -> str:
    try:
        return str(response.json().get("reason", ""))
    except ValueError:
        return ""


class FcmSender:
    """Firebase Cloud Messaging HTTP v1, authorized with the project's service account."""

    SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

    def __init__(self, credentials: dict, client=None):
        self.credentials = credentials
        self.project_id = credentials["project_id"]
        self.client = client or httpx2.Client(timeout=TIMEOUT_S)
        self._access: tuple[str, float] | None = None

    def _access_token(self, *, fresh: bool = False) -> str:
        now = time.time()
        if fresh or self._access is None or now >= self._access[1]:
            token_uri = self.credentials.get("token_uri", "https://oauth2.googleapis.com/token")
            assertion = jwt.encode(
                {
                    "iss": self.credentials["client_email"],
                    "scope": self.SCOPE,
                    "aud": token_uri,
                    "iat": int(now),
                    "exp": int(now) + 3600,
                },
                self.credentials["private_key"],
                algorithm="RS256",
                headers={"kid": self.credentials.get("private_key_id", "")},
            )
            response = self.client.post(
                token_uri,
                data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
            )
            response.raise_for_status()
            body = response.json()
            self._access = (body["access_token"], now + int(body.get("expires_in", 3600)) - 60)
        return self._access[0]

    def payload(self, device: PushDevice, message: Message) -> dict:
        return {
            "message": {
                "token": device.token,
                "notification": {"title": TITLE, "body": message.body},
                # Read by the app when the notification is tapped, also when the app was closed.
                "data": {
                    "path": message.path,
                    "company_id": message.company_id,
                    "notification_id": message.notification_id,
                },
                "android": {
                    "priority": "HIGH",
                    # Time left until the same deadline as APNs (FCM wants a duration, not a date).
                    "ttl": f"{message.seconds_left()}s",
                    "notification": {"channel_id": ANDROID_CHANNEL, "tag": message.notification_id},
                },
            }
        }

    def _post(self, device: PushDevice, message: Message, access_token: str):
        """The request, or None when the deadline has passed. The access token comes first (getting one takes a
        request of its own), then the deadline is checked and `ttl` worked out from it."""
        if message.seconds_left() <= 0:
            return None
        return self.client.post(
            f"https://fcm.googleapis.com/v1/projects/{self.project_id}/messages:send",
            json=self.payload(device, message),
            headers={"Authorization": f"Bearer {access_token}"},
        )

    def send(self, device: PushDevice, message: Message) -> Outcome:
        if message.seconds_left() <= 0:
            return Outcome.EXPIRED
        try:
            response = self._post(device, message, self._access_token())
            if response is not None and response.status_code == 401:
                response = self._post(device, message, self._access_token(fresh=True))
        except httpx2.HTTPError as exc:
            logger.warning("push: FCM request failed: %s", exc)
            return Outcome.FAILED
        if response is None:
            return Outcome.EXPIRED
        if response.status_code == 200:
            return Outcome.SENT
        code, text = _fcm_error(response)
        if response.status_code == 404 or code == "UNREGISTERED" or "registration token" in text.lower():
            return Outcome.GONE
        logger.warning("push: FCM answered %s %s", response.status_code, code or text[:120])
        return Outcome.FAILED


def _fcm_error(response) -> tuple[str, str]:
    try:
        error = response.json().get("error", {})
    except ValueError:
        return "", ""
    codes = [d.get("errorCode", "") for d in error.get("details", []) if isinstance(d, dict)]
    return next((c for c in codes if c), ""), str(error.get("message", ""))
