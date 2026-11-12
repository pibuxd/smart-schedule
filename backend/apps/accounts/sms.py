"""Sending SMS messages. Only login codes are ever sent; everything else is an in-app notification.

The sender is replaceable: `settings.SMS_BACKEND` is a dotted path to a class with `send(phone, text)`.
Locally the message is written to the console. A real gateway (e.g. SMSAPI.pl) arrives with deployment.
"""

import logging
from typing import Protocol

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


class SmsSender(Protocol):
    def send(self, phone_e164: str, text: str) -> None: ...


class ConsoleSmsSender:
    """Writes the message to the log instead of sending it. For local runs and the prototype."""

    def send(self, phone_e164: str, text: str) -> None:
        logger.warning("SMS to %s: %s", phone_e164, text)


class MemorySmsSender:
    """Keeps messages in memory. Used by tests to read the code that would have been sent."""

    outbox: list[tuple[str, str]] = []  # noqa: RUF012 - shared on purpose, cleared by the test fixture

    def send(self, phone_e164: str, text: str) -> None:
        self.outbox.append((phone_e164, text))


def get_sms_sender() -> SmsSender:
    return import_string(settings.SMS_BACKEND)()
