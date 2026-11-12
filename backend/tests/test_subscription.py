"""Free-access codes, extending access, read-only state and the banner before the end."""

import re
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.billing.codes import ALPHABET, format_code, generate_code, hash_code, normalize_code
from apps.billing.models import AccessCode, CodeAttempt, CodeRedemption, GenerationUsage, Subscription
from apps.tenancy.models import Company, Invitation, Membership, Role

pytestmark = pytest.mark.django_db

DAY = timedelta(days=1)


def make_code(days=30, **fields) -> str:
    code = generate_code()
    AccessCode.objects.create(code_hash=hash_code(code), prefix=code[:4], days=days, **fields)
    return code


def redeem(api, company, code):
    return api.post(f"/api/companies/{company.id}/subscription/redeem", {"code": code})


def close_to(moment, expected) -> bool:
    return abs(moment - expected) < timedelta(seconds=30)


# --- the code -----------------------------------------------------------------------------------------


def test_codes_are_long_random_and_without_confusing_characters():
    codes = {generate_code() for _ in range(200)}

    assert len(codes) == 200
    assert all(len(code) >= 10 for code in codes)
    assert not set("".join(codes)) & set("0O1IL")
    assert set("".join(codes)) <= set(ALPHABET)


def test_case_spaces_and_dashes_do_not_matter():
    code = generate_code()
    typed = f"  {format_code(code).lower().replace('-', ' - ')} "

    assert normalize_code(typed) == code
    assert hash_code(typed) == hash_code(code)


# --- redeeming ----------------------------------------------------------------------------------------


def test_first_code_starts_access_from_today(api, make_company):
    a = make_company()
    api.login(a["manager"])
    code = make_code(days=30)

    response = redeem(api, a["company"], format_code(code).lower())

    assert response.status_code == 200
    body = response.json()
    assert body["is_active"] and not body["read_only"]
    assert body["days_left"] == 30
    subscription = Subscription.objects.get(company=a["company"])
    assert close_to(subscription.ends_at, timezone.now() + 30 * DAY)
    assert subscription.source == "code"
    redemption = CodeRedemption.objects.get()
    assert (redemption.company, redemption.user, redemption.days_added) == (a["company"], a["manager"], 30)
    assert AccessCode.objects.get().uses == 1


def test_next_code_extends_from_the_end_date_not_from_today(api, make_company, subscribe):
    a = make_company()
    ends_at = subscribe(a["company"], days=10).ends_at
    api.login(a["manager"])

    assert redeem(api, a["company"], make_code(days=60)).status_code == 200

    assert Subscription.objects.get(company=a["company"]).ends_at == ends_at + 60 * DAY


def test_code_after_expiry_counts_from_today(api, make_company, subscribe):
    a = make_company()
    subscribe(a["company"], days=-20)
    api.login(a["manager"])

    response = redeem(api, a["company"], make_code(days=30))

    assert response.json()["read_only"] is False
    assert close_to(Subscription.objects.get(company=a["company"]).ends_at, timezone.now() + 30 * DAY)


def test_single_use_code_works_for_one_company_only(api, make_company):
    a, b = make_company("A"), make_company("B")
    code = make_code()
    api.login(a["manager"])
    assert redeem(api, a["company"], code).status_code == 200

    api.login(b["manager"])
    response = redeem(api, b["company"], code)

    assert response.status_code == 400
    assert response.json()["detail"] == "Ten kod został już wykorzystany."
    assert not Subscription.objects.filter(company=b["company"]).exists()


def test_multi_use_code_works_once_per_company(api, make_company):
    a, b = make_company("A"), make_company("B")
    code = make_code(max_uses=2)
    api.login(a["manager"])
    assert redeem(api, a["company"], code).status_code == 200
    ends_at = Subscription.objects.get(company=a["company"]).ends_at

    response = redeem(api, a["company"], code)
    assert response.status_code == 400
    assert response.json()["detail"] == "Ten kod był już użyty w tej firmie."
    assert Subscription.objects.get(company=a["company"]).ends_at == ends_at

    api.login(b["manager"])
    assert redeem(api, b["company"], code).status_code == 200
    assert AccessCode.objects.get().uses == 2


