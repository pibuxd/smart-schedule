"""The store test (Piotr, 28.11.2026): the szybkisms.pl gateway, new numbers joining the test location, and the
store reviewers' login with a fixed code."""

import json
import re
from datetime import timedelta
from io import StringIO

import httpx2
import pytest
from django.core.management import CommandError, call_command
from django.test import Client
from django.utils import timezone

from apps.accounts import checks, sms
from apps.accounts.models import LoginCode, User
from apps.billing.models import Subscription
from apps.rules.models import RuleSetting
from apps.staffing.models import EmployeeProfile
from apps.tenancy import testers
from apps.tenancy.models import Invitation, InvitationStatus, Location, Membership, Role

pytestmark = pytest.mark.django_db

FULL = "Miejsca dla testerów są już zajęte"
TOKEN = "token-123"  # noqa: S105 - a made-up token for the fake gateway


def code_from(outbox) -> str:
    return re.search(r"\b(\d{6})\b", outbox[-1][1]).group(1)


def request_code(api, phone, purpose="login"):
    return api.post("/api/auth/request-code", {"phone": phone, "purpose": purpose})


def verify(api, phone, code):
    return api.post("/api/auth/verify-code", {"phone": phone, "code": code})


def log_in(api, phone, outbox):
    """Ask for a code and log in with it; a fresh client per person, like separate phones."""
    response = request_code(api, phone)
    assert response.status_code == 200, response.json()
    response = verify(api, phone, code_from(outbox))
    assert response.status_code == 200, response.json()
    return response.json()


@pytest.fixture
def client_factory():
    """A separate client per person, like separate phones."""

    class Api:
        def __init__(self):
            self.client = Client()

        def post(self, path, data):
            return self.client.post(path, data, content_type="application/json")

    return Api


@pytest.fixture
def closed_test(settings):
    """The closed test on, with an empty location from the command's own code (3 + 15 places by default)."""
    settings.TESTERS_LOCATION_ID = ""
    setup = testers.set_up("Kawiarnia Testowa")
    settings.TESTERS_LOCATION_ID = str(setup.location.pk)
    return setup.location


def role_in(location, phone) -> str | None:
    user = User.objects.get(phone_e164=phone)
    membership = Membership.objects.filter(user=user, company_id=location.company_id).first()
    if membership is None:
        return None
    if membership.role == Role.MANAGER:
        assert membership.locations.filter(pk=location.pk).exists()
        return "manager"
    assert EmployeeProfile.objects.get(membership=membership).works_in(location)
    return "employee"


# --- szybkisms.pl ----------------------------------------------------------------------------------------------------


