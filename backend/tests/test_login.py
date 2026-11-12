"""Login with an SMS code: who gets a code, limits, wrong and expired codes, sessions."""

import re
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.login import hash_login_code
from apps.accounts.models import LoginCode, User
from apps.accounts.tasks import delete_old_login_codes
from apps.tenancy.models import Invitation

pytestmark = pytest.mark.django_db

PHONE = "+48601700800"


def code_from(outbox) -> str:
    text = outbox[-1][1]
    return re.search(r"\b(\d{6})\b", text).group(1)


def request_code(api, phone=PHONE, purpose="login", **extra):
    return api.post("/api/auth/request-code", {"phone": phone, "purpose": purpose}, **extra)


def verify(api, code, phone=PHONE):
    return api.post("/api/auth/verify-code", {"phone": phone, "code": code})


def age_codes(seconds: int) -> None:
    """Move every login code into the past, as if `seconds` had passed."""
    for code in LoginCode.objects.all():
        delta = timedelta(seconds=seconds)
        LoginCode.objects.filter(pk=code.pk).update(
            created_at=code.created_at - delta, expires_at=code.expires_at - delta
        )


# --- who may get a code -------------------------------------------------------------------------------


def test_unknown_number_gets_no_code_on_login(api, sms_outbox):
    response = request_code(api)

    assert response.status_code == 404
    assert "Nie znamy tego numeru" in response.json()["detail"]
    assert sms_outbox == []


def test_existing_account_logs_in_with_the_code_from_sms(api, sms_outbox):
    user = User.objects.create_user(PHONE, first_name="Halina")

    response = request_code(api, "601 700 800")
    assert response.status_code == 200
    assert response.json() == {"phone": PHONE, "expires_in_s": 300, "resend_after_s": 60}
    assert sms_outbox[-1][0] == PHONE

    response = verify(api, code_from(sms_outbox), phone="601-700-800")
    assert response.status_code == 200
    assert response.json()["id"] == str(user.id)
    assert response.json()["first_name"] == "Halina"
    assert api.get("/api/me").json()["phone"] == PHONE


def test_number_with_pending_invitation_gets_a_code_and_an_account(api, sms_outbox, make_company):
    a = make_company()
    Invitation.objects.create(location=a["location"], phone_e164=PHONE, invited_by=a["manager"])

    assert request_code(api).status_code == 200
    response = verify(api, code_from(sms_outbox))

    assert response.status_code == 200
    assert response.json()["pending_invitations"] == 1
    assert response.json()["companies"] == []
    user = User.objects.get(phone_e164=PHONE)
    assert not user.has_usable_password()


def test_declined_invitation_alone_does_not_allow_a_code(api, sms_outbox, make_company):
    a = make_company()
    Invitation.objects.create(
        location=a["location"], phone_e164=PHONE, invited_by=a["manager"], status="declined", decided_at=timezone.now()
    )

    assert request_code(api).status_code == 404
    assert sms_outbox == []


def test_new_manager_registers_with_any_polish_number(api, sms_outbox):
    assert request_code(api, purpose="register").status_code == 200
    assert verify(api, code_from(sms_outbox)).status_code == 200
    assert User.objects.filter(phone_e164=PHONE).exists()


def test_disabled_account_gets_no_code(api, sms_outbox):
    User.objects.create_user(PHONE, is_active=False)

    assert request_code(api).status_code == 404
    assert request_code(api, purpose="register").status_code == 404
    assert sms_outbox == []


@pytest.mark.parametrize("phone", ["abc", "12345", "+49 30 901820", "+1 202 555 0123", ""])
def test_only_valid_polish_numbers_are_accepted(api, sms_outbox, phone):
    response = request_code(api, phone, purpose="register")

    assert response.status_code == 400
    assert sms_outbox == []


# --- the code itself ----------------------------------------------------------------------------------


def test_code_is_stored_only_as_a_hash(api, sms_outbox):
    request_code(api, purpose="register")
    code = code_from(sms_outbox)
    stored = LoginCode.objects.get()

    assert code not in stored.code_hash
    assert stored.code_hash == hash_login_code(PHONE, code)
    assert stored.expires_at - stored.created_at == timedelta(minutes=5)


