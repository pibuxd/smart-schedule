"""The optional bank account number for pay (plain text, any bank): the person saves it, managers of their locations
see and may set it."""

import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import User, bank_account_ending, bank_account_text, normalize_bank_account
from apps.assistant.tools import clean
from apps.notifications.models import Notification
from apps.notifications.services import notification_text
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db

VALID = "PL61 1090 1014 0000 0712 1981 2874"  # the usual example of a Polish IBAN


@pytest.fixture
def shop(make_company, subscribe):
    data = make_company("Złoty Kłos")
    subscribe(data["company"])
    data["employee"].positions.add(data["position"])
    return data


@pytest.mark.parametrize(
    ("raw", "kept"),
    [
        ("  PL61 1090 1014   0000 0712\t1981 2874 ", VALID),
        ("61109010140000071219812874", "61109010140000071219812874"),
        ("Revolut LT12 3250 0123 4567 8910", "Revolut LT12 3250 0123 4567 8910"),
        ("UA21 3223 1300 0002 6007 2335 6600 1", "UA21 3223 1300 0002 6007 2335 6600 1"),
        ("  ", ""),
        (None, ""),
    ],
)
def test_any_bank_is_kept_as_written_with_the_spaces_tidied(raw, kept):
    # Piotr, 25.11.2026: people have Revolut or a Ukrainian bank, so the number is plain text.
    assert normalize_bank_account(raw) == kept


def test_only_a_too_long_text_is_refused():
    assert normalize_bank_account("1" * 100) == "1" * 100
    with pytest.raises(ValidationError) as caught:
        normalize_bank_account("1" * 101)
    assert caught.value.messages == ["Numer konta może mieć najwyżej 100 znaków."]


def test_a_spreadsheet_gets_digits_grouped_and_any_other_text_as_written():
    assert bank_account_text("61109010140000071219812874") == "61 1090 1014 0000 0712 1981 2874"
    assert bank_account_text("12345678901234567890") == "1234 5678 9012 3456 7890"
    assert bank_account_text("Revolut LT12 3250") == "Revolut LT12 3250"
    assert bank_account_text("") == ""
    assert bank_account_ending(VALID) == "2874" and bank_account_ending("") == ""


def test_the_person_saves_and_removes_their_own_number(api, shop):
    api.login(shop["worker"])
    assert api.get("/api/me").json()["bank_account"] == ""

    saved = api.patch("/api/me", {"bank_account": " PL61 1090 1014  0000 0712 1981 2874"})
    assert saved.status_code == 200 and saved.json()["bank_account"] == VALID
    # The name alone changes only the name.
    renamed = api.patch("/api/me", {"first_name": "Ola", "last_name": "Nowak"}).json()
    assert (renamed["first_name"], renamed["bank_account"]) == ("Ola", VALID)

    too_long = api.patch("/api/me", {"bank_account": "1" * 101})
    assert too_long.status_code == 400 and too_long.json()["detail"] == "Numer konta może mieć najwyżej 100 znaków."
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

    body = api.patch(url, {"revision": before["revision"], "bank_account": "PL61 1090 1014 0000 0712 1981 2874"}).json()

    assert body["bank_account"] == VALID and body["revision"] != before["revision"]
    note = Notification.objects.get(user=shop["worker"], kind="bank_account_set")
    assert note.payload == {"ending": "2874"}  # never the whole number
    assert "kończy się na 2874" in notification_text(note.kind, note.payload)
    # The manager's form had the old number: saving it would undo what was just saved.
    stale = api.patch(url, {"revision": before["revision"], "max_hours_month": 100})
    assert stale.status_code == 409

    revolut = api.patch(url, {"bank_account": "Revolut LT12 3250 0123 4567 8910"}).json()
    assert revolut["bank_account"] == "Revolut LT12 3250 0123 4567 8910"
    assert api.patch(url, {"bank_account": ""}).json()["bank_account"] == ""
    removed = Notification.objects.filter(user=shop["worker"], kind="bank_account_set").latest("created_at")
    assert notification_text(removed.kind, removed.payload).startswith("Kierownik usunął Twój numer konta")
    # Other changes of the person leave the number alone and tell nobody.
    api.patch(url, {"max_hours_month": 120})
    assert Notification.objects.filter(kind="bank_account_set").count() == 3


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


def test_the_superadmin_types_a_number_in_the_admin(shop):
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

    spaced = UserEditForm({**data, "bank_account": "PL61  1090 1014 0000 0712 1981 2874  "}, instance=user)
    assert spaced.is_valid() and spaced.cleaned_data["bank_account"] == VALID
