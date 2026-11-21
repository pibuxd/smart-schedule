"""Other hours of a published shift: the employee's report (overtime, leaving early), the manager's decision, the
manager's own change, how hours are counted, and who may do what."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.notifications.models import Notification
from apps.notifications.services import notification_text
from apps.scheduling.editing import publish, start_draft
from apps.scheduling.models import Assignment, SchedulePeriod, ScheduleVersion, Shift
from apps.staffing.models import Position
from apps.tenancy.models import Location, Membership, Role
from apps.worktime.models import HoursChange
from tests.conftest import next_phone
from tests.test_generation import add_employee

pytestmark = pytest.mark.django_db

TZ = ZoneInfo("Europe/Warsaw")


def at(day, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TZ)


@pytest.fixture
def bakery(make_company, subscribe):
    """A published schedule around today: Ola and Ewa sell; Rynek is another location of the same company."""
    data = make_company("Piekarnia")
    company, location, seller = data["company"], data["location"], data["position"]
    subscribe(company)
    data["employee"].positions.set([seller])
    ewa = add_employee(company, location, [seller], "Ewa")
    today = timezone.localdate()
    period = SchedulePeriod.objects.create(
        location=location, start=today - timedelta(days=25), end=today + timedelta(days=10), status="published"
    )
    version = ScheduleVersion.objects.create(period=period, number=1, status="published", published_at=timezone.now())
    keys = iter(range(1000))

    def shift(employee, day, start=(6, 0), end=(14, 0), *, version=version, location=location, position=seller):
        start_at = at(day, *start)
        end_at = at(day, *end)
        if end_at <= start_at:
            end_at = at(day + timedelta(days=1), *end)
        row = Shift.objects.create(
            version=version,
            location=location,
            date=day,
            shift_type=data["shift_type"],
            position=position,
            start_at=start_at,
            end_at=end_at,
            slot_key=f"slot-{next(keys)}",
        )
        return Assignment.objects.create(shift=row, employee=employee)

    rynek = Location.objects.create(company=company, name="Rynek")
    other_manager = data["manager"].__class__.objects.create_user(next_phone(), first_name="Teresa")
    membership = Membership.objects.create(company=company, user=other_manager, role=Role.MANAGER)
    membership.locations.add(rynek)
    return {
        **data,
        "ola": data["employee"],
        "ewa": ewa,
        "today": today,
        "period": period,
        "version": version,
        "shift": shift,
        "rynek": rynek,
        "rynek_manager": other_manager,
    }


def user_of(profile):
    return profile.membership.user


def report(api, b, assignment, start, end, reason="", who=None):
    api.login(user_of(who or b["ola"]))
    return api.post(
        "/api/me/hours-changes",
        {"assignment_id": str(assignment.pk), "start_time": start, "end_time": end, "reason": reason},
    )


def hours_of(api, b, day, name):
    """The row of one person in the manager's hours report for the month of `day`."""
    api.login(b["manager"])
    body = api.get(f"/api/reports/hours?company_id={b['company'].id}&month={day:%Y-%m}").json()
    return next((r for r in body["rows"] if r["name"] == name), None)


def notes(kind):
    return list(Notification.objects.filter(kind=kind))


# ----------------------------------------------------------------------------------------------- the employee


