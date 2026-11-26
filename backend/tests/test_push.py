# ruff: noqa: F811  (the `market` and `shop` fixtures are imported)
"""Push notifications to the apps: registering a phone, unpinning it on logout, what is sent where, what a tap
opens, and the flow from giving a shift away to the manager's approval (docs/mobile.md)."""

import json
from datetime import timedelta

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from django.test import Client
from django.utils import timezone
from procrastinate.contrib.django.models import ProcrastinateJob

from apps.accounts.models import User
from apps.notifications import push
from apps.notifications.models import Notification, PushDevice
from apps.notifications.services import notify, push_path
from tests.test_generation import shop  # noqa: F401  (fixture)
from tests.test_marketplace import market, offer, user_of  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db

IOS_TOKEN = "a1" * 32
ANDROID_TOKEN = "fcm-token:" + "x" * 140


def app_session(user) -> str:
    """Log the person in and return the session key, as the app holds it."""
    client = Client()
    client.force_login(user)
    return client.session.session_key


def app_client(key: str, platform: str = "ios"):
    return Client(headers={"X-Grafikomat-Client": platform, "X-Grafikomat-Session": key})


def register(user, token=IOS_TOKEN, platform="ios") -> str:
    key = app_session(user)
    response = app_client(key, platform).post(
        "/api/me/push-devices", {"platform": platform, "token": token}, content_type="application/json"
    )
    assert response.status_code == 204, response.content
    return key


def push_jobs() -> list[list[str]]:
    return [j.args["notification_ids"] for j in ProcrastinateJob.objects.filter(task_name="notifications.send_push")]


class FakeSender:
    def __init__(self, outcome=push.Outcome.SENT):
        self.sent: list[tuple[str, push.Message]] = []
        self.outcome = outcome

    def send(self, device, message):
        self.sent.append((device.token, message))
        return self.outcome


@pytest.fixture
def senders():
    fakes = {"ios": FakeSender(), "android": FakeSender()}
    push._senders = fakes
    yield fakes
    push.reset_senders()


def run_push_jobs() -> int:
    sent = sum(push.deliver(ids) for ids in push_jobs())
    ProcrastinateJob.objects.filter(task_name="notifications.send_push").delete()
    return sent


# ----------------------------------------------------------------------------------------------- registering


def test_app_registers_the_phone_for_the_session(make_company):
    worker = make_company()["worker"]
    key = register(worker)

    device = PushDevice.objects.get()
    assert (device.user, device.platform, device.token, device.session_key) == (worker, "ios", IOS_TOKEN, key)


def test_registering_needs_a_login_and_a_real_token(make_company):
    assert Client().post(
        "/api/me/push-devices", {"platform": "ios", "token": IOS_TOKEN}, content_type="application/json"
    ).status_code in (401, 403)
    key = app_session(make_company()["worker"])
    bad = app_client(key).post(
        "/api/me/push-devices", {"platform": "ios", "token": "<script>"}, content_type="application/json"
    )
    assert bad.status_code == 422
    assert not PushDevice.objects.exists()


def test_a_phone_moves_to_whoever_logs_in_on_it(make_company):
    one, other = make_company("A")["worker"], make_company("B")["worker"]
    register(one)
    register(other)  # same phone, someone from another company logs in after
    assert list(PushDevice.objects.values_list("user", flat=True)) == [other.pk]


def test_logout_unpins_only_the_phone_of_that_session(make_company):
    worker = make_company()["worker"]
    key = register(worker, IOS_TOKEN, "ios")
    register(worker, ANDROID_TOKEN, "android")

    assert app_client(key).post("/api/auth/logout").status_code == 204

    assert list(PushDevice.objects.values_list("platform", flat=True)) == ["android"]


# ----------------------------------------------------------------------------------------------- queueing


def test_notify_queues_a_push_only_for_people_with_the_app(make_company):
    shop = make_company()
    notify(shop["company"].pk, [shop["worker"].pk], "bank_account_set", {"ending": "1234"})
    assert push_jobs() == []

    register(shop["worker"])
    notify(shop["company"].pk, [shop["worker"].pk, shop["manager"].pk], "bank_account_set", {"ending": "1234"})

    [ids] = push_jobs()
    assert set(ids) == {str(n.pk) for n in Notification.objects.filter(created_at__isnull=False)[:2]}
    assert len(ids) == 2  # one job for the whole batch; the worker finds who has a phone


def test_worker_sends_the_text_and_where_to_open(make_company, senders):
    shop = make_company()
    register(shop["worker"])
    register(shop["manager"], ANDROID_TOKEN, "android")
    payload = {"date": "2026-12-04", "start_time": "06:00", "end_time": "14:00", "position_name": "Sprzedawca"}
    notify(shop["company"].pk, [shop["worker"].pk], "claim_approved", payload)
    notify(shop["company"].pk, [shop["manager"].pk], "hours_reported", {**payload, "difference": 60})

    assert run_push_jobs() == 2

    [(token, message)] = senders["ios"].sent
    assert token == IOS_TOKEN and message.path == "/grafik?dzien=2026-12-04"
    assert message.body.startswith("Kierownik zatwierdził: bierzesz zmianę pt. 04.12, 06:00–14:00, Sprzedawca")
    assert message.company_id == str(shop["company"].pk)
    [(token, message)] = senders["android"].sent
    assert token == ANDROID_TOKEN and message.path == "/kierownik/godziny"


