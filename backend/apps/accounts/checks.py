"""System checks shown by every `manage.py` command (migrate, runserver, worker)."""

from django.conf import settings
from django.core.checks import Warning as CheckWarning
from django.core.checks import register

CONSOLE_SMS = "apps.accounts.sms.ConsoleSmsSender"


@register()
def login_codes_must_not_go_to_the_log_in_production(app_configs, **kwargs):
    if settings.DEBUG or settings.SMS_BACKEND != CONSOLE_SMS:
        return []
    return [
        CheckWarning(
            "Login codes are written to the server log instead of being sent by SMS.",
            hint="Anyone who can read the logs can log in as any user. Before real people use this server, "
            "set SMS_BACKEND to a real SMS gateway class.",
            id="accounts.W001",
        )
    ]


SZYBKISMS = "apps.accounts.sms.SzybkiSmsSender"


@register()
def sms_gateway_has_a_token(app_configs, **kwargs):
    if settings.SMS_BACKEND != SZYBKISMS or settings.SZYBKISMS_TOKEN:
        return []
    return [
        CheckWarning(
            "SMS_BACKEND is the szybkisms.pl gateway, but SZYBKISMS_TOKEN is empty, so no login code can be sent.",
            hint="Generate an API token in the szybkisms.pl panel (REST API) and put it in .env as SZYBKISMS_TOKEN.",
            id="accounts.W002",
        )
    ]


@register()
def closed_test_is_on(app_configs, **kwargs):
    if not settings.TESTERS_LOCATION_ID:
        return []
    return [
        CheckWarning(
            "The closed test is on: every new Polish number that logs in joins the test location.",
            hint="Empty TESTERS_LOCATION_ID before the app is published for everyone (docs/mobile.md).",
            id="accounts.W003",
        )
    ]


@register()
def review_login_is_complete(app_configs, **kwargs):
    from apps.accounts.login import review_phone

    phone, code = settings.REVIEW_LOGIN_PHONE, settings.REVIEW_LOGIN_CODE
    if not phone and not code:
        return []
    if review_phone() is not None:
        return []
    return [
        CheckWarning(
            "The store reviewers' login is off: it needs REVIEW_LOGIN_PHONE (a valid number) and "
            "REVIEW_LOGIN_CODE (6 digits).",
            hint="Set both in .env, or remove both.",
            id="accounts.W004",
        )
    ]
