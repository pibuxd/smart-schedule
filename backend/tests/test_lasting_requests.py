"""Requests "na stałe" (Piotr, 22.11.2026): a lasting request counts in every later period until someone ends it."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.assistant import llm, services
from apps.availability.models import TextRequest
from apps.notifications.models import Notification
from apps.notifications.services import notification_text
from apps.scheduling.models import SchedulePeriod
from apps.scheduling.problem_builder import build_problem
from tests.test_assistant import reading, send_request
from tests.test_assistant import shop as shop
from tests.test_assistant import with_key as with_key

FRIDAYS = {
    "type": "wolne_dni",
    "dates": [],
    "weekdays": [4],
    "level": "wazne",
    "confidence": 0.9,
    "summary": "Wolne w piątki.",
    "lasting": True,
}


@pytest.fixture
def later(shop):
    """The period after `shop["period"]`, collecting availability too."""
    start = shop["period"].end + timedelta(days=1)
    end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return SchedulePeriod.objects.create(
        location=shop["location"], start=start, end=end, availability_requested_at=timezone.now()
    )


def saved(shop, *, lasting=True, month=None, interpretation=None, **fields):
    """An understood request of the shop's worker for its period (or for `month`, with no period)."""
    data = dict(interpretation or FRIDAYS)
    data["lasting"] = lasting and not data.get("dates")
    return TextRequest.objects.create(
        company=shop["company"],
        employee=shop["employee"],
        period=None if month else shop["period"],
        month=month,
        text="Nie pracuję w piątki.",
        status=TextRequest.Status.INTERPRETED,
        interpretation=data,
        lasting=lasting,
        **fields,
    )


def mine(api, shop, period):
    return api.get(f"/api/me/requests?company_id={shop['company'].pk}&period_id={period.pk}").json()


def end_mine(api, shop, row, period, ended=True):
    body = {"company_id": str(shop["company"].pk), "period_id": str(period.pk), "ended": ended}
    return api.post(f"/api/me/requests/{row.pk}/end", body)


def requests_in(period):
    return build_problem([period]).problem.requests


class TestGenerator:
    def test_a_lasting_request_counts_in_later_periods_and_a_plain_one_does_not(self, shop, later):
        lasting = saved(shop)
        saved(shop, lasting=False)
        [request] = requests_in(later)
        assert request.id == str(lasting.pk) and request.location is None  # about the person
        assert request.dates and all(d.weekday() == 4 and later.start <= d <= later.end for d in request.dates)
        assert len(requests_in(shop["period"])) == 2

    def test_later_periods_keep_only_the_lasting_wishes_of_a_message(self, shop, later):
        day = (shop["period"].start + timedelta(days=3)).isoformat()
        only_now = {**FRIDAYS, "weekdays": [5], "summary": "Wolne w soboty.", "lasting": False}
        dated = {**FRIDAYS, "weekdays": [], "dates": [day], "summary": "Wolne."}
        row = saved(shop, interpretation={**FRIDAYS, "more": [only_now, dated]})
        assert len(requests_in(shop["period"])) == 3
        [request] = requests_in(later)
        assert request.id == str(row.pk) and all(d.weekday() == 4 for d in request.dates)

    def test_an_ended_request_counts_until_the_period_it_was_ended_from(self, shop, later):
        saved(shop, ends_from=later.start)
        assert requests_in(shop["period"]) and not requests_in(later)

    def test_a_lasting_request_written_for_a_month_counts_in_the_periods_after_it(self, shop, later):
        row = saved(shop, month=shop["period"].start)
        assert [r.id for r in requests_in(later)] == [str(row.pk)]