def test_nothing_goes_to_a_phone_whose_session_ended(make_company, senders):
    shop = make_company()
    key = register(shop["worker"])
    from django.contrib.sessions.models import Session

    Session.objects.filter(session_key=key).update(expire_date=timezone.now() - timedelta(minutes=1))
    notify(shop["company"].pk, [shop["worker"].pk], "bank_account_set", {"ending": "1234"})

    assert run_push_jobs() == 0
    assert senders["ios"].sent == [] and not PushDevice.objects.exists()


def test_seen_or_old_notifications_stay_in_the_app(make_company, senders, settings):
    shop = make_company()
    register(shop["worker"])
    notify(shop["company"].pk, [shop["worker"].pk], "bank_account_set", {"ending": "1"})
    notify(shop["company"].pk, [shop["worker"].pk], "bank_account_set", {"ending": "2"})
    first, second = Notification.objects.order_by("payload__ending")
    Notification.objects.filter(pk=first.pk).update(read_at=timezone.now())
    old = timezone.now() - timedelta(seconds=settings.PUSH_MAX_AGE_S + 60)
    Notification.objects.filter(pk=second.pk).update(created_at=old)

    assert run_push_jobs() == 0


def test_a_token_the_service_forgot_is_deleted(make_company, senders):
    shop = make_company()
    register(shop["worker"])
    senders["ios"].outcome = push.Outcome.GONE
    notify(shop["company"].pk, [shop["worker"].pk], "bank_account_set", {"ending": "1"})

    assert run_push_jobs() == 0
    assert not PushDevice.objects.exists()


def test_without_credentials_nothing_is_sent(make_company, settings):
    shop = make_company()
    register(shop["worker"])
    push.reset_senders()
    settings.PUSH_APNS_KEY_FILE = settings.PUSH_FCM_CREDENTIALS_FILE = ""
    notify(shop["company"].pk, [shop["worker"].pk], "bank_account_set", {"ending": "1"})

    assert run_push_jobs() == 0
    assert PushDevice.objects.exists()  # the phone stays registered for when push is set up


# ----------------------------------------------------------------------------------------------- what a tap opens


def test_each_kind_opens_its_shift_or_period(settings):
    today = timezone.localdate()
    future = (today + timedelta(days=40)).isoformat()
    assert push_path("availability_requested", {"start": future}) == f"/kiedy-moge?miesiac={future[:7]}"
    assert push_path("schedule_published", {"start": future}) == f"/grafik?dzien={future}"
    # A period that has started opens on today.
    assert push_path("schedule_published", {"start": "2020-01-01"}) == f"/grafik?dzien={today.isoformat()}"
    assert push_path("shift_offered", {"offer_id": "o1", "date": future}) == "/grafik?oferta=o1"
    assert push_path("offer_taken", {"date": future}) == f"/grafik?dzien={future}"
    assert push_path("shift_claimed", {"offer_id": "o1"}) == "/kierownik/oddane-zmiany?oferta=o1"
    assert push_path("offer_made", {}) == "/kierownik/oddane-zmiany"
    assert push_path("shift_emptied", {"location_id": "l1", "period_id": "p1"}) == "/kierownik/lokal/l1/grafik?okres=p1"
    assert push_path("request_for_manager", {"location_id": "l1"}) == "/kierownik/lokal/l1/dyspozycje"
    assert push_path("hours_reported", {}) == "/kierownik/godziny"
    assert push_path("something_new", {}) == "/"
    # Ids never break out of the path.
    assert push_path("shift_claimed", {"offer_id": "../x?y"}) == "/kierownik/oddane-zmiany?oferta=..%2Fx%3Fy"


def test_from_giving_a_shift_away_to_the_managers_approval(api, market, senders):
    """The scenario of the apps: the giver, the volunteer and the manager each have a phone."""
    m = market
    giver, taker, manager = user_of(m["giver"]), user_of(m["elsewhere"]), m["manager"]
    register(giver, "giver" + "0" * 60)
    register(taker, "taker:" + "1" * 60, "android")
    register(manager, "manager" + "2" * 60)

    offer_id = offer(api, m).json()["id"]
    run_push_jobs()
    # The volunteer's phone opens the offer in "Mój grafik"; the manager's the list of given-away shifts.
    [(_, to_taker)] = senders["android"].sent
    assert to_taker.path == f"/grafik?oferta={offer_id}" and "oddaje zmianę" in to_taker.body
    assert [msg.path for token, msg in senders["ios"].sent if token.startswith("manager")] == [
        f"/kierownik/oddane-zmiany?oferta={offer_id}"
    ]

    api.login(taker)
    assert api.post(f"/api/offers/{offer_id}/claim").status_code == 201
    senders["ios"].sent.clear()
    run_push_jobs()
    paths = {token[:5]: msg.path for token, msg in senders["ios"].sent}
    assert paths == {
        "manag": f"/kierownik/oddane-zmiany?oferta={offer_id}",
        "giver": f"/grafik?dzien={m['row'].shift.date}",
    }

    api.login(manager)
    claim = api.get(f"/api/manager/offers?company_id={m['company'].id}").json()["offers"][0]["claims"][0]["id"]
    assert api.post(f"/api/claims/{claim}/approve").status_code == 200
    senders["ios"].sent.clear()
    senders["android"].sent.clear()
    run_push_jobs()
    [(_, approved)] = senders["android"].sent
    assert approved.path == f"/grafik?dzien={m['row'].shift.date}" and approved.body.startswith("Kierownik zatwierdził")
    [(token, taken)] = senders["ios"].sent
    assert token.startswith("giver") and "bierze" in taken.body


