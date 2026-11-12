"""Small request helpers shared by API modules."""

from django.conf import settings
from django.http import HttpRequest
from ninja.errors import HttpError
from ninja.utils import check_csrf


def client_ip(request: HttpRequest) -> str | None:
    """Address of the browser. Behind Caddy it is the entry of X-Forwarded-For added by the last trusted proxy."""
    if settings.NUM_PROXIES > 0:
        forwarded = [part.strip() for part in request.headers.get("X-Forwarded-For", "").split(",") if part.strip()]
        if len(forwarded) >= settings.NUM_PROXIES:
            return forwarded[-settings.NUM_PROXIES]
    return request.META.get("REMOTE_ADDR")


def require_csrf(request: HttpRequest) -> None:
    """CSRF check for endpoints without session auth (login). Session-authenticated endpoints get it from Ninja."""
    if check_csrf(request) is not None:
        raise HttpError(403, "Odśwież stronę i spróbuj ponownie.")