def gateway(answer):
    """A SzybkiSmsSender whose requests go to `answer(request)`; the requests are kept in `.seen`."""
    seen = []

    def handler(request):
        seen.append(request)
        return answer(request)

    sender = sms.SzybkiSmsSender(client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    sender.seen = seen
    return sender


def queued(request):
    body = json.loads(request.content)
    return httpx2.Response(
        200,
        json=[{"id": 1, "recipient": body["recipients"], "status_code": "QUEUED", "price": 0.16}],
        headers={"X-Success-Count": "1", "X-Error-Count": "0"},
    )


def test_gateway_sends_the_code_with_the_token(settings):
    settings.SZYBKISMS_TOKEN = TOKEN
    settings.SZYBKISMS_SENDER = "Grafikomat"
    settings.SZYBKISMS_SANDBOX = False
    sender = gateway(queued)

    sender.send("+48601700800", "Grafikomat: kod logowania 123456. Ważny 5 minut.")

    (request,) = sender.seen
    assert str(request.url) == "https://api.szybkisms.pl/rest/messages/sms"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert json.loads(request.content) == {
        "recipients": "+48601700800",
        "message": "Grafikomat: kod logowania 123456. Ważny 5 minut.",
        # Without Polish marks the code fits in one SMS.
        "unicode": False,
        "sender": "Grafikomat",
    }


def test_gateway_sandbox_and_default_sender(settings):
    settings.SZYBKISMS_TOKEN = TOKEN
    settings.SZYBKISMS_SENDER = ""
    settings.SZYBKISMS_SANDBOX = True
    sender = gateway(queued)

    sender.send("+48601700800", "kod 123456")

    (request,) = sender.seen
    assert str(request.url) == "https://api.szybkisms.pl/rest-sandbox/messages/sms"
    assert "sender" not in json.loads(request.content)


def test_rejected_message_is_an_error_without_the_code(settings):
    settings.SZYBKISMS_TOKEN = TOKEN
    sender = gateway(
        lambda request: httpx2.Response(
            200, json=[{"id": None, "status_code": "REJECTED", "status_description": "Rejected (Invalid number)"}]
        )
    )

    with pytest.raises(sms.SmsNotSent) as error:
        sender.send("+48601700800", "kod 654321")
    assert "Invalid number" in str(error.value)
    assert "654321" not in str(error.value)


def test_refused_request_is_an_error_with_the_gateways_words(settings):
    settings.SZYBKISMS_TOKEN = TOKEN
    sender = gateway(
        lambda request: httpx2.Response(
            401,
            json={
                "type": "https://api.szybkisms.pl/problems/unauthorized/",
                "title": "Unauthorized",
                "detail": "Authorization token is missing or invalid.",
                "code": "401-1",
            },
        )
    )

    with pytest.raises(sms.SmsNotSent) as error:
        sender.send("+48601700800", "kod 654321")
    assert "401" in str(error.value) and "token is missing or invalid" in str(error.value)


def test_no_token_sends_nothing(settings):
    settings.SZYBKISMS_TOKEN = ""
    sender = gateway(queued)

    with pytest.raises(sms.SmsNotSent):
        sender.send("+48601700800", "kod 654321")
    assert sender.seen == []


def test_login_through_the_gateway_and_a_failed_send(api, settings, monkeypatch):
    """The login code goes through the gateway; when the gateway refuses, the person hears so and keeps the limit."""
    settings.SMS_BACKEND = checks.SZYBKISMS
    settings.SZYBKISMS_TOKEN = TOKEN
    phone = "+48601700800"
    User.objects.create_user(phone)
    answers = [queued]
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return answers[0](request)

    real_client = httpx2.Client
    monkeypatch.setattr(sms.httpx2, "Client", lambda **kw: real_client(transport=httpx2.MockTransport(handler)))

    assert request_code(api, phone).status_code == 200
    code = re.search(r"\b(\d{6})\b", sent[-1]["message"]).group(1)
    assert verify(api, phone, code).status_code == 200

    answers[0] = lambda request: httpx2.Response(500, json={"title": "Internal Server Error"})
    LoginCode.objects.update(created_at=timezone.now() - timedelta(minutes=2))
    response = request_code(api, phone)
    assert response.status_code == 503
    assert "Nie udało się wysłać SMS-a" in response.json()["detail"]
    # The failed code was not saved, so it does not count toward the five codes an hour.
    assert LoginCode.objects.filter(phone_e164=phone).count() == 1


def test_check_warns_about_the_gateway_without_a_token(settings):
    settings.SMS_BACKEND = checks.SZYBKISMS
    settings.SZYBKISMS_TOKEN = ""
    assert [w.id for w in checks.sms_gateway_has_a_token(None)] == ["accounts.W002"]
    settings.SZYBKISMS_TOKEN = TOKEN
    assert checks.sms_gateway_has_a_token(None) == []


# --- new numbers join the test location ------------------------------------------------------------------------------


def test_without_the_test_a_new_number_is_unknown(api, sms_outbox, settings):
    settings.TESTERS_LOCATION_ID = ""

    response = request_code(api, "+48601700800")

    assert response.status_code == 404
    assert "Nie znamy tego numeru" in response.json()["detail"]
    assert sms_outbox == []


def test_a_new_number_joins_the_test_location(api, sms_outbox, closed_test):
    me = log_in(api, "601 700 800", sms_outbox)

    assert [c["name"] for c in me["companies"]] == ["Kawiarnia Testowa"]
    assert me["pending_invitations"] == 0
    assert role_in(closed_test, "+48601700800") in {"manager", "employee"}
    invitation = Invitation.objects.get(phone_e164="+48601700800")
    assert invitation.status == InvitationStatus.ACCEPTED
    assert invitation.invited_by is None


def test_places_fill_as_set_and_then_the_test_is_full(client_factory, sms_outbox, settings, closed_test):
    settings.TESTERS_MANAGERS = 1
    settings.TESTERS_EMPLOYEES = 2
    phones = ["+48601700801", "+48601700802", "+48601700803"]

    for phone in phones:
        log_in(client_factory(), phone, sms_outbox)

    assert sorted(role_in(closed_test, phone) for phone in phones) == ["employee", "employee", "manager"]
    response = request_code(client_factory(), "+48601700804")
    assert response.status_code == 404
    assert FULL in response.json()["detail"]
    assert not User.objects.filter(phone_e164="+48601700804").exists()


def test_the_role_is_drawn_in_proportion_to_free_places(closed_test, settings, monkeypatch):
    settings.TESTERS_MANAGERS = 1
    settings.TESTERS_EMPLOYEES = 2
    drawn = []
    monkeypatch.setattr(testers.secrets, "randbelow", lambda n: drawn.append(n) or pick)

    pick = 0
    assert testers.draw_role(closed_test) == Role.MANAGER
    pick = 1
    assert testers.draw_role(closed_test) == Role.EMPLOYEE
    pick = 2
    assert testers.draw_role(closed_test) == Role.EMPLOYEE
    assert drawn == [3, 3, 3]


def test_people_already_in_the_location_take_places(closed_test, settings, make_company):
    """Places count the people now in the location: someone a tester-manager invited takes an employee's place."""
    settings.TESTERS_MANAGERS = 1
    settings.TESTERS_EMPLOYEES = 1
    worker = User.objects.create_user("+48601700810")
    membership = Membership.objects.create(company=closed_test.company, user=worker)
    profile = EmployeeProfile.objects.create(membership=membership, home_location=closed_test)

    places = testers.places(closed_test)
    assert (places.free_managers, places.free_employees) == (1, 0)
    assert testers.draw_role(closed_test) == Role.MANAGER

    # Removing the person frees the place.
    EmployeeProfile.objects.filter(pk=profile.pk).update(removed_at=timezone.now(), is_active=False)
    assert testers.places(closed_test).free_employees == 1


def test_the_test_filling_up_before_login_creates_no_account(client_factory, sms_outbox, settings, closed_test):
    settings.TESTERS_MANAGERS = 0
    settings.TESTERS_EMPLOYEES = 1
    late = client_factory()
    assert request_code(late, "+48601700821").status_code == 200
    late_code = code_from(sms_outbox)
    log_in(client_factory(), "+48601700822", sms_outbox)

    response = verify(late, "+48601700821", late_code)

    assert response.status_code == 400
    assert FULL in response.json()["detail"]
    assert not User.objects.filter(phone_e164="+48601700821").exists()


def test_registering_a_company_does_not_join_the_test(api, sms_outbox, closed_test):
    assert request_code(api, "+48601700830", purpose="register").status_code == 200
    me = verify(api, "+48601700830", code_from(sms_outbox)).json()

    assert me["companies"] == []
    assert role_in(closed_test, "+48601700830") is None


def test_invited_number_keeps_its_invitation(api, sms_outbox, closed_test, make_company):
    other = make_company()
    Invitation.objects.create(location=other["location"], phone_e164="+48601700831", invited_by=other["manager"])

    me = log_in(api, "+48601700831", sms_outbox)

    assert me["pending_invitations"] == 1
    assert role_in(closed_test, "+48601700831") is None


def test_existing_account_does_not_join(api, sms_outbox, closed_test):
    User.objects.create_user("+48601700832")

    me = log_in(api, "+48601700832", sms_outbox)

    assert me["companies"] == []


def test_foreign_new_number_gets_no_code(api, sms_outbox, closed_test):
    response = request_code(api, "+380501234567")

    assert response.status_code == 404
    assert "Nie znamy tego numeru" in response.json()["detail"]
    assert sms_outbox == []


@pytest.mark.parametrize("value", ["not-a-uuid", "6a1e0000-0000-4000-8000-00000000ffff", "archived"])
def test_a_wrong_or_archived_location_turns_the_test_off(api, sms_outbox, settings, closed_test, value):
    if value == "archived":
        Location.objects.filter(pk=closed_test.pk).update(archived_at=timezone.now())
    else:
        settings.TESTERS_LOCATION_ID = value

    response = request_code(api, "+48601700840")

    assert response.status_code == 404
    assert "Nie znamy tego numeru" in response.json()["detail"]


def test_check_reminds_that_the_test_is_on(settings):
    settings.TESTERS_LOCATION_ID = ""
    assert checks.closed_test_is_on(None) == []
    settings.TESTERS_LOCATION_ID = "6a1e0000-0000-4000-8000-000000000001"
    assert [w.id for w in checks.closed_test_is_on(None)] == ["accounts.W003"]


# --- the store reviewers' login --------------------------------------------------------------------------------------


@pytest.fixture
def reviewer(settings):
    settings.REVIEW_LOGIN_PHONE = "500 900 100"
    settings.REVIEW_LOGIN_CODE = "246810"
    return "+48500900100"


def test_reviewer_logs_in_with_the_fixed_code_and_gets_no_sms(api, sms_outbox, reviewer, closed_test):
    assert request_code(api, reviewer).status_code == 200
    assert sms_outbox == []

    me = verify(api, reviewer, "246810").json()

    assert me["first_name"] == "Recenzent"
    assert [c["role"] for c in me["companies"]] == ["manager"]


def test_reviewers_code_follows_the_usual_rules(api, sms_outbox, reviewer, closed_test):
    assert request_code(api, reviewer).status_code == 200

    wrong = verify(api, reviewer, "111111")
    assert wrong.status_code == 400
    assert "Pozostało prób: 4" in wrong.json()["detail"]
    assert verify(api, reviewer, "246810").status_code == 200
    # Used once, like any code.
    assert verify(api, reviewer, "246810").status_code == 400


def test_reviewer_takes_no_testers_place(reviewer, closed_test, settings):
    settings.TESTERS_MANAGERS = 1

    places = testers.places(closed_test)

    assert role_in(closed_test, reviewer) == "manager"
    assert (places.managers, places.free_managers) == (0, 1)


def test_half_set_review_login_is_off_and_warned(api, sms_outbox, settings):
    settings.REVIEW_LOGIN_PHONE = "500 900 100"
    settings.REVIEW_LOGIN_CODE = "12345"  # 5 digits
    User.objects.create_user("+48500900100")

    assert request_code(api, "+48500900100").status_code == 200
    assert sms_outbox[-1][0] == "+48500900100"
    assert [w.id for w in checks.review_login_is_complete(None)] == ["accounts.W004"]
    settings.REVIEW_LOGIN_CODE = "123456"
    assert checks.review_login_is_complete(None) == []
    settings.REVIEW_LOGIN_PHONE = settings.REVIEW_LOGIN_CODE = ""
    assert checks.review_login_is_complete(None) == []


# --- the command -----------------------------------------------------------------------------------------------------


def run(*args) -> str:
    out = StringIO()
    call_command("tester_location", *args, stdout=out)
    return out.getvalue()


def test_command_makes_an_empty_location_once(settings):
    settings.TESTERS_LOCATION_ID = ""
    settings.REVIEW_LOGIN_PHONE = settings.REVIEW_LOGIN_CODE = ""

    out = run("--name", "Kawiarnia Testowa")

    location = Location.objects.get(name="Kawiarnia Testowa")
    assert location.company.name == "Kawiarnia Testowa"
    assert f"TESTERS_LOCATION_ID={location.pk}" in out
    assert "Kierownicy: 0 z 3, pracownicy: 0 z 15." in out
    assert not EmployeeProfile.objects.filter(home_location=location).exists()
    assert not location.positions.exists()
    assert RuleSetting.objects.filter(location=location).exists()
    ends_at = Subscription.objects.get(company=location.company).ends_at
    assert timedelta(days=89) < ends_at - timezone.now() <= timedelta(days=90)

    # Run again before the setting is in .env: the same location.
    run("--name", "Kawiarnia Testowa", "--days", "120")
    assert Location.objects.filter(name="Kawiarnia Testowa").count() == 1
    assert Subscription.objects.get(company=location.company).ends_at - timezone.now() > timedelta(days=119)


def test_command_shows_places_and_adds_the_reviewer(settings, reviewer, closed_test, client_factory, sms_outbox):
    log_in(client_factory(), "+48601700850", sms_outbox)

    out = run()

    assert "Lokal testerów: „Kawiarnia Testowa”." in out
    assert re.search(r"Kierownicy: \d z 3, pracownicy: \d z 15\.", out)
    assert "TESTERS_LOCATION_ID=" not in out
    assert "Konto recenzenta (kierownik tego lokalu): +48500900100, kod 246810." in out
    assert role_in(closed_test, reviewer) == "manager"


def test_command_needs_a_name_when_the_test_is_off(settings):
    settings.TESTERS_LOCATION_ID = ""
    with pytest.raises(CommandError):
        run()
    with pytest.raises(CommandError):
        run("--name", "X", "--days", "0")