def test_employee_reports_overtime_and_the_manager_approves(api, bakery):
    b = bakery
    yesterday = b["today"] - timedelta(days=1)
    row = b["shift"](b["ola"], yesterday)

    sent = report(api, b, row, "06:00", "15:30", "Inwentaryzacja")

    assert sent.status_code == 201, sent.json()
    body = sent.json()
    assert body["status"] == "pending" and body["difference_minutes"] == 90
    assert (body["planned_start_time"], body["planned_end_time"], body["start_time"], body["end_time"]) == (
        "06:00",
        "14:00",
        "06:00",
        "15:30",
    )
    [told] = notes("hours_reported")
    assert told.user_id == b["manager"].pk
    text = notification_text(told.kind, told.payload)
    assert "nadgodziny: +1 h 30 min" in text and "Inwentaryzacja" in text and "„Godziny”" in text
    assert hours_of(api, b, yesterday, "Pracownik")["total"] == 8  # waiting: the plan still counts

    api.login(user_of(b["ola"]))
    mine = api.get(f"/api/me/schedule?company_id={b['company'].id}").json()
    [recent] = [s for s in mine["recent"] if s["id"] == str(row.pk)]
    assert recent["worked"] is None and recent["report"]["end_time"] == "15:30" and recent["can_report"]

    api.login(b["manager"])
    listing = api.get(f"/api/manager/hours-changes?company_id={b['company'].id}").json()
    assert listing["waiting"] == 1 and listing["pending"][0]["assignment_id"] == str(row.pk)
    assert listing["pending"][0]["employee_name"] == "Pracownik" and listing["pending"][0]["reason"] == "Inwentaryzacja"

    approved = api.post(f"/api/hours-changes/{body['id']}/approve")

    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    assert approved.json()["decided_by_name"] == "Menedżer"
    [answer] = notes("hours_approved")
    assert answer.user_id == user_of(b["ola"]).pk
    assert "zatwierdził" in notification_text(answer.kind, answer.payload)
    counted = hours_of(api, b, yesterday, "Pracownik")
    assert (counted["total"], counted["longer"], counted["shorter"]) == (9.5, 1.5, 0)
    listing = api.get(f"/api/manager/hours-changes?company_id={b['company'].id}").json()
    assert listing["waiting"] == 0 and [c["status"] for c in listing["recent"]] == ["approved"]

    api.login(user_of(b["ola"]))
    mine = api.get(f"/api/me/schedule?company_id={b['company'].id}").json()
    [recent] = [s for s in mine["recent"] if s["id"] == str(row.pk)]
    assert recent["report"] is None
    assert recent["worked"]["start_time"] == "06:00" and recent["worked"]["end_time"] == "15:30"
    assert recent["worked"]["hours"] == 9.5 and recent["worked"]["difference_minutes"] == 90
    month = next(m for m in mine["months"] if m["month"] == f"{yesterday:%Y-%m}")
    assert month["hours"] == 9.5
    assert recent["hours"] == 8  # the schedule itself is the plan


def test_leaving_early_while_the_shift_runs_and_a_rejection(api, bakery):
    b = bakery
    now = timezone.now().astimezone(TZ).replace(second=0, microsecond=0)
    if now.hour == 0 and now.minute < 5:
        pytest.skip("too close to midnight for a shift that started today")
    started = max(now - timedelta(hours=2), now.replace(hour=0, minute=0))
    ends = ((started.hour + 8) % 24, started.minute)
    row = b["shift"](b["ola"], started.date(), (started.hour, started.minute), ends)
    leave = f"{now:%H:%M}"

    sent = report(api, b, row, f"{started:%H:%M}", leave, "Źle się czuję")

    assert sent.status_code == 201, sent.json()
    assert sent.json()["difference_minutes"] == -round((started + timedelta(hours=8) - now).total_seconds() / 60)
    api.login(user_of(b["ola"]))
    mine = api.get(f"/api/me/schedule?company_id={b['company'].id}").json()
    [running] = [s for s in mine["shifts"] if s["id"] == str(row.pk)]
    assert running["report"]["end_time"] == leave and running["worked"] is None

    api.login(b["manager"])
    rejected = api.post(f"/api/hours-changes/{sent.json()['id']}/reject")

    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    [answer] = notes("hours_rejected")
    assert "nie zatwierdził" in notification_text(answer.kind, answer.payload)
    assert hours_of(api, b, started.date(), "Pracownik")["total"] == 8
    assert api.post(f"/api/hours-changes/{sent.json()['id']}/approve").status_code == 409  # already decided


