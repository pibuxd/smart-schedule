"""Sending SMS messages. Only login codes are ever sent; everything else is an in-app notification.

The sender is replaceable: `settings.SMS_BACKEND` is a dotted path to a class with `send(phone, text)`.
Locally the message is written to the console; on the server it goes through the szybkisms.pl gateway
(`SzybkiSmsSender`, Piotr 28.11.2026). A sender raises when the message did not go out: the caller then tells the
person and the code does not count toward their limits.
"""

import logging
from typing import Protocol

import httpx2
from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


class SmsSender(Protocol):
    def send(self, phone_e164: str, text: str) -> None: ...


class SmsNotSent(Exception):
    """The gateway did not take the message. The text never contains the message (it holds a login code)."""


class ConsoleSmsSender:
    """Writes the message to the log instead of sending it. For local runs and the prototype."""

    def send(self, phone_e164: str, text: str) -> None:
        logger.warning("SMS to %s: %s", phone_e164, text)


class MemorySmsSender:
    """Keeps messages in memory. Used by tests to read the code that would have been sent."""

    outbox: list[tuple[str, str]] = []  # noqa: RUF012 - shared on purpose, cleared by the test fixture

    def send(self, phone_e164: str, text: str) -> None:
        self.outbox.append((phone_e164, text))


class SzybkiSmsSender:
    """The szybkisms.pl gateway, REST API 1.3 (https://api.szybkisms.pl/rest/): `POST /messages/sms` with the
    account's API token (`SZYBKISMS_TOKEN`) as a Bearer token.

    Polish letters go without their marks (`unicode: false`), so a login code fits in one SMS and costs one message.
    The gateway answers 200 with one result per message; a message it did not queue (`status_code` REJECTED) is
    a failure like a refused request. `SZYBKISMS_SANDBOX` uses the gateway's test system, which sends nothing.
    """

    PRODUCTION_URL = "https://api.szybkisms.pl/rest"
    SANDBOX_URL = "https://api.szybkisms.pl/rest-sandbox"
    TIMEOUT_S = 10

    def __init__(self, client: httpx2.Client | None = None):
        self.client = client

    def send(self, phone_e164: str, text: str) -> None:
        token = settings.SZYBKISMS_TOKEN
        if not token:
            raise SmsNotSent("SZYBKISMS_TOKEN is empty")
        body: dict = {"recipients": phone_e164, "message": text, "unicode": False}
        if settings.SZYBKISMS_SENDER:
            body["sender"] = settings.SZYBKISMS_SENDER
        base = self.SANDBOX_URL if settings.SZYBKISMS_SANDBOX else self.PRODUCTION_URL
        headers = {"Authorization": f"Bearer {token}"}
        if self.client is not None:
            response = self.client.post(f"{base}/messages/sms", json=body, headers=headers)
        else:
            with httpx2.Client(timeout=self.TIMEOUT_S) as client:
                response = client.post(f"{base}/messages/sms", json=body, headers=headers)
        if response.status_code != 200:
            raise SmsNotSent(f"szybkisms.pl answered {response.status_code}: {_problem(response)}")
        result = _first_result(response)
        status = str(result.get("status_code") or "")
        if not status or status == "REJECTED":
            reason = result.get("status_description") or "no result for the message"
            raise SmsNotSent(f"szybkisms.pl did not queue the SMS ({status or 'no status'}): {reason}")


def _problem(response: httpx2.Response) -> str:
    """The gateway's own words about a refused request (RFC 9457 problem details), without the request body."""
    try:
        problem = response.json()
    except ValueError:
        return response.text[:200]
    if not isinstance(problem, dict):
        return str(problem)[:200]
    return " ".join(str(problem[key]) for key in ("title", "detail", "code") if problem.get(key)) or str(problem)[:200]


def _first_result(response: httpx2.Response) -> dict:
    try:
        results = response.json()
    except ValueError:
        return {}
    if isinstance(results, list) and results and isinstance(results[0], dict):
        return results[0]
    return results if isinstance(results, dict) else {}


def get_sms_sender() -> SmsSender:
    return import_string(settings.SMS_BACKEND)()