def test_code_past_its_own_deadline_is_refused(api, make_company):
    a = make_company()
    api.login(a["manager"])

    response = redeem(api, a["company"], make_code(valid_until=timezone.now() - timedelta(minutes=1)))

    assert response.status_code == 400
    assert response.json()["detail"] == "Ten kod stracił ważność."
    assert redeem(api, a["company"], make_code(valid_until=timezone.now() + DAY)).status_code == 200


def test_wrong_codes_are_counted_and_limited(api, make_company):
    a = make_company()
    api.login(a["manager"])
    good = make_code()

    statuses = [redeem(api, a["company"], f"ZLYKOD{n}ABCDE").status_code for n in range(5)]
    assert statuses == [400] * 5
    assert CodeAttempt.objects.filter(user=a["manager"], success=False).count() == 5

    # The limit is reached: even a correct code has to wait.
    response = redeem(api, a["company"], good)
    assert response.status_code == 429
    assert AccessCode.objects.get().uses == 0

    CodeAttempt.objects.update(at=timezone.now() - timedelta(minutes=61))
    assert redeem(api, a["company"], good).status_code == 200
    assert CodeAttempt.objects.filter(success=True).count() == 1


def test_attempts_are_limited_per_ip_address_too(api, make_company, settings):
    settings.ACCESS_CODE_FAILURES_PER_IP_PER_HOUR = 2
    a, b = make_company("A"), make_company("B")
    api.login(a["manager"])
    assert redeem(api, a["company"], "ZLYKOD1ABCDE").status_code == 400
    assert redeem(api, a["company"], "ZLYKOD2ABCDE").status_code == 400

    api.login(b["manager"])
    assert redeem(api, b["company"], make_code()).status_code == 429


def test_only_a_manager_of_the_company_enters_codes(api, make_company):
    a, b = make_company("A"), make_company("B")
    code = make_code()

    api.login(a["worker"])
    assert redeem(api, a["company"], code).status_code == 403
    assert api.get(f"/api/companies/{a['company'].id}/subscription").status_code == 403

    api.login(b["manager"])
    assert redeem(api, a["company"], code).status_code == 404
    assert api.get(f"/api/companies/{a['company'].id}/subscription").status_code == 404

    api.logout()
    assert redeem(api, a["company"], code).status_code == 401
    assert AccessCode.objects.get().uses == 0


# --- state, banner, read-only -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (30, {"is_active": True, "read_only": False, "days_left": 30, "expiring_soon": False}),
        (7.5, {"is_active": True, "read_only": False, "days_left": 8, "expiring_soon": False}),
        (6.5, {"is_active": True, "read_only": False, "days_left": 7, "expiring_soon": True}),
        (0.01, {"is_active": True, "read_only": False, "days_left": 1, "expiring_soon": True}),
        (-0.01, {"is_active": False, "read_only": True, "days_left": 0, "expiring_soon": False}),
    ],
)
def test_subscription_state_and_banner_seven_days_before_the_end(api, make_company, subscribe, days, expected):
    a = make_company()
    subscribe(a["company"], days=days)
    api.login(a["manager"])

    body = api.get(f"/api/companies/{a['company'].id}/subscription").json()

    assert {key: body[key] for key in expected} == expected
    assert body["ends_at"] is not None


def test_company_without_a_code_is_read_only_and_keeps_its_data(api, make_company):
    a = make_company()
    api.login(a["manager"])

    body = api.get(f"/api/companies/{a['company'].id}/subscription").json()

    assert body == {
        "is_active": False,
        "read_only": True,
        "ends_at": None,
        "days_left": 0,
        "expiring_soon": False,
        "trial": False,
        "generations_used": 0,
        "generations_limit": 30,
    }
    assert api.get("/api/me").json()["companies"][0]["read_only"] is True