def test_a_new_report_replaces_the_waiting_one_and_can_be_taken_back(api, bakery):
    b = bakery
    row = b["shift"](b["ola"], b["today"] - timedelta(days=2))
    first = report(api, b, row, "06:00", "15:00").json()

    assert report(api, b, row, "06:00", "15:00").status_code == 409  # the same report already waits
    second = report(api, b, row, "06:00", "16:00").json()

    assert HoursChange.objects.get(pk=first["id"]).status == "cancelled"
    assert second["status"] == "pending" and len(notes("hours_reported")) == 2
    taken_back = api.post(f"/api/hours-changes/{second['id']}/cancel")
    assert taken_back.status_code == 200 and taken_back.json()["status"] == "cancelled"
    assert api.post(f"/api/hours-changes/{second['id']}/cancel").status_code == 409
    api.login(b["manager"])
    assert api.get(f"/api/manager/hours-changes?company_id={b['company'].id}").json()["waiting"] == 0
    api.login(user_of(b["ewa"]))
    assert api.post(f"/api/hours-changes/{first['id']}/cancel").status_code == 404  # not hers


def test_what_an_employee_cannot_report(api, bakery):
    b = bakery
    today = b["today"]
    yesterday = b["shift"](b["ola"], today - timedelta(days=1))
    b["shift"](b["ola"], today)
    old = b["shift"](b["ola"], today - timedelta(days=20))
    draft = ScheduleVersion.objects.create(period=b["period"], number=2)
    in_draft = b["shift"](b["ola"], today - timedelta(days=3), version=draft)

    assert report(api, b, yesterday, "06:00", "15:00", who=b["ewa"]).status_code == 404  # someone else's
    assert report(api, b, in_draft, "06:00", "15:00").status_code == 409
    too_old = report(api, b, old, "06:00", "15:00")
    assert too_old.status_code == 409 and "14 dni" in too_old.json()["detail"]
    same = report(api, b, yesterday, "06:00", "14:00")
    assert same.status_code == 400 and "te same godziny" in same.json()["detail"]
    clash = report(api, b, yesterday, "13:00", "07:00")  # into the next morning's shift
    assert clash.status_code == 409 and "nachodzą na inną zmianę" in clash.json()["detail"]
    assert report(api, b, yesterday, "25:00", "14:00").status_code == 400
    assert report(api, b, yesterday, "6", "14:00").status_code in (400, 422)
    assert HoursChange.objects.count() == 0


def test_hours_of_a_night_shift_cross_midnight(api, bakery):
    b = bakery
    night = b["shift"](b["ola"], b["today"] - timedelta(days=3), (22, 0), (6, 0))

    early = report(api, b, night, "22:00", "02:00").json()
    assert early["difference_minutes"] == -240 and early["end_time"] == "02:00"
    change = HoursChange.objects.get(pk=early["id"])
    assert change.end_at == at(b["today"] - timedelta(days=2), 2)

    late_start = report(api, b, night, "00:30", "07:00").json()  # came after midnight, stayed an hour longer
    change = HoursChange.objects.get(pk=late_start["id"])
    assert change.start_at == at(b["today"] - timedelta(days=2), 0, 30)
    assert late_start["difference_minutes"] == -90


# ----------------------------------------------------------------------------------------------- the manager


def test_the_manager_sets_hours_alone_and_brings_the_plan_back(api, bakery):
    b = bakery
    day = b["today"] - timedelta(days=1)
    row = b["shift"](b["ola"], day)
    api.login(b["manager"])

    shorter = api.post(
        f"/api/assignments/{row.pk}/hours",
        {"employee_id": str(row.employee_id), "start_time": "06:00", "end_time": "12:00"},
    )

    assert shorter.status_code == 200, shorter.json()
    assert shorter.json()["worked"]["end_time"] == "12:00" and shorter.json()["worked"]["by_manager"]
    [told] = notes("hours_set")
    assert told.user_id == user_of(b["ola"]).pk
    assert "krócej o 2 h" in notification_text(told.kind, told.payload)
    counted = hours_of(api, b, day, "Pracownik")
    assert (counted["total"], counted["shorter"]) == (6, 2)

    longer = api.post(
        f"/api/assignments/{row.pk}/hours",
        {"employee_id": str(row.employee_id), "start_time": "06:00", "end_time": "14:30"},
    )
    assert longer.json()["worked"]["difference_minutes"] == 30
    assert list(HoursChange.objects.order_by("created_at").values_list("status", flat=True)) == [
        "replaced",
        "approved",
    ]
    assert (
        api.post(
            f"/api/assignments/{row.pk}/hours",
            {"employee_id": str(row.employee_id), "start_time": "06:00", "end_time": "14:30"},
        ).status_code
        == 400
    )

    back = api.post(
        f"/api/assignments/{row.pk}/hours",
        {"employee_id": str(row.employee_id), "start_time": "06:00", "end_time": "14:00"},
    )

    assert back.status_code == 200 and back.json()["worked"] is None
    assert not HoursChange.objects.filter(status="approved").exists()
    assert hours_of(api, b, day, "Pracownik")["total"] == 8
    last = Notification.objects.filter(kind="hours_set").order_by("-created_at").first()
    assert "przywrócił godziny z grafiku" in notification_text(last.kind, last.payload)
    assert (
        api.post(
            f"/api/assignments/{row.pk}/hours",
            {"employee_id": str(row.employee_id), "start_time": "06:00", "end_time": "14:00"},
        ).status_code
        == 400
    )


