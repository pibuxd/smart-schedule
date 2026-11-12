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
