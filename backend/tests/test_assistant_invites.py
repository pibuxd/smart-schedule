"""The manager's assistant reads a list of people (a file or the message) and proposes invitations; nothing is saved
until the manager accepts the plan. Phone numbers never reach the model (docs/plan.md, section 40)."""

import re
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.assistant import llm, services
from apps.assistant.models import AssistantCommand, AssistantRuleSet
from apps.scheduling.models import SchedulePeriod
from apps.staffing.models import Position
from apps.tenancy.models import Invitation, Location, Membership, Role

pytestmark = pytest.mark.django_db

CSV = "Imię i nazwisko;Telefon;Stanowisko\nKowalska Anna;512 345 678;kasjerka\nJan Nowak;600-100-200;Piekarz\n"


@pytest.fixture
def a(make_company, subscribe):
    company = make_company("A")
    subscribe(company["company"])
    Position.objects.create(location=company["location"], name="Kasa")
    return company


@pytest.fixture
def with_key(settings):
    settings.OPENROUTER_API_KEY = "test-key"


def shown(lines: list[str]) -> list[str]:
    """Numbers in plan lines keep their groups together with non-breaking spaces."""
    return [re.sub(r"(?<=\d) (?=\d)", "\u00a0", line) for line in lines]


def plan(**changes) -> llm.CommandPlan:
    values = {
        "topic": "app",
        "reply": "Znalazłem 2 osoby.",
        "question": None,
        "rule_changes": [],
        "new_instructions": [],
        "remove_instructions": [],
    }
    return llm.CommandPlan(**{**values, **changes})


def person(first, last, phone, positions=(), location=None, manager=False) -> llm.PersonToInvite:
    return llm.PersonToInvite(
        first_name=first, last_name=last, phone=phone, positions=list(positions), location=location, manager=manager
    )


def send_file(api, location, monkeypatch, answer, content=CSV, name="lista.csv", text=""):
    seen = {}

    def fake(text, context, toolbox=None, file_text="", file_name=""):
        seen.update(text=text, context=context, file_text=file_text, file_name=file_name)
        return answer

    monkeypatch.setattr(llm, "plan_command", fake)
    file = SimpleUploadedFile(name, content.encode() if isinstance(content, str) else content)
    created = api.client.post(f"/api/locations/{location.pk}/assistant-commands/file", {"file": file, "text": text})
    assert created.status_code == 201, created.json()
    assert created.json()["file_name"] == name
    assert services.run_command(created.json()["id"]) == "ready"
    return api.get(f"/api/assistant-commands/{created.json()['id']}").json(), seen


def test_a_file_becomes_a_plan_of_invitations_without_numbers_for_the_model(api, a, with_key, monkeypatch):
    api.login(a["manager"])
    answer = plan(
        invitations=[person("Anna", "Kowalska", "[TEL1]", ["Kasa"]), person("Jan", "Nowak", "[TEL2]", ["Piekarz"])]
    )

    body, seen = send_file(api, a["location"], monkeypatch, answer)

    # The model reads the file with marks instead of numbers, and sees the manager's locations.
    assert seen["text"] == "Zaproś osoby z tego pliku."
    assert "512" not in seen["file_text"] and "600" not in seen["file_text"]
    assert "Kowalska Anna | [TEL1] | kasjerka" in seen["file_text"]
    assert seen["file_name"] == "lista.csv"
    assert f"Lokale tego kierownika (do zaproszeń): {a['location'].name}." in seen["context"]
    assert body["lines"] == shown(["Zaproszę: Anna Kowalska, 512 345 678, Kasa.", "Zaproszę: Jan Nowak, 600 100 200."])
    assert body["notes"][0] == services.INVITES_NOTE
    assert "Jan Nowak: Piekarz" in body["notes"][1]
    assert body["can_apply"] and body["has_invites"] and body["outside_agreements"]
    assert not Invitation.objects.exists()
    # The file's text is dropped once the assistant has read it; the name stays for the chat.
    assert AssistantCommand.objects.get().attachment == {"name": "lista.csv"}

    applied = api.post(f"/api/assistant-commands/{body['id']}/apply")

    assert applied.status_code == 200, applied.json()
    assert applied.json()["notes"] == [n for n in body["notes"] if n != services.INVITES_NOTE]
    anna, jan = Invitation.objects.order_by("phone_e164")
    assert (anna.phone_e164, anna.first_name, anna.last_name) == ("+48512345678", "Anna", "Kowalska")
    assert [p.name for p in anna.positions.all()] == ["Kasa"]
    assert jan.phone_e164 == "+48600100200" and not jan.positions.exists()
    assert anna.invited_by == a["manager"]