def test_the_managers_change_answers_a_waiting_report(api, bakery):
    b = bakery
    row = b["shift"](b["ola"], b["today"] - timedelta(days=1))
    other = b["shift"](b["ewa"], b["today"] - timedelta(days=1))
    same = report(api, b, row, "06:00", "15:00").json()
    different = report(api, b, other, "06:00", "16:00", who=b["ewa"]).json()
    api.login(b["manager"])

    api.post(
        f"/api/assignments/{row.pk}/hours",
        {"employee_id": str(row.employee_id), "start_time": "06:00", "end_time": "15:00"},
    )
    api.post(
        f"/api/assignments/{other.pk}/hours",
        {"employee_id": str(other.employee_id), "start_time": "06:00", "end_time": "15:00"},
    )

    approved = HoursChange.objects.get(pk=same["id"])
    assert approved.status == "approved" and not approved.by_manager and approved.decided_by == b["manager"]
    assert HoursChange.objects.get(pk=different["id"]).status == "replaced"
    own = HoursChange.objects.get(employee=b["ewa"], status="approved")
    assert own.by_manager and (own.start_at, own.end_at) == (other.shift.start_at, at(other.shift.date, 15))
    assert {n.kind for n in Notification.objects.filter(user=user_of(b["ewa"]))} == {"hours_set"}
    assert api.get(f"/api/manager/hours-changes?company_id={b['company'].id}").json()["waiting"] == 0


def set_hours(api, b, assignment, start, end, reason="", who=None):
    """The manager's own change, from a form that shows the person on the shift now (or `who`)."""
    api.login(b["manager"])
    person = who if who is not None else assignment.employee_id
    return api.post(
        f"/api/assignments/{assignment.pk}/hours",
        {"employee_id": str(person), "start_time": start, "end_time": end, "reason": reason},
    )


def test_a_correction_that_gives_the_shift_to_someone_else_ends_the_report(api, bakery):
    b = bakery
    day = b["today"] - timedelta(days=1)
    row = b["shift"](b["ola"], day)
    # Another day of the same month, so one monthly report shows both.
    approved = b["shift"](b["ola"], day - timedelta(days=1) if day.day > 1 else day + timedelta(days=1))
    waiting = report(api, b, row, "06:00", "15:00").json()
    set_hours(api, b, approved, "06:00", "16:00")
    kept = HoursChange.objects.get(employee=b["ola"], status="approved")

    draft = start_draft(b["version"], b["manager"])
    Assignment.objects.filter(shift__version=draft, employee=b["ola"]).update(employee=b["ewa"])
    publish(draft, b["manager"], notify=False)

    assert HoursChange.objects.get(pk=waiting["id"]).status == "expired"
    assert HoursChange.objects.get(pk=kept.pk).status == "expired"
    body = api.get(f"/api/reports/hours?company_id={b['company'].id}&month={day:%Y-%m}").json()
    assert [(r["name"], r["total"]) for r in body["rows"]] == [("Ewa Nowak", 16)]  # Ola's 10 h no longer count
    assert api.post(f"/api/hours-changes/{waiting['id']}/approve").status_code == 409
    # Ola hears about both: the report that ended and the approved hours that stopped counting.
    told = {n.payload["change_id"]: n for n in notes("hours_lost")}
    assert {n.user_id for n in told.values()} == {user_of(b["ola"]).pk}
    ended = notification_text("hours_lost", told[waiting["id"]].payload)
    assert ended.startswith("Nie masz już tej zmiany w grafiku lokalu") and "zgłoszenie godzin wygasło" in ended
    dropped = notification_text("hours_lost", told[str(kept.pk)].payload)
    assert "zatwierdzone godziny już się nie liczą" in dropped and "nadgodziny: +2 h" in dropped

    # The next correction says nothing again; giving the shift back brings the plan, not the old hours.
    again = start_draft(draft, b["manager"])
    publish(again, b["manager"], notify=False)
    back = start_draft(again, b["manager"])
    Assignment.objects.filter(shift__version=back, shift__slot_key=approved.shift.slot_key).update(employee=b["ola"])
    publish(back, b["manager"], notify=False)
    assert hours_of(api, b, day, "Pracownik")["total"] == 8
    assert len(notes("hours_lost")) == 2