def test_wrong_code_is_refused_and_counted(api, sms_outbox):
    request_code(api, purpose="register")
    wrong = "000000" if code_from(sms_outbox) != "000000" else "111111"

    response = verify(api, wrong)

    assert response.status_code == 400
    assert "Pozostało prób: 4" in response.json()["detail"]
    assert LoginCode.objects.get().attempts == 1
    assert api.get("/api/me").status_code == 401


def test_after_five_wrong_tries_even_the_right_code_is_refused(api, sms_outbox):
    request_code(api, purpose="register")
    code = code_from(sms_outbox)
    wrong = "000000" if code != "000000" else "111111"

    statuses = [verify(api, wrong).status_code for _ in range(5)]
    assert statuses == [400, 400, 400, 400, 400]
    assert LoginCode.objects.get().attempts == 5

    response = verify(api, code)
    assert response.status_code == 429
    assert "Poproś o nowy kod" in response.json()["detail"]
    assert not User.objects.filter(phone_e164=PHONE).exists()


def test_code_expires_after_five_minutes(api, sms_outbox):
    request_code(api, purpose="register")
    code = code_from(sms_outbox)

    age_codes(299)
    assert LoginCode.objects.filter(expires_at__gt=timezone.now()).exists()
    age_codes(2)

    response = verify(api, code)
    assert response.status_code == 400
    assert response.json()["detail"] == "Kod wygasł. Poproś o nowy."


def test_code_works_only_once(api, sms_outbox):
    request_code(api, purpose="register")
    code = code_from(sms_outbox)
    assert verify(api, code).status_code == 200
    api.logout()

    assert verify(api, code).status_code == 400


def test_a_new_code_replaces_the_previous_one(api, sms_outbox):
    request_code(api, purpose="register")
    first = code_from(sms_outbox)
    age_codes(61)
    request_code(api, purpose="register")
    second = code_from(sms_outbox)

    if first != second:
        assert verify(api, first).status_code == 400
    assert verify(api, second).status_code == 200


def test_code_of_another_number_does_not_work(api, sms_outbox):
    User.objects.create_user("+48601700801")
    request_code(api, purpose="register")
    code = code_from(sms_outbox)

    assert verify(api, code, phone="+48601700801").status_code == 400


def test_spaces_in_the_typed_code_are_ignored(api, sms_outbox):
    request_code(api, purpose="register")
    code = code_from(sms_outbox)

    assert verify(api, f" {code[:3]} {code[3:]} ").status_code == 200


# --- limits -------------------------------------------------------------------------------------------


def test_next_code_only_after_a_minute(api, sms_outbox):
    assert request_code(api, purpose="register").status_code == 200

    response = request_code(api, purpose="register")
    assert response.status_code == 429
    assert "Kolejny możesz dostać za" in response.json()["detail"]
    assert len(sms_outbox) == 1

    age_codes(60)
    assert request_code(api, purpose="register").status_code == 200
    assert len(sms_outbox) == 2


def test_five_codes_per_number_per_hour(api, sms_outbox, settings):
    settings.LOGIN_CODE_RESEND_AFTER_S = 0

    statuses = [request_code(api, purpose="register").status_code for _ in range(6)]
    assert statuses == [200, 200, 200, 200, 200, 429]
    assert len(sms_outbox) == 5

    # Another number is not affected, and after an hour the first one works again.
    assert request_code(api, "+48601700801", purpose="register").status_code == 200
    age_codes(3601)
    assert request_code(api, purpose="register").status_code == 200


def test_limit_per_ip_address_counts_also_refused_numbers(api, sms_outbox, settings):
    settings.LOGIN_CODES_PER_IP_PER_HOUR = 3

    assert request_code(api, "+48601700801", purpose="register").status_code == 200
    assert request_code(api, "+48601700802").status_code == 404
    assert request_code(api, "+48601700803").status_code == 404
    # The fourth request from this address is refused before we say whether the number is known.
    assert request_code(api, "+48601700804").status_code == 429
    assert request_code(api, "+48601700805", purpose="register").status_code == 429
    assert len(sms_outbox) == 1

    assert request_code(api, "+48601700805", purpose="register", REMOTE_ADDR="10.0.0.9").status_code == 200