# ----------------------------------------------------------------------------------------------- the services


def test_apns_request_and_answers():
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    seen = []

    def answer(request):
        seen.append(request)
        phone = request.url.path.rsplit("/", 1)[-1]
        if phone == "gone":
            return httpx2.Response(410, json={"reason": "Unregistered"})
        if phone == "dev" and request.url.host == "api.push.apple.com":
            return httpx2.Response(400, json={"reason": "BadDeviceToken"})
        return httpx2.Response(200)

    sender = push.ApnsSender(
        key=pem.decode(),
        key_id="KEY123",
        team_id="TEAM456",
        topic="pl.grafikomat.app",
        client=httpx2.Client(transport=httpx2.MockTransport(answer)),
    )
    message = push.Message(notification_id="n1", company_id="c1", body="Jest nowy grafik.", path="/grafik")
    user = User.objects.create_user("+48601900300")

    assert sender.send(PushDevice(user=user, platform="ios", token="ok"), message) is push.Outcome.SENT
    request = seen[-1]
    assert request.url.host == "api.push.apple.com" and request.headers["apns-topic"] == "pl.grafikomat.app"
    claims = jwt.decode(request.headers["authorization"].split()[1], key.public_key(), algorithms=["ES256"])
    assert claims["iss"] == "TEAM456"
    assert jwt.get_unverified_header(request.headers["authorization"].split()[1])["kid"] == "KEY123"
    body = json.loads(request.content)
    assert body["aps"]["alert"] == {"title": "Grafikomat", "body": "Jest nowy grafik."} and body["path"] == "/grafik"

    assert sender.send(PushDevice(user=user, platform="ios", token="gone"), message) is push.Outcome.GONE
    # A token of an Xcode build is retried at the sandbox and remembered.
    dev = PushDevice.objects.create(user=user, platform="ios", token="dev", session_key="s")
    assert sender.send(dev, message) is push.Outcome.SENT
    assert seen[-1].url.host == "api.sandbox.push.apple.com"
    dev.refresh_from_db()
    assert dev.sandbox is True


def test_fcm_request_and_answers():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    credentials = {
        "project_id": "grafikomat-test",
        "client_email": "push@grafikomat-test.iam.gserviceaccount.com",
        "private_key": pem.decode(),
        "private_key_id": "k1",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    seen = []

    def answer(request):
        seen.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx2.Response(200, json={"access_token": "ya29.test", "expires_in": 3600})
        phone = json.loads(request.content)["message"]["token"]
        if phone == "gone":
            error = {"code": 404, "details": [{"errorCode": "UNREGISTERED"}], "message": "Requested entity not found."}
            return httpx2.Response(404, json={"error": error})
        return httpx2.Response(200, json={"name": "projects/grafikomat-test/messages/1"})

    sender = push.FcmSender(credentials, client=httpx2.Client(transport=httpx2.MockTransport(answer)))
    message = push.Message(notification_id="n1", company_id="c1", body="Ola oddaje zmianę.", path="/grafik?oferta=o1")
    user = User.objects.create_user("+48601900301")

    assert sender.send(PushDevice(user=user, platform="android", token="t1"), message) is push.Outcome.SENT
    grant, sent = seen
    assertion = dict(x.split("=") for x in grant.content.decode().split("&"))["assertion"]
    claims = jwt.decode(assertion, key.public_key(), algorithms=["RS256"], audience=credentials["token_uri"])
    assert claims["scope"] == "https://www.googleapis.com/auth/firebase.messaging"
    assert sent.url.path == "/v1/projects/grafikomat-test/messages:send"
    assert sent.headers["authorization"] == "Bearer ya29.test"
    body = json.loads(sent.content)["message"]
    assert body["data"] == {"path": "/grafik?oferta=o1", "company_id": "c1", "notification_id": "n1"}
    assert body["android"]["notification"]["channel_id"] == "grafik"

    assert sender.send(PushDevice(user=user, platform="android", token="gone"), message) is push.Outcome.GONE
    assert len([r for r in seen if r.url.host == "oauth2.googleapis.com"]) == 1  # the access token is reused