def test_expiry_blocks_changes_until_a_new_code_is_entered(api, make_company, subscribe):
    a = make_company()
    subscribe(a["company"], days=-1)
    api.login(a["manager"])
    url = f"/api/locations/{a['location'].id}/invitations"

    assert api.post(url, {"phone": "+48602300400"}).status_code == 402
    assert api.get(url).status_code == 200  # reading still works, nothing is deleted

    assert redeem(api, a["company"], make_code()).status_code == 200
    assert api.post(url, {"phone": "+48602300400"}).status_code == 201
    assert Invitation.objects.count() == 1


def test_generation_usage_of_the_current_month_is_reported(api, make_company, subscribe):
    a = make_company()
    subscribe(a["company"])
    this_month = timezone.localdate().replace(day=1)
    GenerationUsage.objects.create(company=a["company"], month=this_month, count=4)
    GenerationUsage.objects.create(company=a["company"], month=(this_month - DAY).replace(day=1), count=9)
    api.login(a["manager"])

    body = api.get(f"/api/companies/{a['company'].id}/subscription").json()

    assert (body["generations_used"], body["generations_limit"]) == (4, 30)


# --- registering a company ----------------------------------------------------------------------------


def test_manager_registers_a_company_with_a_code(api):
    user = User.objects.create_user("+48603500600")
    api.login(user)

    response = api.post(
        "/api/companies",
        {"name": " Piekarnia Pod Lipą ", "first_name": "Marta", "last_name": "Zając", "code": make_code(days=60)},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Piekarnia Pod Lipą"
    assert body["read_only"] is False
    company = Company.objects.get(id=body["id"])
    assert company.created_by == user
    assert Membership.objects.get(company=company).role == Role.OWNER
    assert close_to(Subscription.objects.get(company=company).ends_at, timezone.now() + 60 * DAY)
    user.refresh_from_db()
    assert user.full_name == "Marta Zając"
    assert api.get("/api/me").json()["companies"] == [
        {"id": str(company.id), "name": "Piekarnia Pod Lipą", "role": "owner", "read_only": False}
    ]


def test_company_registered_without_a_code_gets_a_trial(api):
    api.login(User.objects.create_user("+48603500600"))

    response = api.post("/api/companies", {"name": "Kawiarnia Rano"})

    assert response.status_code == 201
    body = response.json()
    assert body["read_only"] is False
    assert body["trial"] is True
    subscription = Subscription.objects.get(company_id=body["id"])
    assert subscription.source == Subscription.Source.TRIAL
    assert close_to(subscription.ends_at, timezone.now() + 14 * DAY)
    state = api.get(f"/api/companies/{body['id']}/subscription").json()
    assert state["trial"] is True and state["days_left"] == 14


def test_only_the_first_company_of_a_person_gets_a_trial(api):
    api.login(User.objects.create_user("+48603500600"))
    api.post("/api/companies", {"name": "Kawiarnia Rano"})

    response = api.post("/api/companies", {"name": "Kawiarnia Wieczór"})

    assert response.json()["read_only"] is True
    assert response.json()["trial"] is False
    assert response.json()["subscription_ends_at"] is None


def test_after_the_trial_the_company_is_read_only_until_a_code(api):
    user = User.objects.create_user("+48603500600")
    api.login(user)
    company_id = api.post("/api/companies", {"name": "Kawiarnia Rano"}).json()["id"]
    Subscription.objects.filter(company_id=company_id).update(ends_at=timezone.now() - DAY)

    blocked = api.post("/api/locations", {"company_id": company_id, "name": "Rynek"})
    assert blocked.status_code == 402
    assert "Okres próbny" in blocked.json()["detail"]

    redeemed = api.post(f"/api/companies/{company_id}/subscription/redeem", {"code": make_code(days=30)})
    assert redeemed.status_code == 200
    assert redeemed.json()["trial"] is False
    assert redeemed.json()["days_left"] == 30


def test_wrong_code_at_registration_creates_nothing_but_counts_the_attempt(api):
    user = User.objects.create_user("+48603500600")
    api.login(user)

    response = api.post("/api/companies", {"name": "Kawiarnia Rano", "code": "ZLYKOD1ABCDE"})

    assert response.status_code == 400
    assert "Nie ma takiego kodu" in response.json()["detail"]
    assert not Company.objects.exists()
    assert not Membership.objects.exists()
    assert CodeAttempt.objects.filter(user=user, success=False).count() == 1


def test_company_name_is_required(api):
    api.login(User.objects.create_user("+48603500600"))

    assert api.post("/api/companies", {"name": "   "}).status_code == 400
    assert api.post("/api/companies", {}).status_code == 422


# --- admin --------------------------------------------------------------------------------------------


@pytest.fixture
def superadmin(client):
    admin = User.objects.create_superuser("+48500999999", "haslo-testowe-123")
    client.force_login(admin)
    return admin


def test_superadmin_generates_codes_shown_once_and_stored_as_hashes(client, superadmin, api, make_company):
    url = reverse("admin:billing_accesscode_generate")
    assert client.get(url).status_code == 200
    assert client.get(reverse("admin:billing_accesscode_add")).status_code == 302

    response = client.post(
        url,
        {"count": 3, "days": 60, "max_uses": 1, "valid_until_0": "", "valid_until_1": "", "note": "Pszepiekarnia"},
    )

    assert response.status_code == 200
    page = response.content.decode()
    shown = re.findall(r"\b[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}\b", page)
    assert len(shown) == 3
    codes = AccessCode.objects.all()
    assert codes.count() == 3
    assert {c.code_hash for c in codes} == {hash_code(code) for code in shown}
    assert all(c.days == 60 and c.note == "Pszepiekarnia" and c.created_by == superadmin for c in codes)
    for code in shown:
        assert normalize_code(code) not in "".join(f"{c.code_hash}{c.prefix}" for c in codes)

    # The list never shows a whole code, and a generated code really works.
    assert shown[0] not in client.get(reverse("admin:billing_accesscode_changelist")).content.decode()
    a = make_company()
    api.login(a["manager"])
    assert redeem(api, a["company"], shown[0]).status_code == 200


def test_generate_form_rejects_bad_values(client, superadmin):
    response = client.post(
        reverse("admin:billing_accesscode_generate"),
        {"count": 0, "days": 45, "max_uses": 1, "valid_until_0": "2020-01-01", "valid_until_1": "12:00", "note": ""},
    )

    assert response.status_code == 200
    assert not AccessCode.objects.exists()


def test_generate_page_is_only_for_the_superadmin(client, make_company):
    a = make_company()
    client.force_login(a["manager"])

    response = client.post(reverse("admin:billing_accesscode_generate"), {"count": 1, "days": 30, "max_uses": 1})

    assert response.status_code == 302
    assert not AccessCode.objects.exists()


def test_superadmin_changes_a_phone_number_and_is_told_about_pending_invitations(client, superadmin, make_company):
    a = make_company()
    worker = a["worker"]
    old_phone = worker.phone_e164
    Invitation.objects.create(location=a["location"], phone_e164=old_phone, role="manager")
    form = client.get(reverse("admin:accounts_user_change", args=[worker.pk])).context["adminform"].form
    data = {name: value for name, value in form.initial.items() if value is not None and name != "password"}
    data.update(phone_e164="603 111 222", groups=[], user_permissions=[])
    data["date_joined_0"], data["date_joined_1"] = "2026-11-12", "10:00:00"
    data.pop("date_joined", None)
    data.pop("last_login", None)

    response = client.post(reverse("admin:accounts_user_change", args=[worker.pk]), data, follow=True)

    assert response.status_code == 200, response.content.decode()[:3000]
    worker.refresh_from_db()
    assert worker.phone_e164 == "+48603111222"
    # History stays with the account: same membership and employee profile.
    assert Membership.objects.get(user=worker).employee_profile == a["employee"]
    messages = " ".join(str(m) for m in response.context["messages"])
    assert "Oczekujące zaproszenia na stary numer: 1" in messages
    assert Invitation.objects.get().phone_e164 == old_phone