def test_client_address_comes_from_the_trusted_proxy(api, settings):
    settings.NUM_PROXIES = 1

    # The client can prepend anything; the entry added by Caddy is the last one.
    request_code(api, purpose="register", HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.7")
    assert LoginCode.objects.get().ip == "203.0.113.7"


def test_forwarded_header_is_ignored_without_a_trusted_proxy(api):
    request_code(api, purpose="register", HTTP_X_FORWARDED_FOR="203.0.113.7")
    assert LoginCode.objects.get().ip == "127.0.0.1"


def test_failed_sms_delivery_does_not_use_up_the_limit(api, settings):
    settings.SMS_BACKEND = "tests.test_login.BrokenSender"

    assert request_code(api, purpose="register").status_code == 503
    assert LoginCode.objects.count() == 0


class BrokenSender:
    def send(self, phone_e164, text):
        raise ConnectionError("gateway down")


# --- sessions -----------------------------------------------------------------------------------------


def test_me_requires_login_and_sets_the_csrf_cookie(api):
    response = api.get("/api/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Zaloguj się."}
    assert "csrftoken" in response.cookies


def test_session_lasts_about_sixty_days(api, sms_outbox):
    request_code(api, purpose="register")
    response = verify(api, code_from(sms_outbox))

    assert response.cookies["sessionid"]["max-age"] == 60 * 24 * 60 * 60
    assert response.cookies["sessionid"]["httponly"]


def test_logout_ends_the_session(api):
    api.login(User.objects.create_user(PHONE))
    assert api.get("/api/me").status_code == 200

    assert api.post("/api/auth/logout").status_code == 204
    assert api.get("/api/me").status_code == 401


def test_login_endpoints_check_csrf():
    client = Client(enforce_csrf_checks=True)
    body = {"phone": PHONE, "purpose": "register"}

    assert client.post("/api/auth/request-code", body, content_type="application/json").status_code == 403

    token = client.get("/api/me").cookies["csrftoken"].value
    response = client.post("/api/auth/request-code", body, content_type="application/json", HTTP_X_CSRFTOKEN=token)
    assert response.status_code == 200


def test_logged_in_person_can_set_their_name(api):
    user = User.objects.create_user(PHONE)
    api.login(user)

    response = api.patch("/api/me", {"first_name": " Zofia ", "last_name": "Wójcik"})

    assert response.status_code == 200
    assert response.json()["first_name"] == "Zofia"
    user.refresh_from_db()
    assert user.full_name == "Zofia Wójcik"
    assert api.patch("/api/me", {"first_name": "", "last_name": "Wójcik"}).status_code == 422
    assert api.patch("/api/me", {"first_name": "  ", "last_name": "Wójcik"}).status_code == 400


def test_changing_the_phone_number_logs_the_account_out(api):
    """Stage 2 review note: the superadmin changes a number; old devices must not stay logged in."""
    user = User.objects.create_user(PHONE)
    api.login(user)
    assert api.get("/api/me").status_code == 200

    user.phone_e164 = "+48601700899"
    user.save()

    assert api.get("/api/me").status_code == 401


def test_endpoints_need_a_session_by_default(api):
    assert api.get("/api/me/invitations").status_code == 401
    assert api.post("/api/companies", {"name": "Firma"}).status_code == 401
    assert api.get("/api/health").status_code == 200


def test_old_login_codes_are_deleted(api, sms_outbox):
    request_code(api, purpose="register")
    request_code(api, "+48601700801", purpose="register")
    LoginCode.objects.filter(phone_e164=PHONE).update(
        created_at=timezone.now() - timedelta(days=2), expires_at=timezone.now() - timedelta(days=1)
    )

    assert delete_old_login_codes(0) == 1
    assert list(LoginCode.objects.values_list("phone_e164", flat=True)) == ["+48601700801"]


def test_system_check_warns_when_codes_go_to_the_log_outside_development(settings):
    from apps.accounts.checks import login_codes_must_not_go_to_the_log_in_production as check

    settings.SMS_BACKEND = "apps.accounts.sms.ConsoleSmsSender"
    settings.DEBUG = False
    assert [warning.id for warning in check(None)] == ["accounts.W001"]

    settings.DEBUG = True
    assert check(None) == []
