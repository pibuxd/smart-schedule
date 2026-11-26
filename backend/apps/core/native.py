"""Requests from the iOS and Android apps (Capacitor, docs/mobile.md).

The apps show the same SPA, loaded from their own origin (`capacitor://localhost` on iOS, `https://localhost` on
Android), and call the API on the server's domain. A WebView does not keep cookies of another site reliably (iOS
blocks them as third-party cookies), so an app request:

- says it is from the app with `X-Grafikomat-Client: ios|android`;
- carries the Django session key in `X-Grafikomat-Session` instead of the session cookie; the key is handed over
  in the same header of the response whenever it changes (login gives a new one, logout and an ended session
  give an empty one), and the app keeps it in its own storage, so a restart keeps the person logged in;
- is never authenticated by a cookie, so the CSRF check (which protects cookies) is not needed: a browser sends
  these headers to another site only after a CORS check, and only the apps' origins pass it here;
- keeps its session alive: a day the app is used moves the end of the session to SESSION_COOKIE_AGE from then.

Browsers on the server's own domain send none of these headers and work exactly as before.
"""

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from django.utils.cache import patch_vary_headers

CLIENT_HEADER = "X-Grafikomat-Client"
SESSION_HEADER = "X-Grafikomat-Session"
PLATFORMS = ("ios", "android")
# Any other value still counts as the app (the header alone decides how the request is authenticated).
OTHER = "app"
# The session remembers the last day the app was used; the first request of a new day saves it again.
USED_ON_KEY = "grafikomat_app_used_on"


def app_platform(request: HttpRequest) -> str | None:
    """'ios' or 'android' for a request from the apps ("app" for another value), None for a browser."""
    return getattr(request, "native_app", None)


class NativeAppMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        origin = request.headers.get("Origin", "")
        allowed = origin in settings.NATIVE_APP_ORIGINS
        if request.method == "OPTIONS" and allowed and "Access-Control-Request-Method" in request.headers:
            return self._preflight(origin)

        client = request.headers.get(CLIENT_HEADER)
        sent = None
        if client is not None:
            request.native_app = client if client in PLATFORMS else OTHER
            # Cookies never log an app request in: only the key the app sends does.
            request.COOKIES.pop(settings.SESSION_COOKIE_NAME, None)
            request.COOKIES.pop(settings.CSRF_COOKIE_NAME, None)
            sent = request.headers.get(SESSION_HEADER, "").strip() or None
            if sent:
                request.COOKIES[settings.SESSION_COOKIE_NAME] = sent
            request._dont_enforce_csrf_checks = True

        response = self.get_response(request)

        if allowed:
            response["Access-Control-Allow-Origin"] = origin
            response["Access-Control-Expose-Headers"] = SESSION_HEADER
            patch_vary_headers(response, ("Origin",))
        if client is not None:
            self._hand_over_session(request, response, sent)
        return response

    def process_view(self, request: HttpRequest, view_func, view_args, view_kwargs):
        """Keep an app session alive while the app is used (saved by SessionMiddleware after the view)."""
        if app_platform(request) is None or not request.user.is_authenticated:
            return None
        today = timezone.localdate().isoformat()
        if request.session.get(USED_ON_KEY) != today:
            request.session[USED_ON_KEY] = today
        return None

    @staticmethod
    def _preflight(origin: str) -> HttpResponse:
        response = HttpResponse(status=204)
        response["Access-Control-Allow-Origin"] = origin
        response["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE"
        response["Access-Control-Allow-Headers"] = f"Content-Type, {CLIENT_HEADER}, {SESSION_HEADER}"
        response["Access-Control-Max-Age"] = "86400"
        response["Vary"] = "Origin"
        return response

    @staticmethod
    def _hand_over_session(request: HttpRequest, response: HttpResponse, sent: str | None) -> None:
        session = getattr(request, "session", None)
        key = session.session_key if session is not None else sent
        if key != sent:
            response[SESSION_HEADER] = key or ""
        # The app reads the key from the header; cookies for its WebView would only linger there.
        for name in (settings.SESSION_COOKIE_NAME, settings.CSRF_COOKIE_NAME):
            response.cookies.pop(name, None)