def test_people_who_cannot_be_invited_are_left_out_with_a_note(api, a, with_key, monkeypatch):
    api.login(a["manager"])
    answer = plan(
        invitations=[
            person("Anna", "Kowalska", "[TEL1]"),
            person("Ktoś", "", "[TEL7]"),  # a mark that is not in the text
            person("Bez", "Numeru", ""),
            person("Pracownik", "", "[TEL2]"),  # already works here
            person("Ewa", "Lis", "[TEL3]", location="Księżyc"),
        ]
    )
    text = f"Anna 512 345 678, Pracownik {a['worker'].phone_e164}, Ewa 602 300 400"

    body, _ = send_file(api, a["location"], monkeypatch, answer, content=text, name="lista.txt")

    assert body["lines"] == shown(["Zaproszę: Anna Kowalska, 512 345 678."])
    assert body["notes"][1] == (
        "Nie zaproszę: Ktoś (numeru nie ma w Twojej wiadomości ani w pliku); Bez Numeru (brak numeru); "
        "Pracownik (już pracuje w tym lokalu); Ewa Lis (nie ma lokalu „Księżyc”)."
    )
    assert body["can_apply"]


def test_invitations_to_another_managed_location_and_managers_only_by_the_owner(api, a, with_key, monkeypatch):
    other = Location.objects.create(company=a["company"], name="Piekarnia Wieliczka")
    Position.objects.create(location=other, name="Piec")
    api.login(a["manager"])  # the owner
    # The owner's own words name the manager's number; the file only says "kierownik" next to Ewa.
    answer = plan(
        invitations=[
            person("Anna", "Kowalska", "[TEL2]", ["piec"], location="Wieliczka"),
            person("Jan", "Nowak", "[TEL1]", manager=True),
            person("Ewa", "Lis", "[TEL3]", manager=True),
        ]
    )

    body, seen = send_file(
        api,
        a["location"],
        monkeypatch,
        answer,
        content="Anna 512345678\nJan 600100200\nEwa 601200300 kierownik",
        text="Jan Nowak 600 100 200 będzie kierownikiem",
    )

    assert seen["text"] == "Jan Nowak [TEL1] będzie kierownikiem"
    assert seen["file_text"] == "Anna [TEL2]\nJan [TEL1]\nEwa [TEL3] kierownik"
    assert body["lines"] == shown(
        [
            "Zaproszę: Anna Kowalska, 512 345 678, Piec (lokal Piekarnia Wieliczka).",
            f"Zaproszę: Jan Nowak, 600 100 200, kierownik (lokal {a['location'].name}).",
            f"Zaproszę: Ewa Lis, 601 200 300 (lokal {a['location'].name}).",
        ]
    )
    # A manager only from the owner's words, never from a file alone.
    assert any(
        note.startswith("Z pliku zapraszam tylko pracowników, więc jako pracownika zaproszę: Ewa Lis.")
        for note in body["notes"]
    )
    assert api.post(f"/api/assistant-commands/{body['id']}/apply").status_code == 200
    anna = Invitation.objects.get(phone_e164="+48512345678")
    assert anna.location == other and [p.name for p in anna.positions.all()] == ["Piec"]
    assert Invitation.objects.get(phone_e164="+48600100200").role == Role.MANAGER
    assert Invitation.objects.get(phone_e164="+48601200300").role == Role.EMPLOYEE

    # A manager (not the owner) cannot invite managers, nor to a location they do not manage.
    boss = a["manager"].__class__.objects.create_user("+48602300499")
    membership = Membership.objects.create(company=a["company"], user=boss, role=Role.MANAGER)
    membership.locations.add(a["location"])
    api.login(boss)
    answer = plan(
        invitations=[
            person("Ola", "", "[TEL1]", manager=True),
            person("Iza", "", "[TEL2]", location="Piekarnia Wieliczka"),
        ]
    )
    body, seen = send_file(
        api, a["location"], monkeypatch, answer, content="Iza 601000002", text="Ola 601000001 ma być kierownikiem"
    )
    assert "Piekarnia Wieliczka" not in seen["context"]
    assert body["lines"] == []
    assert "Ola (kierownika zaprasza tylko właściciel firmy)" in body["notes"][0]
    assert "Iza (nie ma lokalu „Piekarnia Wieliczka”)" in body["notes"][0]
    assert not body["can_apply"]


