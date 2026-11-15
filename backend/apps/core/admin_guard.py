"""A limit on failed logins to the Django admin (only the superuser has a password, so guessing is the risk)."""

from django.conf import settings
from django.contrib import admin
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse

from apps.core.http import client_ip

WINDOW_S = 60 * 60


def _key(request: HttpRequest) -> str:
    return f"admin-login-failures:{client_ip(request)}"


def admin_login(request: HttpRequest, extra_context=None) -> HttpResponse:
    """The admin's login view, refusing an address after too many failed tries in an hour.
    The counter lives in the cache of each server process, which is enough to make guessing slow."""
    if request.method == "POST" and cache.get(_key(request), 0) >= settings.ADMIN_LOGIN_FAILURES_PER_IP_PER_HOUR:
        return HttpResponse("Za dużo nieudanych prób logowania. Spróbuj ponownie za godzinę.", status=429)
    response = admin.site.login(request, extra_context)
    # A successful login redirects; a failed one shows the form again.
    if request.method == "POST" and response.status_code == 200:
        key = _key(request)
        cache.add(key, 0, WINDOW_S)
        cache.incr(key)
    return response
