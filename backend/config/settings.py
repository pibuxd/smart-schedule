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
    "apps.notifications",
]

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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

# Free-access codes: failed attempts allowed per hour before further tries are refused.
ACCESS_CODE_FAILURES_PER_USER_PER_HOUR = int(env("ACCESS_CODE_FAILURES_PER_USER_PER_HOUR", "5"))
ACCESS_CODE_FAILURES_PER_IP_PER_HOUR = int(env("ACCESS_CODE_FAILURES_PER_IP_PER_HOUR", "20"))
SUBSCRIPTION_BANNER_DAYS = 7

# Background jobs (Procrastinate on Postgres).
PROCRASTINATE_AUTODISCOVER_MODULE_NAME = "tasks"

# Scheduling engine limits (used from stage 5 on).
SOLVER_TIME_LIMIT_S = int(env("SOLVER_TIME_LIMIT_S", "30"))
GENERATION_MONTHLY_LIMIT = int(env("GENERATION_MONTHLY_LIMIT", "30"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}
