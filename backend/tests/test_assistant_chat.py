"""The chat restores only its author's conversation, within the managed location."""

from datetime import timedelta

from django.utils import timezone

from apps.accounts.models import User
from apps.assistant.models import AssistantCommand
from apps.tenancy.models import Location, Membership, Role
from tests.conftest import next_phone


def message(shop, **changes):
    return AssistantCommand.objects.create(
        **{
            "location": shop["location"],
            "created_by": shop["manager"],
            "text": "Moja wiadomość",
            "status": AssistantCommand.Status.READY,
            "plan": {"reply": "Moja odpowiedź"},
            **changes,
        }
    )


def test_history_is_private_to_the_author_and_location(api, make_company):
    shop = make_company()
    other = make_company("Inna firma")
    colleague = User.objects.create_user(next_phone())
    Membership.objects.create(company=shop["company"], user=colleague, role=Role.OWNER)
    another_location = Location.objects.create(company=shop["company"], name="Drugi lokal")
    own = message(shop)
    message(shop, created_by=colleague, text="Rozmowa innego kierownika")
    message(shop, location=another_location, text="Rozmowa w innym lokalu")
    message(shop, created_by=None, text="Rozmowa bez autora")
    message(other)

    api.login(shop["manager"])
    result = api.get(f"/api/locations/{shop['location'].pk}/assistant-commands")
    assert result.status_code == 200
    assert [row["id"] for row in result.json()] == [str(own.pk)]
    assert result.json()[0]["reply"] == "Moja odpowiedź"
    assert "assistant_answer" not in result.json()[0]
    assert api.get(f"/api/locations/{other['location'].pk}/assistant-commands").status_code == 404


def test_history_requires_a_session_and_management_access(api, make_company):
    shop = make_company()
    message(shop)
    url = f"/api/locations/{shop['location'].pk}/assistant-commands"
    assert api.get(url).status_code == 401
    api.login(shop["worker"])
    assert api.get(url).status_code == 403


def test_history_keeps_latest_fifty_in_order_including_decided_messages(api, make_company, subscribe):
    shop = make_company()
    subscribe(shop["company"], days=-1)
    start = timezone.now() - timedelta(hours=1)
    saved = [message(shop, created_at=start + timedelta(seconds=i), text=f"Wiadomość {i}") for i in range(52)]
    saved[-2].status = AssistantCommand.Status.APPLIED
    saved[-2].save()
    saved[-1].status = AssistantCommand.Status.DISMISSED
    saved[-1].save()
    api.login(shop["manager"])
    response = api.get(f"/api/locations/{shop['location'].pk}/assistant-commands")
    assert response.status_code == 200  # Expired access still permits reading.
    rows = response.json()
    assert [row["id"] for row in rows] == [str(row.pk) for row in saved[2:]]
    assert [row["status"] for row in rows[-2:]] == ["applied", "dismissed"]
    assert all(not row["can_apply"] for row in rows[-2:])