def test_a_typed_message_with_numbers_works_the_same_and_history_hides_numbers(api, a, with_key, monkeypatch):
    api.login(a["manager"])
    seen = []

    def fake(text, context, toolbox=None):
        seen.append((text, context))
        return plan(invitations=[person("Anna", "Kowalska", "[TEL1]")])

    monkeypatch.setattr(llm, "plan_command", fake)
    for _ in range(2):
        created = api.post(
            f"/api/locations/{a['location'].pk}/assistant-commands", {"text": "Zaproś Annę Kowalską 512 345 678"}
        )
        services.run_command(created.json()["id"])

    assert seen[0][0] == "Zaproś Annę Kowalską [TEL1]"
    # The earlier message and its plan line come back without the number.
    assert "512" not in seen[1][1]
    assert "Zaproś Annę Kowalską [numer]" in seen[1][1]


def test_people_invited_meanwhile_are_skipped_on_acceptance(api, a, with_key, monkeypatch):
    today = timezone.localdate()
    SchedulePeriod.objects.create(
        location=a["location"], start=today, end=today + timedelta(days=30), availability_requested_at=timezone.now()
    )
    api.login(a["manager"])
    answer = plan(invitations=[person("Anna", "", "[TEL1]"), person("Jan", "", "[TEL2]")])
    body, _ = send_file(api, a["location"], monkeypatch, answer, content="Anna 512345678\nJan 600100200")
    assert api.post(f"/api/locations/{a['location'].pk}/invitations", {"phone": "512345678"}).status_code == 201
    # The period's schedule is published meanwhile: invitations do not depend on the agreements.
    AssistantRuleSet.objects.update(consumed_at=timezone.now())

    applied = api.post(f"/api/assistant-commands/{body['id']}/apply")

    assert applied.status_code == 200, applied.json()
    assert applied.json()["notes"][-1] == (
        "Tych osób nie zaprosiłem, bo w międzyczasie coś się zmieniło: Anna (ma już zaproszenie)."
    )
    assert Invitation.objects.filter(phone_e164="+48600100200").exists()


def test_an_unreadable_file_or_no_key(api, a, monkeypatch):
    api.login(a["manager"])
    url = f"/api/locations/{a['location'].pk}/assistant-commands/file"

    response = api.client.post(url, {"file": SimpleUploadedFile("stary.xls", b"\xd0\xcf\x11\xe0...")})
    assert response.status_code == 400 and "xlsx" in response.json()["detail"]
    assert not AssistantCommand.objects.exists()

    # Without a key the message is kept as unavailable, without the file's text.
    response = api.client.post(url, {"file": SimpleUploadedFile("lista.csv", CSV.encode())})
    assert response.status_code == 201 and response.json()["status"] == "unavailable"
    assert AssistantCommand.objects.get().attachment == {"name": "lista.csv"}

    api.login(a["worker"])
    assert api.client.post(url, {"file": SimpleUploadedFile("lista.csv", CSV.encode())}).status_code == 403