def test_a_change_in_place_ends_the_report_and_says_the_hours_stop_counting(api, bakery):
    b = bakery
    day = b["today"] - timedelta(days=1)
    row = b["shift"](b["ola"], day)
    other = b["shift"](b["ola"], day - timedelta(days=1))
    waiting = report(api, b, row, "06:00", "15:00").json()
    set_hours(api, b, other, "06:00", "12:00")

    moved = api.post(f"/api/assignments/{row.pk}/reassign", {"employee_id": str(b["ewa"].pk), "force": True})

    assert moved.status_code == 200, moved.json()
    assert HoursChange.objects.get(pk=waiting["id"]).status == "expired"
    assert api.get(f"/api/manager/hours-changes?company_id={b['company'].id}").json()["waiting"] == 0
    [ended] = notes("hours_lost")
    assert ended.user_id == user_of(b["ola"]).pk and ended.payload["approved"] is False

    swapped = api.post("/api/shift-swaps", {"first_id": str(other.pk), "second_id": str(row.pk), "force": True})

    assert swapped.status_code == 204
    last = Notification.objects.filter(kind="hours_lost").order_by("-created_at").first()
    assert last.user_id == user_of(b["ola"]).pk and last.payload["approved"] is True
    assert "krócej o 2 h" in notification_text(last.kind, last.payload)
    assert HoursChange.objects.get(employee=b["ola"], by_manager=True).status == "expired"
    assert hours_of(api, b, day, "Pracownik")["total"] == 8  # Ola now has Ewa's old shift, at its planned hours


def test_old_hours_do_not_come_back_with_the_shift(api, bakery):
    """Ola's approved 06:00–16:00 must not count again after her next shift was moved to start at 14:00."""
    b = bakery
    day = b["today"] - timedelta(days=1)
    first = b["shift"](b["ola"], day)
    second = b["shift"](b["ola"], day, (16, 0), (22, 0))
    set_hours(api, b, first, "06:00", "16:00")
    assert api.post(f"/api/assignments/{first.pk}/reassign", {"employee_id": str(b["ewa"].pk)}).status_code == 200
    assert set_hours(api, b, second, "14:00", "22:00").status_code == 200

    back = api.post(f"/api/assignments/{first.pk}/reassign", {"employee_id": str(b["ola"].pk)})

    assert back.status_code == 200, back.json()
    counted = hours_of(api, b, day, "Pracownik")
    assert (counted["total"], counted["longer"]) == (16, 2)  # 06:00–14:00 and 14:00–22:00, no hour twice
    assert not HoursChange.objects.filter(employee=b["ola"], slot_key=first.shift.slot_key, status="approved").exists()


