"""The iOS and Android apps: their origin may call the API, the session key travels in a header, the CSRF cookie
is not needed, and the session survives an app restart (docs/mobile.md, `apps/core/native.py`)."""

import re
from datetime import timedelta

import pytest
from django.contrib.sessions.models import Session
from django.test import Client
from django.utils import timezone

from apps.accounts.models import User
from apps.core.native import USED_ON_KEY

pytestmark = pytest.mark.django_db

PHONE = "+48601900100"
IOS = "capacitor://localhost"
ANDROID = "https://localhost"


class App:
    """The app on a phone: a client without cookies that keeps the session key it is handed, like the app's own
    storage does (`src/native/session-token.ts`). A new `App(key)` is the app started again."""

    def __init__(self, key: str | None = None, platform: str = "ios", origin: str = IOS):
        # Django's test client would keep cookies; CSRF checks on, as in a real browser.
        self.client = Client(enforce_csrf_checks=True)
        self.key, self.platform, self.origin = key, platform, origin

    def _headers(self) -> dict:
        headers = {"X-Grafikomat-Client": self.platform, "Origin": self.origin}
        if self.key:
            headers["X-Grafikomat-Session"] = self.key
        return headers

    def _keep(self, response):
        if "X-Grafikomat-Session" in response.headers:
            self.key = response.headers["X-Grafikomat-Session"] or None
        self.client.cookies.clear()
        return response

    def get(self, path):
        return self._keep(self.client.get(path, headers=self._headers()))

    def post(self, path, data=None):
        return self._keep(self.client.post(path, data or {}, content_type="application/json", headers=self._headers()))


def code_from(outbox) -> str:
    return re.search(r"\b(\d{6})\b", outbox[-1][1]).group(1)


def log_in(app: App, sms_outbox) -> dict:
    assert app.post("/api/auth/request-code", {"phone": PHONE}).status_code == 200
    response = app.post("/api/auth/verify-code", {"phone": PHONE, "code": code_from(sms_outbox)})
    assert response.status_code == 200, response.content
    return response.json()


def test_preflight_lets_in_only_the_apps():
    for origin in (IOS, ANDROID):
        response = Client().options(
            "/api/auth/request-code",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-grafikomat-client",
            },
        )
        assert response.status_code == 204
        assert response.headers["Access-Control-Allow-Origin"] == origin
        assert "X-Grafikomat-Session" in response.headers["Access-Control-Allow-Headers"]
        assert "Access-Control-Allow-Credentials" not in response.headers  # cookies never ride along

    other = Client().options(
        "/api/auth/request-code", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}
    )
    assert "Access-Control-Allow-Origin" not in other.headers


def test_app_logs_in_without_cookies_and_stays_logged_in_after_restart(sms_outbox):
    User.objects.create_user(PHONE, first_name="Halina")
    app = App()
    assert app.get("/api/me").status_code == 401

    me = log_in(app, sms_outbox)

    assert me["first_name"] == "Halina" and app.key
    assert Session.objects.filter(session_key=app.key).exists()
    # Restart: a new client with only the stored key.
    again = App(app.key)
    response = again.get("/api/me")
    assert response.status_code == 200 and response.json()["phone"] == PHONE
    assert response.headers["Access-Control-Allow-Origin"] == IOS
    assert response.headers["Access-Control-Expose-Headers"] == "X-Grafikomat-Session"
    # Nothing for the WebView's cookie jar.
    assert "sessionid" not in response.cookies and "csrftoken" not in response.cookies
    # Changes need no CSRF cookie in the app.
    assert again.post("/api/auth/logout").status_code == 204


def test_android_origin_works_the_same(sms_outbox):
    User.objects.create_user(PHONE)
    app = App(platform="android", origin=ANDROID)
    log_in(app, sms_outbox)
    response = App(app.key, platform="android", origin=ANDROID).get("/api/me")
    assert response.status_code == 200 and response.headers["Access-Control-Allow-Origin"] == ANDROID


def test_logout_empties_the_key_and_the_old_key_stops_working(sms_outbox):
    User.objects.create_user(PHONE)
    app = App()
    log_in(app, sms_outbox)
    old = app.key

    response = app.post("/api/auth/logout")

    assert response.status_code == 204 and response.headers["X-Grafikomat-Session"] == ""
    assert app.key is None
    stale = App(old)
    response = stale.get("/api/me")
    assert response.status_code == 401
    assert response.headers["X-Grafikomat-Session"] == ""  # the app forgets it too


def test_a_cookie_never_logs_an_app_request_in():
    user = User.objects.create_user(PHONE)
    client = Client()
    client.force_login(user)  # a session cookie, as a browser would have

    response = client.get("/api/me", headers={"X-Grafikomat-Client": "android"})

    assert response.status_code == 401


def test_browsers_still_need_the_csrf_token(sms_outbox):
    User.objects.create_user(PHONE)
    browser = Client(enforce_csrf_checks=True)
    refused = browser.post("/api/auth/request-code", {"phone": PHONE}, content_type="application/json")
    assert refused.status_code == 403
    # The web app's way: GET /me sets the CSRF cookie, which is sent back in the header.
    browser.get("/api/me")
    token = browser.cookies["csrftoken"].value
    sent = browser.post(
        "/api/auth/request-code", {"phone": PHONE}, content_type="application/json", headers={"X-CSRFToken": token}
    )
    assert sent.status_code == 200
    assert "Access-Control-Allow-Origin" not in sent.headers


def test_using_the_app_on_a_new_day_moves_the_end_of_the_session(sms_outbox, settings):
    User.objects.create_user(PHONE)
    app = App()
    log_in(app, sms_outbox)
    row = Session.objects.get(session_key=app.key)
    data = row.get_decoded()
    data[USED_ON_KEY] = (timezone.localdate() - timedelta(days=1)).isoformat()
    soon = timezone.now() + timedelta(days=2)
    Session.objects.filter(pk=row.pk).update(session_data=Session.objects.encode(data), expire_date=soon)

    assert App(app.key).get("/api/me").status_code == 200

    row.refresh_from_db()
    assert row.expire_date > timezone.now() + timedelta(seconds=settings.SESSION_COOKIE_AGE - 60)
    assert row.get_decoded()[USED_ON_KEY] == timezone.localdate().isoformat()


def test_a_changed_phone_number_logs_the_app_out_too(sms_outbox):
    user = User.objects.create_user(PHONE)
    app = App()
    log_in(app, sms_outbox)
    user.phone_e164 = "+48601900199"
    user.save()

    assert App(app.key).get("/api/me").status_code == 401
