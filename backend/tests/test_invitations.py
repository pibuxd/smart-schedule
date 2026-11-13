"""Invitations: the manager invites by phone number, the invited person accepts or declines in the app."""

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.staffing.models import EmployeeProfile
from apps.tenancy.models import Invitation, InvitationStatus, Location, Membership, Role

pytestmark = pytest.mark.django_db

PHONE = "+48602300400"


@pytest.fixture
def a(make_company, subscribe):
    company = make_company("A")
    subscribe(company["company"])
    return company


@pytest.fixture
def b(make_company, subscribe):
    company = make_company("B")
    subscribe(company["company"])
    return company


def invite(api, location, phone=PHONE, **fields):
    return api.post(f"/api/locations/{location.id}/invitations", {"phone": phone, **fields})


# --- the manager's side -------------------------------------------------------------------------------


def test_manager_invites_by_phone_number_and_no_sms_is_sent(api, a, sms_outbox):
    api.login(a["manager"])

    response = invite(api, a["location"], "602 300 400", first_name="Ewa", last_name="Lis")

    assert response.status_code == 201
    body = response.json()
    assert body["phone"] == PHONE
    assert body["status"] == "pending"
    assert body["role"] == "employee"
    assert sms_outbox == []
    invitation = Invitation.objects.get()
    assert invitation.company == a["company"]
    assert invitation.invited_by == a["manager"]

    listed = api.get(f"/api/locations/{a['location'].id}/invitations").json()
    assert [row["id"] for row in listed] == [body["id"]]


def test_one_pending_invitation_per_location_and_number(api, a):
    api.login(a["manager"])
    assert invite(api, a["location"]).status_code == 201

    response = invite(api, a["location"])
    assert response.status_code == 409
    assert "oczekujące zaproszenie" in response.json()["detail"]
    assert Invitation.objects.count() == 1

    # The same number can be invited to another location of the company.
    other = Location.objects.create(company=a["company"], name="Drugi lokal")
    assert invite(api, other).status_code == 201


def test_invalid_phone_number_is_refused(api, a):
    api.login(a["manager"])
    assert invite(api, a["location"], "12345").status_code == 400
    assert invite(api, a["location"], "+49 30 901820").status_code == 400


def test_person_already_working_in_the_company_cannot_be_invited_again(api, a):
    api.login(a["manager"])

    response = invite(api, a["location"], a["worker"].phone_e164)

    assert response.status_code == 409
    assert "jest już pracownikiem" in response.json()["detail"]


def test_employee_cannot_invite_or_see_invitations(api, a):
    api.login(a["worker"])

    assert invite(api, a["location"]).status_code == 403
    assert api.get(f"/api/locations/{a['location'].id}/invitations").status_code == 403


def test_manager_handles_only_assigned_locations(api, a):
    other = Location.objects.create(company=a["company"], name="Drugi lokal")
    manager = User.objects.create_user("+48602300499")
    membership = Membership.objects.create(company=a["company"], user=manager, role=Role.MANAGER)
    membership.locations.add(other)
    api.login(manager)

    assert invite(api, other).status_code == 201
    assert invite(api, a["location"]).status_code == 403
    # Only the owner invites other managers.
    assert invite(api, other, "+48602300401", role="manager").status_code == 403


