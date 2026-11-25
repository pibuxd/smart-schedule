"""The optional bank account number for pay: the person saves it, managers of their locations see and may set it."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.accounts.models import User, bank_account_text, normalize_bank_account
from apps.assistant.tools import clean
from apps.notifications.models import Notification
from apps.notifications.services import notification_text
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db

VALID = "61109010140000071219812874"  # PL61 1090 1014 0000 0712 1981 2874, the usual example of a Polish IBAN


@pytest.fixture
def shop(make_company, subscribe):
    data = make_company("Złoty Kłos")
    subscribe(data["company"])
    data["employee"].positions.add(data["position"])
    return data


@pytest.mark.parametrize(
    "raw",
    [
        VALID,
        "61 1090 1014 0000 0712 1981 2874",
        "PL61 1090 1014 0000 0712 1981 2874",
        "pl61-1090-1014-0000-0712-1981-2874",
    ],
)
def test_a_polish_account_number_in_any_usual_spelling(raw):
    assert normalize_bank_account(raw) == VALID
    assert bank_account_text(VALID) == "61 1090 1014 0000 0712 1981 2874"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("61 1090 1014 0000 0712 1981 287", "26 cyfr"),  # a digit missing
        ("DE89 3704 0044 0532 0130 00", "26 cyfr"),  # a foreign IBAN
        ("61 1090 1014 0000 0712 1981 287x", "26 cyfr"),
        ("61 1090 1014 0000 0712 1981 2875", "błąd"),  # one digit wrong
        ("61 1090 1014 0000 0712 1918 2874", "błąd"),  # two digits swapped
    ],
)
def test_a_wrong_number_is_caught_with_a_polish_sentence(raw, message):
    with pytest.raises(ValidationError) as caught:
        normalize_bank_account(raw)
    assert message in caught.value.messages[0]


def test_no_number_is_fine_and_the_database_keeps_only_26_digits(shop):
    assert normalize_bank_account("  ") == "" and normalize_bank_account(None) == ""
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=shop["worker"].pk).update(bank_account="61 1090")


def test_the_person_saves_and_removes_their_own_number(api, shop):
    api.login(shop["worker"])
    assert api.get("/api/me").json()["bank_account"] == ""

    saved = api.patch("/api/me", {"bank_account": "PL61 1090 1014 0000 0712 1981 2874"})
    assert saved.status_code == 200 and saved.json()["bank_account"] == VALID
    # The name alone changes only the name.
    renamed = api.patch("/api/me", {"first_name": "Ola", "last_name": "Nowak"}).json()
    assert (renamed["first_name"], renamed["bank_account"]) == ("Ola", VALID)

    typo = api.patch("/api/me", {"bank_account": "61 1090 1014 0000 0712 1981 2875"})
    assert typo.status_code == 400 and typo.json()["detail"] == "W tym numerze konta jest błąd. Sprawdź cyfry."
    assert User.objects.get(pk=shop["worker"].pk).bank_account == VALID

    assert api.patch("/api/me", {"bank_account": ""}).json()["bank_account"] == ""
    assert api.patch("/api/me", {"first_name": " "}).status_code == 400


def test_managers_of_the_location_see_it_other_people_do_not(api, shop, make_company):
    User.objects.filter(pk=shop["worker"].pk).update(bank_account=VALID)
    employees = f"/api/locations/{shop['location'].pk}/employees"

    api.login(shop["manager"])
    [row] = api.get(employees).json()
    assert row["bank_account"] == VALID

    api.login(shop["worker"])  # a plain employee does not read the list of people
    assert api.get(employees).status_code == 403
    api.login(make_company("Inna")["manager"])
    assert api.get(employees).status_code == 404


def test_a_manager_sets_the_number_and_the_person_is_told(api, shop):
    api.login(shop["manager"])
    url = f"/api/employees/{shop['employee'].pk}"
    [before] = api.get(f"/api/locations/{shop['location'].pk}/employees").json()

    body = api.patch(url, {"revision": before["revision"], "bank_account": "61 1090 1014 0000 0712 1981 2874"}).json()

    assert body["bank_account"] == VALID and body["revision"] != before["revision"]
    note = Notification.objects.get(user=shop["worker"], kind="bank_account_set")
    assert note.payload == {"ending": "2874"}  # never the whole number
    assert "kończy się na 2874" in notification_text(note.kind, note.payload)
    # The manager's form had the old number: saving it would undo what was just saved.
    stale = api.patch(url, {"revision": before["revision"], "max_hours_month": 100})
    assert stale.status_code == 409

    assert api.patch(url, {"bank_account": "123"}).json()["detail"].startswith("Numer konta ma 26 cyfr")
    assert api.patch(url, {"bank_account": ""}).json()["bank_account"] == ""
    removed = Notification.objects.filter(user=shop["worker"], kind="bank_account_set").latest("created_at")
    assert notification_text(removed.kind, removed.payload).startswith("Kierownik usunął Twój numer konta")
    # Other changes of the person leave the number alone and tell nobody.
    api.patch(url, {"max_hours_month": 120})
    assert Notification.objects.filter(kind="bank_account_set").count() == 2


def test_only_the_person_changes_a_number_shared_with_another_company(api, shop, make_company):
    api.login(shop["manager"])
    [row] = api.get(f"/api/locations/{shop['location'].pk}/employees").json()
    assert row["other_company"] is False
    other = make_company("Inna")
    Membership.objects.create(company=other["company"], user=shop["worker"])

    # The manager's form says so before anything is typed.
    [row] = api.get(f"/api/locations/{shop['location'].pk}/employees").json()
    assert row["other_company"] is True
    response = api.patch(f"/api/employees/{shop['employee'].pk}", {"bank_account": VALID})

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Ta osoba ma konto także w innej firmie, więc numer konta może zmienić tylko ona sama."
    )
    assert User.objects.get(pk=shop["worker"].pk).bank_account == ""
    assert api.patch(f"/api/employees/{shop['employee'].pk}", {"max_hours_month": 100}).json()["other_company"] is True


def test_a_manager_who_works_shifts_sets_their_own_number_without_a_notification(api, shop):
    api.login(shop["manager"])
    me = api.post(f"/api/locations/{shop['location'].pk}/employees/me").json()

    assert api.patch(f"/api/employees/{me['id']}", {"bank_account": VALID}).json()["bank_account"] == VALID
    assert not Notification.objects.filter(kind="bank_account_set").exists()


def test_the_assistant_never_reads_account_numbers():
    row = {"first_name": "Ola", "bank_account": VALID, "phone": "+48601000001", "position_ids": ["p1"]}
    assert clean({"rows": [row]}) == {"rows": [{"first_name": "Ola", "position_ids": ["p1"]}]}


def test_the_superadmin_types_a_number_with_spaces_in_the_admin(shop):
    from apps.accounts.admin import UserEditForm

    user = shop["worker"]
    data = {
        "phone_e164": user.phone_e164,
        "first_name": user.first_name,
        "last_name": "",
        "bank_account": "PL61 1090 1014 0000 0712 1981 2874",
        "is_active": True,
        "date_joined": user.date_joined,
    }
    form = UserEditForm(data, instance=user)
    assert form.is_valid(), form.errors
    assert form.save().bank_account == VALID

    wrong = UserEditForm({**data, "bank_account": "61 1090 1014 0000 0712 1981 2875"}, instance=user)
    assert not wrong.is_valid() and "błąd" in wrong.errors["bank_account"][0]
