"""Django settings. Every value that differs between environments comes from env vars."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable {name}")
    return value


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-key-change-me" if DEBUG else None)


def env_list(name: str, default: str) -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "http://localhost:8080,http://localhost:5173")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "ninja",
    "procrastinate.contrib.django",
    "apps.core",
    "apps.accounts",
    "apps.tenancy",
    "apps.billing",
    "apps.staffing",
    "apps.scheduling",
    "apps.availability",
    "apps.rules",
    "apps.marketplace",
    "apps.reports",
    "apps.notifications",
    "apps.assistant",
    "apps.worktime",
    "apps.pay",
]

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # The iOS and Android apps: their origin may call the API, and their session key comes in a header (before
    # SessionMiddleware, which reads it). Browsers are not affected.
    "apps.core.native.NativeAppMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "grafikomat"),
        "USER": env("POSTGRES_USER", "grafikomat"),
        "PASSWORD": env("POSTGRES_PASSWORD", "grafikomat"),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "pl"
TIME_ZONE = "Europe/Warsaw"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Sessions: ~60 days, cookie only over HTTPS outside local development.
SESSION_COOKIE_AGE = 60 * 24 * 60 * 60
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = not DEBUG

# The iOS and Android apps (Capacitor, docs/mobile.md) load their screens from these origins and call the API
# across origins, with the session key in a header instead of a cookie. Their sessions last SESSION_COOKIE_AGE from
# the last day the app was used.
NATIVE_APP_ORIGINS = env_list("NATIVE_APP_ORIGINS", "capacitor://localhost,https://localhost")

# Behind Caddy.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# How many reverse proxies we trust to set X-Forwarded-For (1 behind Caddy, 0 when the API is reached directly).
# Rate limits use the client address, so a wrong value either merges all users into one address or lets
# a client fake its address.
NUM_PROXIES = int(env("DJANGO_NUM_PROXIES", "0"))

# Login with an SMS code (the only way app users log in).
SMS_BACKEND = env("SMS_BACKEND", "apps.accounts.sms.ConsoleSmsSender")
LOGIN_CODE_TTL_S = 5 * 60
LOGIN_CODE_MAX_ATTEMPTS = 5
LOGIN_CODE_RESEND_AFTER_S = int(env("LOGIN_CODE_RESEND_AFTER_S", "60"))
LOGIN_CODES_PER_PHONE_PER_HOUR = int(env("LOGIN_CODES_PER_PHONE_PER_HOUR", "5"))
LOGIN_CODES_PER_IP_PER_HOUR = int(env("LOGIN_CODES_PER_IP_PER_HOUR", "20"))
# New numbers (no account, no invitation) one address may send a registration code to per hour.
REGISTER_NUMBERS_PER_IP_PER_HOUR = int(env("REGISTER_NUMBERS_PER_IP_PER_HOUR", "5"))
# The szybkisms.pl gateway (SMS_BACKEND=apps.accounts.sms.SzybkiSmsSender): the API token made in its panel, the
# sender name (empty = the account's default) and its sandbox, which sends nothing (Piotr, 28.11.2026).
SZYBKISMS_TOKEN = env("SZYBKISMS_TOKEN", "").strip()
SZYBKISMS_SENDER = env("SZYBKISMS_SENDER", "").strip()
SZYBKISMS_SANDBOX = env_bool("SZYBKISMS_SANDBOX", False)
# The closed test of the phone apps (apps/tenancy/testers.py): a new Polish number that logs in joins this location
# as a manager or an employee, drawn from the places still free. Empty = off; turn it off before everyone may sign up.
TESTERS_LOCATION_ID = env("TESTERS_LOCATION_ID", "").strip()
TESTERS_MANAGERS = int(env("TESTERS_MANAGERS", "3"))
TESTERS_EMPLOYEES = int(env("TESTERS_EMPLOYEES", "15"))
# The store reviewers' account (Google Play and Apple need a login that works without a one-time code): this number
# logs in with this fixed 6-digit code and gets no SMS. Both empty = off.
REVIEW_LOGIN_PHONE = env("REVIEW_LOGIN_PHONE", "").strip()
REVIEW_LOGIN_CODE = env("REVIEW_LOGIN_CODE", "").strip()

# Django admin (superuser password): failed logins allowed per address per hour.
ADMIN_LOGIN_FAILURES_PER_IP_PER_HOUR = int(env("ADMIN_LOGIN_FAILURES_PER_IP_PER_HOUR", "10"))

# Free-access codes: failed attempts allowed per hour before further tries are refused.
ACCESS_CODE_FAILURES_PER_USER_PER_HOUR = int(env("ACCESS_CODE_FAILURES_PER_USER_PER_HOUR", "5"))
ACCESS_CODE_FAILURES_PER_IP_PER_HOUR = int(env("ACCESS_CODE_FAILURES_PER_IP_PER_HOUR", "20"))
# The manager's panel shows the access strip this many days before access from a code ends, and the trial's
# strip only in its last TRIAL_BANNER_DAYS (Piotr, 26.11.2026); a read-only company always sees it.
SUBSCRIPTION_BANNER_DAYS = 7
TRIAL_BANNER_DAYS = 2
# A company registered without a code gets this many days of full access (once per person who registers).
TRIAL_DAYS = int(env("TRIAL_DAYS", "30"))

# Push notifications to the iOS and Android apps (docs/mobile.md), sent by the worker. Nothing is configured by
# default: without these the notifications stay in the app only. Keys are files outside the repository.
# iPhone (APNs): the .p8 key from developer.apple.com (Keys), its id, the team id and the app's bundle id.
PUSH_APNS_KEY_FILE = env("PUSH_APNS_KEY_FILE", "").strip()
PUSH_APNS_KEY_ID = env("PUSH_APNS_KEY_ID", "").strip()
PUSH_APNS_TEAM_ID = env("PUSH_APNS_TEAM_ID", "").strip()
PUSH_APNS_TOPIC = env("PUSH_APNS_TOPIC", "pl.grafikomat.app").strip()
# Builds from Xcode use Apple's sandbox; TestFlight and App Store builds the production service. A token the first
# one refuses is tried at the other and remembered per phone.
PUSH_APNS_SANDBOX = env_bool("PUSH_APNS_SANDBOX", False)
# Android (Firebase Cloud Messaging): the service account JSON of the Firebase project.
PUSH_FCM_CREDENTIALS_FILE = env("PUSH_FCM_CREDENTIALS_FILE", "").strip()
# A notification the worker reaches later than this (worker stopped for a while) stays in the app only.
PUSH_MAX_AGE_S = int(env("PUSH_MAX_AGE_S", str(6 * 60 * 60)))

# Background jobs (Procrastinate on Postgres).
PROCRASTINATE_AUTODISCOVER_MODULE_NAME = "tasks"

# Scheduling engine: time limit of one generation and CPU threads CP-SAT may use for it.
SOLVER_TIME_LIMIT_S = int(env("SOLVER_TIME_LIMIT_S", "30"))
SOLVER_WORKERS = int(env("SOLVER_WORKERS", "8"))

# The assistant (a language model) reads employees' text requests and the manager's commands. Without a key it is
# off: requests go to the manager as written and the manager sets rules by hand. OpenRouter is used when its key is
# set (since 21.11.2026), else Anthropic's API (Claude).
OPENROUTER_API_KEY = env("OPENROUTER_API_KEY", "").strip()
# Model id as on openrouter.ai/models.
OPENROUTER_MODEL = env("OPENROUTER_MODEL", "").strip() or "deepseek/deepseek-v4.1-flash"
# reasoning.effort: how much the model thinks on each call (none|minimal|low|medium|high|xhigh). Empty = model default.
OPENROUTER_EFFORT = env("OPENROUTER_EFFORT", "low").strip().lower()
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = env("ANTHROPIC_MODEL", "claude-opus-5-5")
# output_config.effort: how much the model thinks on each call (low|medium|high|xhigh|max). Empty = model default.
ANTHROPIC_EFFORT = env("ANTHROPIC_EFFORT", "low").strip().lower()
# Below this confidence a request is left to the manager instead of the generator.
ASSISTANT_MIN_CONFIDENCE = float(env("ASSISTANT_MIN_CONFIDENCE", "0.6"))
# Limits on writing to the assistant, off by default since 20.11.2026 (0 = no limit; Piotr's decision). A number
# turns one back on: messages from one company's managers per month (questions included), saved requests of one
# person per period (questions and refused messages do not count), and messages of one person per day.
ASSISTANT_COMMANDS_MONTHLY_LIMIT = int(env("ASSISTANT_COMMANDS_MONTHLY_LIMIT", "0"))
TEXT_REQUESTS_PER_PERIOD = int(env("TEXT_REQUESTS_PER_PERIOD", "0"))
ASSISTANT_MESSAGES_PER_DAY = int(env("ASSISTANT_MESSAGES_PER_DAY", "0"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}