def test_manager_cancels_a_pending_invitation(api, a):
    api.login(a["manager"])
    invitation_id = invite(api, a["location"]).json()["id"]

    response = api.post(f"/api/invitations/{invitation_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["decided_at"] is not None
    assert api.post(f"/api/invitations/{invitation_id}/cancel").status_code == 409
    # After cancelling, the number can be invited again.
    assert invite(api, a["location"]).status_code == 201


def test_other_company_gets_404_on_every_invitation_endpoint(api, a, b):
    api.login(a["manager"])
    invitation_id = invite(api, a["location"]).json()["id"]

    api.login(b["manager"])
    assert api.get(f"/api/locations/{a['location'].id}/invitations").status_code == 404
    assert invite(api, a["location"], "+48602300401").status_code == 404
    assert api.post(f"/api/invitations/{invitation_id}/cancel").status_code == 404
    assert api.post(f"/api/invitations/{invitation_id}/accept").status_code == 404
    assert api.post(f"/api/invitations/{invitation_id}/decline").status_code == 404
    assert Invitation.objects.get().status == InvitationStatus.PENDING


def test_invitation_endpoints_need_login(api, a):
    invitation = Invitation.objects.create(location=a["location"], phone_e164=PHONE)

    assert invite(api, a["location"]).status_code == 401
    assert api.get(f"/api/locations/{a['location'].id}/invitations").status_code == 401
    assert api.post(f"/api/invitations/{invitation.id}/accept").status_code == 401
    assert api.post(f"/api/invitations/{invitation.id}/cancel").status_code == 401


# --- the invited person's side ------------------------------------------------------------------------


def test_invited_person_sees_the_invitation_and_accepts_it(api, a):
    api.login(a["manager"])
    invitation_id = invite(api, a["location"], first_name="Ewa", last_name="Lis").json()["id"]
    user = User.objects.create_user(PHONE)
    api.login(user)

    listed = api.get("/api/me/invitations").json()
    assert len(listed) == 1
    assert listed[0]["company_name"] == "A"
    assert listed[0]["location_name"] == a["location"].name
    assert api.get("/api/me").json()["pending_invitations"] == 1

    response = api.post(f"/api/invitations/{invitation_id}/accept")
    assert response.status_code == 200

    membership = Membership.objects.get(user=user)
    assert membership.company == a["company"]
    assert membership.role == Role.EMPLOYEE
    profile = EmployeeProfile.objects.get(membership=membership)
    assert profile.home_location == a["location"]
    user.refresh_from_db()
    assert user.full_name == "Ewa Lis"

    me = api.get("/api/me").json()
    assert me["pending_invitations"] == 0
    assert [(c["name"], c["role"]) for c in me["companies"]] == [("A", "employee")]
    assert api.get("/api/me/invitations").json() == []
    assert api.post(f"/api/invitations/{invitation_id}/accept").status_code == 409


def test_accepting_does_not_overwrite_an_existing_name(api, a):
    Invitation.objects.create(location=a["location"], phone_e164=PHONE, first_name="Ewka", last_name="L.")
    user = User.objects.create_user(PHONE, first_name="Ewa", last_name="Lis")
    api.login(user)

    api.post(f"/api/invitations/{Invitation.objects.get().id}/accept")

    user.refresh_from_db()
    assert user.full_name == "Ewa Lis"


def test_declining_creates_nothing_and_allows_a_new_invitation(api, a):
    api.login(a["manager"])
    invitation_id = invite(api, a["location"]).json()["id"]
    user = User.objects.create_user(PHONE)
    api.login(user)

    response = api.post(f"/api/invitations/{invitation_id}/decline")

    assert response.status_code == 200
    assert not Membership.objects.filter(user=user).exists()
    assert Invitation.objects.get().status == InvitationStatus.DECLINED
    assert api.post(f"/api/invitations/{invitation_id}/accept").status_code == 409

    api.login(a["manager"])
    assert invite(api, a["location"]).status_code == 201


def test_cancelled_invitation_cannot_be_accepted(api, a):
    invitation = Invitation.objects.create(
        location=a["location"], phone_e164=PHONE, status=InvitationStatus.CANCELLED, decided_at=timezone.now()
    )
    user = User.objects.create_user(PHONE)
    api.login(user)

    assert api.get("/api/me/invitations").json() == []
    assert api.post(f"/api/invitations/{invitation.id}/accept").status_code == 409
    assert not Membership.objects.filter(user=user).exists()


def test_only_the_invited_number_can_answer(api, a):
    invitation = Invitation.objects.create(location=a["location"], phone_e164=PHONE)
    api.login(User.objects.create_user("+48602300401"))

    assert api.post(f"/api/invitations/{invitation.id}/accept").status_code == 404
    assert api.post(f"/api/invitations/{invitation.id}/decline").status_code == 404
    # A manager of the company cannot accept on the person's behalf either.
    api.login(a["manager"])
    assert api.post(f"/api/invitations/{invitation.id}/accept").status_code == 404
    assert Invitation.objects.get().status == InvitationStatus.PENDING


def test_owner_invites_a_manager_for_a_location(api, a):
    api.login(a["manager"])
    invitation_id = invite(api, a["location"], role="manager").json()["id"]
    user = User.objects.create_user(PHONE)
    api.login(user)

    assert api.post(f"/api/invitations/{invitation_id}/accept").status_code == 200

    membership = Membership.objects.get(user=user)
    assert membership.role == Role.MANAGER
    assert list(membership.locations.all()) == [a["location"]]
    assert not EmployeeProfile.objects.filter(membership=membership).exists()
    # The new manager can now invite employees to that location.
    assert invite(api, a["location"], "+48602300401").status_code == 201


def test_employee_invited_as_manager_keeps_the_employee_profile(api, a):
    api.login(a["manager"])
    invitation_id = invite(api, a["location"], a["worker"].phone_e164, role="manager").json()["id"]
    api.login(a["worker"])

    assert api.post(f"/api/invitations/{invitation_id}/accept").status_code == 200

    membership = Membership.objects.get(user=a["worker"])
    assert membership.role == Role.MANAGER
    assert membership.employee_profile == a["employee"]


def test_person_can_belong_to_two_companies(api, a, b):
    Invitation.objects.create(location=b["location"], phone_e164=a["worker"].phone_e164)
    api.login(a["worker"])

    api.post(f"/api/invitations/{Invitation.objects.get().id}/accept")

    assert sorted(c["name"] for c in api.get("/api/me").json()["companies"]) == ["A", "B"]


# --- read-only mode -----------------------------------------------------------------------------------


def test_expired_company_cannot_invite_but_invited_people_can_still_answer(api, a, subscribe):
    api.login(a["manager"])
    invitation_id = invite(api, a["location"]).json()["id"]
    subscribe(a["company"], days=-1)

    response = invite(api, a["location"], "+48602300401")
    assert response.status_code == 402
    assert "tylko oglądać" in response.json()["detail"]
    assert api.post(f"/api/invitations/{invitation_id}/cancel").status_code == 402
    assert api.get(f"/api/locations/{a['location'].id}/invitations").status_code == 200

    api.login(User.objects.create_user(PHONE))
    assert api.post(f"/api/invitations/{invitation_id}/accept").status_code == 200


def test_company_without_any_code_is_read_only(api, make_company):
    company = make_company("Bez kodu")
    api.login(company["manager"])

    response = invite(api, company["location"])
    assert response.status_code == 402
    assert "nie ma jeszcze kodu" in response.json()["detail"]