class TestAssistant:
    def read(self, api, shop, monkeypatch, answer, text="Nie pracuję w piątki."):
        monkeypatch.setattr(llm, "read_request", lambda text, context, toolbox=None: answer)
        api.login(shop["worker"])
        pk = send_request(api, shop, text).json()["id"]
        services.interpret_request(pk)
        return TextRequest.objects.get(pk=pk)

    def test_a_general_wish_read_as_lasting_is_saved_so(self, api, shop, with_key, monkeypatch):
        row = self.read(api, shop, monkeypatch, reading(lasting=True))
        assert row.status == "interpreted" and row.lasting and row.interpretation["lasting"] is True
        [listed] = mine(api, shop, shop["period"])
        assert listed["lasting"] and listed["can_last"] and listed["carried_from"] is None

    def test_concrete_days_never_last(self, api, shop, with_key, monkeypatch):
        day = (shop["period"].start + timedelta(days=4)).isoformat()
        row = self.read(api, shop, monkeypatch, reading(lasting=True, weekdays=[], dates=[day]))
        assert row.status == "interpreted" and not row.lasting and row.interpretation["lasting"] is False
        assert mine(api, shop, shop["period"])[0]["can_last"] is False

    def test_the_assistant_sees_lasting_requests_from_earlier_months(
        self,
        api,
        shop,
        later,
        with_key,
        monkeypatch,
    ):
        old = saved(shop)
        seen = {}

        def fake(text, context, toolbox=None):
            seen["context"] = context
            return reading(lasting=True, weekdays=[6])

        monkeypatch.setattr(llm, "read_request", fake)
        api.login(shop["worker"])
        body = {"company_id": str(shop["company"].pk), "period_id": str(later.pk), "text": "Jednak soboty."}
        pk = api.post("/api/me/requests", body).json()["id"]
        services.interpret_request(pk)
        assert f'"from_earlier_month": "{shop["period"].start:%Y-%m}"' in seen["context"]
        assert old.text in seen["context"]

    def test_correcting_a_lasting_request_from_an_earlier_month_ends_it_from_this_one(
        self,
        api,
        shop,
        later,
        with_key,
        monkeypatch,
    ):
        old = saved(shop)
        monkeypatch.setattr(
            llm, "read_request", lambda text, context, toolbox=None: reading(lasting=True, replaces_request=1)
        )
        api.login(shop["worker"])
        body = {"company_id": str(shop["company"].pk), "period_id": str(later.pk), "text": "Od teraz soboty."}
        pk = api.post("/api/me/requests", body).json()["id"]
        assert services.interpret_request(pk) == "interpreted"
        old.refresh_from_db()
        new = TextRequest.objects.get(pk=pk)
        # The earlier month keeps it; from this one on only the new request counts.
        assert old.status == "interpreted" and old.ends_from == later.start
        assert old.ended_by == shop["worker"] and new.supersedes == old and new.lasting
        assert [r.id for r in requests_in(later)] == [str(new.pk)]
        assert str(old.pk) in {r.id for r in requests_in(shop["period"])}


class TestEmployee:
    def test_a_lasting_request_from_an_earlier_period_is_listed_as_carried(self, api, shop, later):
        row = saved(shop)
        api.login(shop["worker"])
        [listed] = mine(api, shop, later)
        assert listed["id"] == str(row.pk) and listed["carried_from"] == str(shop["period"].start)
        assert listed["lasting"] and not listed["ended"]
        month = (later.end + timedelta(days=1)).isoformat()
        assert [r["id"] for r in api.get(f"/api/me/requests?company_id={shop['company'].pk}&month={month}").json()] == [
            str(row.pk)
        ]

    def test_the_person_ends_it_from_a_later_period_and_can_bring_it_back(self, api, shop, later):
        row = saved(shop)
        api.login(shop["worker"])
        body = end_mine(api, shop, row, later).json()
        assert body["ended"] and body["ended_by"] == "employee" and body["ends_from"] == str(later.start)
        assert not requests_in(later) and requests_in(shop["period"])
        [listed] = mine(api, shop, later)  # still there, as ended
        assert listed["ended"]
        month = (later.end + timedelta(days=1)).isoformat()
        assert api.get(f"/api/me/requests?company_id={shop['company'].pk}&month={month}").json() == []
        assert end_mine(api, shop, row, later, ended=False).status_code == 200
        row.refresh_from_db()
        assert row.ends_from is None and row.ended_by is None and requests_in(later)

    def test_it_cannot_be_ended_where_it_was_written_or_where_the_period_is_closed(self, api, shop, later):
        row = saved(shop)
        api.login(shop["worker"])
        assert end_mine(api, shop, row, shop["period"]).status_code == 409
        later.status = SchedulePeriod.Status.PUBLISHED
        later.save()
        assert end_mine(api, shop, row, later).status_code == 409
        plain = saved(shop, lasting=False)
        later.status = SchedulePeriod.Status.COLLECTING
        later.save()
        assert end_mine(api, shop, plain, later).status_code == 409

    def test_the_choice_only_this_period_or_lasting(self, api, shop, later):
        row = saved(shop, lasting=False)
        api.login(shop["worker"])
        body = api.patch(f"/api/me/requests/{row.pk}", {"lasting": True}).json()
        assert body["lasting"]
        row.refresh_from_db()
        assert row.interpretation["lasting"] is True and requests_in(later)
        row.ends_from = later.start
        row.save()
        assert api.patch(f"/api/me/requests/{row.pk}", {"lasting": False}).status_code == 200
        row.refresh_from_db()
        assert not row.lasting and row.ends_from is None and not requests_in(later)

    def test_a_request_about_concrete_days_cannot_last(self, api, shop):
        day = (shop["period"].start + timedelta(days=2)).isoformat()
        row = saved(shop, lasting=False, interpretation={**FRIDAYS, "weekdays": [], "dates": [day]})
        api.login(shop["worker"])
        assert api.patch(f"/api/me/requests/{row.pk}", {"lasting": True}).status_code == 409

    def test_the_choice_needs_its_own_period_open(self, api, shop, later):
        row = saved(shop, lasting=False)
        shop["period"].status = SchedulePeriod.Status.PUBLISHED
        shop["period"].save()
        api.login(shop["worker"])
        assert api.patch(f"/api/me/requests/{row.pk}", {"lasting": True}).status_code == 409

    def test_someone_else_cannot_end_my_request(self, api, shop, later, make_company):
        row = saved(shop)
        other = make_company("Inna firma")
        api.login(other["worker"])
        body = {"company_id": str(other["company"].pk), "period_id": str(later.pk)}
        assert api.post(f"/api/me/requests/{row.pk}/end", body).status_code == 404
        body["company_id"] = str(shop["company"].pk)
        assert api.post(f"/api/me/requests/{row.pk}/end", body).status_code in (403, 404)
        row.refresh_from_db()
        assert row.ends_from is None