def test_taking_a_shift_that_approved_hours_run_into(api, bakery):
    b = bakery
    day = b["today"] - timedelta(days=1)
    mine = b["shift"](b["ola"], day)
    late = b["shift"](b["ewa"], day, (14, 0), (22, 0))
    set_hours(api, b, mine, "06:00", "16:00")
    body = {"employee_id": str(b["ola"].pk)}

    candidates = api.get(f"/api/assignments/{late.pk}/handover-candidates").json()
    refused = api.post(f"/api/assignments/{late.pk}/reassign", body)

    [ola] = [c for c in candidates if c["employee_id"] == str(b["ola"].pk)]
    assert any("Zatwierdzone godziny tej osoby nachodzą" in p for p in ola["problems"])
    assert refused.status_code == 409 and "06:00–16:00" in refused.json()["detail"]

    forced = api.post(f"/api/assignments/{late.pk}/reassign", {**body, "force": True})

    assert forced.status_code == 200
    assert hours_of(api, b, day, "Pracownik")["total"] == 16  # her 06:00–16:00 gave way to the plan
    last = Notification.objects.filter(kind="hours_lost").latest("created_at")
    assert last.payload["overlap"] and "nachodzą na inną Twoją zmianę" in notification_text(last.kind, last.payload)


def test_a_correction_that_runs_into_approved_hours_ends_them(api, bakery):
    b = bakery
    day = b["today"] - timedelta(days=1)
    mine = b["shift"](b["ola"], day)
    b["shift"](b["ewa"], day, (14, 0), (22, 0))
    set_hours(api, b, mine, "06:00", "16:00")

    draft = start_draft(b["version"], b["manager"])
    Assignment.objects.filter(shift__version=draft, employee=b["ewa"]).update(employee=b["ola"])
    publish(draft, b["manager"], notify=False)

    assert HoursChange.objects.get(employee=b["ola"]).status == "expired"
    assert hours_of(api, b, day, "Pracownik")["total"] == 16
    [told] = notes("hours_lost")
    assert told.payload["overlap"] is True


def test_the_form_changes_only_the_person_it_shows(api, bakery):
    b = bakery
    row = b["shift"](b["ola"], b["today"] - timedelta(days=1))
    api.login(b["manager"])
    api.post(f"/api/assignments/{row.pk}/reassign", {"employee_id": str(b["ewa"].pk), "force": True})

    stale = set_hours(api, b, row, "06:00", "12:00", who=b["ola"].pk)

    assert stale.status_code == 409 and "inna osoba" in stale.json()["detail"]
    assert not HoursChange.objects.exists() and not notes("hours_set")
    missing = api.post(f"/api/assignments/{row.pk}/hours", {"start_time": "06:00", "end_time": "12:00"})
    assert missing.status_code == 422


def test_bringing_the_plan_back_is_checked_for_overlaps(api, bakery):
    b = bakery
    day = b["today"] - timedelta(days=1)
    first = b["shift"](b["ola"], day)
    second = b["shift"](b["ola"], day, (14, 0), (20, 0))
    assert set_hours(api, b, first, "06:00", "12:00").status_code == 200
    assert set_hours(api, b, second, "12:00", "20:00").status_code == 200

    back = set_hours(api, b, first, "06:00", "14:00")

    assert back.status_code == 409 and "nachodzą na inną zmianę" in back.json()["detail"]
    assert hours_of(api, b, day, "Pracownik")["total"] == 14


def test_the_24_hour_limit_counts_a_change_of_the_clock(api, bakery):
    """25 October 2026: clocks in Warsaw go back an hour, so 12:00 to 12:00 is 25 hours."""
    b = bakery
    seller = Position.objects.create(location=b["rynek"], name="Sprzedawca")
    period = SchedulePeriod.objects.create(location=b["rynek"], start=date(2026, 10, 19), end=date(2026, 10, 25))
    version = ScheduleVersion.objects.create(period=period, number=1, status="published")
    row = b["shift"](
        b["ola"], date(2026, 10, 24), (12, 0), (20, 0), version=version, location=b["rynek"], position=seller
    )
    api.login(b["rynek_manager"])
    body = {"employee_id": str(b["ola"].pk), "start_time": "12:00"}

    too_long = api.post(f"/api/assignments/{row.pk}/hours", {**body, "end_time": "12:00"})
    longest = api.post(f"/api/assignments/{row.pk}/hours", {**body, "end_time": "11:00"})

    assert too_long.status_code == 400 and "24 godziny" in too_long.json()["detail"]
    assert longest.status_code == 200, longest.json()
    assert longest.json()["worked"]["hours"] == 24
    report_body = api.get(f"/api/reports/hours?company_id={b['company'].id}&month=2026-10").json()
    assert report_body["rows"][0]["total"] == 24


def test_sums_are_rounded_once(api, bakery, monkeypatch):
    b = bakery
    # The 1st of this month: yesterday's shift is in "Minione zmiany" and its month gets a sum too.
    first_day = b["today"].replace(day=1)
    monkeypatch.setattr(timezone, "localdate", lambda *args, **kwargs: first_day)
    for back in (1, 2, 3):
        b["shift"](b["ola"], first_day - timedelta(days=back), (6, 0), (14, 20))
    month = f"{first_day - timedelta(days=1):%Y-%m}"

    assert hours_of(api, b, first_day - timedelta(days=1), "Pracownik")["total"] == 25

    api.login(user_of(b["ola"]))
    mine = api.get(f"/api/me/schedule?company_id={b['company'].id}").json()
    assert {m["month"]: m["hours"] for m in mine["months"]}[month] == 25
    assert len(mine["recent"]) == 3


def test_the_grid_and_the_list_of_published_shifts_show_the_hours(api, bakery):
    b = bakery
    row = b["shift"](b["ola"], b["today"] - timedelta(days=1))
    other = b["shift"](b["ewa"], b["today"] - timedelta(days=1))
    report(api, b, other, "06:00", "15:00", who=b["ewa"])
    api.login(b["manager"])
    api.post(
        f"/api/assignments/{row.pk}/hours",
        {"employee_id": str(row.employee_id), "start_time": "07:00", "end_time": "14:00"},
    )

    grid = {s["assignment_id"]: s for s in api.get(f"/api/versions/{b['version'].pk}").json()["shifts"]}
    assert grid[str(row.pk)]["worked"]["start_time"] == "07:00" and grid[str(row.pk)]["hours_report"] is None
    assert grid[str(other.pk)]["worked"] is None and grid[str(other.pk)]["hours_report"]["end_time"] == "15:00"
    listed = {s["id"]: s for s in api.get(f"/api/locations/{b['location'].pk}/handover-shifts").json()}
    assert listed[str(row.pk)]["worked"]["difference_minutes"] == -60
    assert listed[str(other.pk)]["hours_report"]["difference_minutes"] == 60


def test_csv_has_overtime_and_shorter_columns(api, bakery):
    b = bakery
    day = b["today"] - timedelta(days=1)
    row = b["shift"](b["ola"], day)
    api.login(b["manager"])
    api.post(
        f"/api/assignments/{row.pk}/hours",
        {"employee_id": str(row.employee_id), "start_time": "06:00", "end_time": "15:15"},
    )

    text = api.get(f"/api/reports/hours.csv?company_id={b['company'].id}&month={day:%Y-%m}").content.decode("utf-8-sig")

    header, line = text.strip().splitlines()
    assert header.endswith(";Razem;Nadgodziny (ponad grafik);Krótsze zmiany;Uwagi")
    assert line.split(";")[-4:] == ["9,25", "1,25", "0,00", ""]


# ----------------------------------------------------------------------------------------------- who may do what