class TestManager:
    def listed(self, api, period):
        return api.get(f"/api/periods/{period.pk}/requests").json()

    def end(self, api, period, row, ended=True):
        return api.post(f"/api/periods/{period.pk}/requests/{row.pk}/end", {"ended": ended})

    def test_the_manager_sees_a_lasting_request_in_later_periods(self, api, shop, later):
        row = saved(shop)
        api.login(shop["manager"])
        [own] = self.listed(api, shop["period"])
        assert own["lasting"] and own["carried_from"] is None
        [carried] = self.listed(api, later)
        assert carried["id"] == str(row.pk) and carried["carried_from"] == str(shop["period"].start)

    def test_the_manager_ends_it_from_a_period_and_the_person_is_told(self, api, shop, later):
        row = saved(shop)
        api.login(shop["manager"])
        body = self.end(api, later, row).json()
        assert body["ended"] and body["ended_by"] == "manager"
        assert not requests_in(later) and requests_in(shop["period"])
        [listed] = self.listed(api, later)
        assert listed["ended"]
        note = Notification.objects.get(user=shop["worker"], kind="request_ended")
        assert "Nie pracuję w piątki." in notification_text(note.kind, note.payload)
        # The person cannot take back the manager's decision; the manager can.
        api.login(shop["worker"])
        assert end_mine(api, shop, row, later, ended=False).status_code == 409
        api.login(shop["manager"])
        assert self.end(api, later, row, ended=False).status_code == 200
        row.refresh_from_db()
        assert row.ends_from is None

    def test_only_a_carried_lasting_request_can_be_ended(self, api, shop, later):
        lasting, plain = saved(shop), saved(shop, lasting=False)
        api.login(shop["manager"])
        assert self.end(api, shop["period"], lasting).status_code == 409
        assert self.end(api, later, plain).status_code == 409

    def test_another_company_cannot_end_it(self, api, shop, later, make_company):
        row = saved(shop)
        other = make_company("Inna firma")
        api.login(other["manager"])
        assert self.end(api, later, row).status_code in (403, 404)
        row.refresh_from_db()
        assert row.ends_from is None


def test_notification_text_names_the_day():
    text = notification_text("request_ended", {"text": "Nie w piątki.", "from": "2027-01-01", "location_name": "Rynek"})
    assert text == (
        "Kierownik zakończył Twoją prośbę na stałe „Nie w piątki.” (Rynek). Od 1.01.2027 nie liczy się przy układaniu "
        "grafiku."
    )