def test_only_the_managers_of_the_location_decide(api, bakery, subscribe, make_company):
    b = bakery
    row = b["shift"](b["ola"], b["today"] - timedelta(days=1))
    change = report(api, b, row, "06:00", "15:00").json()

    api.login(b["rynek_manager"])  # manages another location of the same company
    assert api.post(f"/api/hours-changes/{change['id']}/approve").status_code == 403
    assert (
        api.post(
            f"/api/assignments/{row.pk}/hours",
            {"employee_id": str(row.employee_id), "start_time": "06:00", "end_time": "12:00"},
        ).status_code
        == 403
    )
    assert api.get(f"/api/manager/hours-changes?company_id={b['company'].id}").json()["pending"] == []
    api.login(user_of(b["ewa"]))  # an employee
    assert api.post(f"/api/hours-changes/{change['id']}/approve").status_code == 403
    assert api.get(f"/api/manager/hours-changes?company_id={b['company'].id}").status_code == 403

    other = make_company("Inna")
    api.login(other["manager"])  # another company: nothing exists
    assert api.post(f"/api/hours-changes/{change['id']}/approve").status_code == 404
    assert api.post(f"/api/hours-changes/{change['id']}/cancel").status_code == 404
    assert (
        api.post(
            f"/api/assignments/{row.pk}/hours",
            {"employee_id": str(row.employee_id), "start_time": "06:00", "end_time": "12:00"},
        ).status_code
        == 404
    )
    assert api.get(f"/api/manager/hours-changes?company_id={b['company'].id}").status_code == 404
    api.login(other["worker"])
    sent = api.post("/api/me/hours-changes", {"assignment_id": str(row.pk), "start_time": "06:00", "end_time": "15:00"})
    assert sent.status_code == 404
    assert HoursChange.objects.get().status == "pending"


def test_read_only_company_cannot_change_hours(api, bakery, subscribe):
    b = bakery
    row = b["shift"](b["ola"], b["today"] - timedelta(days=1))
    change = report(api, b, row, "06:00", "15:00").json()
    subscribe(b["company"], days=-1)

    assert report(api, b, row, "06:00", "16:00").status_code == 402
    assert api.post(f"/api/hours-changes/{change['id']}/cancel").status_code == 402
    api.login(b["manager"])
    assert api.post(f"/api/hours-changes/{change['id']}/approve").status_code == 402
    assert (
        api.post(
            f"/api/assignments/{row.pk}/hours",
            {"employee_id": str(row.employee_id), "start_time": "06:00", "end_time": "12:00"},
        ).status_code
        == 402
    )
    assert api.get(f"/api/manager/hours-changes?company_id={b['company'].id}").status_code == 200


def test_an_empty_shift_and_another_location_shift(api, bakery):
    b = bakery
    rynek_seller = Position.objects.create(location=b["rynek"], name="Sprzedawca")
    empty = b["shift"](None, b["today"] - timedelta(days=1))
    api.login(b["manager"])
    nobody = api.post(
        f"/api/assignments/{empty.pk}/hours",
        {"employee_id": str(b["ola"].pk), "start_time": "06:00", "end_time": "12:00"},
    )
    assert nobody.status_code == 409 and "nikogo" in nobody.json()["detail"]

    period = SchedulePeriod.objects.create(location=b["rynek"], start=b["today"] - timedelta(days=5), end=b["today"])
    version = ScheduleVersion.objects.create(period=period, number=1, status="published")
    yesterday = b["today"] - timedelta(days=1)
    away = b["shift"](
        b["ola"], yesterday, (15, 0), (20, 0), version=version, location=b["rynek"], position=rynek_seller
    )
    here = b["shift"](b["ola"], b["today"] - timedelta(days=1))
    clash = report(api, b, here, "06:00", "16:00")  # runs into her afternoon in Rynek
    assert clash.status_code == 409 and "Rynek" in clash.json()["detail"]
    assert report(api, b, away, "13:30", "20:00").status_code == 409  # starts before her morning ends
    sent = report(api, b, away, "15:00", "21:00")
    assert sent.status_code == 201 and sent.json()["location_name"] == "Rynek"
    # The owner and the manager of Rynek decide about it.
    assert {n.user_id for n in notes("hours_reported")} == {b["manager"].pk, b["rynek_manager"].pk}


def test_older_shifts_can_be_picked_by_month(api, bakery):
    b = bakery
    old = b["shift"](b["ola"], b["today"] - timedelta(days=20))
    api.login(b["manager"])
    url = f"/api/locations/{b['location'].pk}/handover-shifts"

    default = [s["id"] for s in api.get(url).json()]
    by_month = [s["id"] for s in api.get(f"{url}?month={old.shift.date:%Y-%m}").json()]

    assert str(old.pk) not in default and str(old.pk) in by_month
    assert api.get(f"{url}?month=2026-13").status_code == 400
    assert set_hours(api, b, old, "06:00", "12:00").status_code == 200  # the manager has no 14-day limit
