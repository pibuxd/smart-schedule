"""Generating a schedule: reading the database into a Problem, the API, the worker job, limits and stability."""

from datetime import date, time, timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.utils import timezone
from procrastinate.contrib.django import app
from procrastinate.contrib.django.models import ProcrastinateJob

from apps.accounts.models import User
from apps.availability.models import AvailabilityDay, TextRequest
from apps.billing.models import GenerationUsage
from apps.rules.models import RuleSetting, WeightProfile
from apps.scheduling.generation import fail_stale_runs, request_generation, run_generation
from apps.scheduling.models import Assignment, GenerationRun, SchedulePeriod, ScheduleVersion, Shift
from apps.scheduling.problem_builder import BuildError, build_problem, slot_key
from apps.staffing.models import Contract, EmployeeProfile, ShiftType, StaffingException, StaffingRule
from apps.tenancy.models import LocationGroup, Membership
from engine.problem import RequestType
from engine.validator import validate
from tests.conftest import next_phone

MON = date(2026, 12, 7)  # a Monday, in the future for these tests
TODAY = date(2026, 11, 12)
FAST = {"time_limit_s": 3, "workers": 4}


def add_employee(company, location, positions, first="Ola", **fields):
    user = User.objects.create_user(next_phone(), first_name=first, last_name="Nowak")
    membership = Membership.objects.create(company=company, user=user)
    profile = EmployeeProfile.objects.create(membership=membership, home_location=location, **fields)
    profile.positions.set(positions)
    return profile


@pytest.fixture
def shop(make_company, subscribe):
    """One location: mornings 06–14 (2 sellers Mon–Fri, 1 at weekends), 3 sellers, a one-week period."""
    data = make_company("Piekarnia")
    company, location, seller, morning = data["company"], data["location"], data["position"], data["shift_type"]
    subscribe(company)
    data["employee"].positions.set([seller])
    people = [
        data["employee"],
        add_employee(company, location, [seller], "Ewa"),
        add_employee(company, location, [seller], "Jan"),
    ]
    StaffingRule.objects.bulk_create(
        StaffingRule(
            company=company, location=location, weekday=d, shift_type=morning, position=seller, count=2 if d < 5 else 1
        )
        for d in range(7)
    )
    period = SchedulePeriod.objects.create(location=location, start=MON, end=MON + timedelta(days=6))
    return {**data, "people": people, "period": period}


def generate(api, *periods):
    return api.post("/api/periods/generate", {"period_ids": [str(p.id) for p in periods]})


# ----------------------------------------------------------------- reading the database


@pytest.mark.django_db
def test_slots_come_from_staffing_with_exceptions_and_flexible_hours(shop):
    company, location, seller = shop["company"], shop["location"], shop["position"]
    deliveries = ShiftType.objects.create(location=location, name="Dostawy", kind=ShiftType.Kind.FLEXIBLE)
    StaffingRule.objects.create(
        location=location,
        weekday=1,
        shift_type=deliveries,
        position=seller,
        count=1,
        start_time=time(4),
        end_time=time(9),
    )
    StaffingException.objects.create(
        location=location, date=MON, shift_type=shop["shift_type"], position=seller, count=0
    )
    StaffingException.objects.create(
        location=location,
        date=MON + timedelta(days=3),
        shift_type=shop["shift_type"],
        position=seller,
        count=3,
        start_time=time(7),
        end_time=time(15),
    )

    built = build_problem([shop["period"]], today=TODAY)
    slots = {s.id: s for s in built.problem.slots}

    assert not any(s.date == MON for s in slots.values())  # closed on Monday (count 0)
    tuesday = [s for s in slots.values() if s.date == MON + timedelta(days=1)]
    assert len(tuesday) == 3  # 2 mornings + 1 delivery 04–09
    delivery = slots[slot_key(MON + timedelta(days=1), str(deliveries.id), str(seller.id), 1)]
    assert (delivery.start.hour, delivery.end.hour) == (4, 9)
    thursday = [s for s in slots.values() if s.date == MON + timedelta(days=3)]
    assert len(thursday) == 3 and {(s.start.hour, s.end.hour) for s in thursday} == {(7, 15)}
    assert len(slots) == 3 + 2 + 3 + 2 + 1 + 1  # Tue 2+1, Wed 2, Thu 3, Fri 2, Sat 1, Sun 1
    assert {s.location for s in slots.values()} == {str(location.id)}
    assert company.id == shop["period"].company_id


@pytest.mark.django_db
def test_flexible_shift_without_hours_stops_the_run_instead_of_hiding_it(shop):
    nameless = ShiftType.objects.create(location=shop["location"], name="Bez godzin", kind=ShiftType.Kind.FLEXIBLE)
    StaffingRule.objects.create(
        location=shop["location"], weekday=2, shift_type=nameless, position=shop["position"], count=1
    )
    run = run_generation(request_generation(_ctx(shop), [shop["period"]])[0].pk, **FAST)

    assert run.status == GenerationRun.Status.FAILED
    assert "„Bez godzin”" in run.error and "Uzupełnij godziny" in run.error
    assert GenerationUsage.objects.get(company=shop["company"]).count == 0


@pytest.mark.django_db
def test_rules_of_the_group_with_location_changes_in_one_ordered_list(shop):
    company, location = shop["company"], shop["location"]
    group = LocationGroup.objects.create(company=company, name="Grupa")
    location.group = group
    location.save()
    for position, code in enumerate(["min_rest_between_shifts", "target_hours", "fair_weekends"], start=1):
        RuleSetting.objects.create(group=group, rule_code=code, position=position)
    RuleSetting.objects.create(location=location, rule_code="target_hours", position=1, is_hard=True)
    RuleSetting.objects.create(location=location, rule_code="fair_weekends", position=3, enabled=False)
    RuleSetting.objects.create(location=location, rule_code="max_shifts_per_week", position=2, params={"shifts": 4})
    WeightProfile.objects.create(group=group, manager_share=Decimal("0.85"))

    problem = build_problem([shop["period"]], today=TODAY).problem

    rules = [(r.code, r.rank, r.hard) for r in problem.rules_for(str(location.id))]
    assert rules == [
        ("target_hours", 1, True),  # the location's own setting, first
        ("min_rest_between_shifts", 2, False),
        ("max_shifts_per_week", 3, False),
    ]
    assert problem.weights.manager_share == pytest.approx(0.85)


@pytest.mark.django_db
def test_people_availability_and_requests_are_read(shop):
    anna, ewa, jan = shop["people"]
    jan.is_active = False
    jan.save()
    AvailabilityDay.objects.create(employee=anna, date=MON, state="cannot")
    period = shop["period"]
    base = {"employee": anna, "period": period}
    TextRequest.objects.create(
        **base,
        text="Nie z Ewą",
        status=TextRequest.Status.INTERPRETED,
        interpretation={"type": "unikaj_osoby", "subject_employee": str(ewa.id), "dates": [], "level": "wazne"},
        manager_priority=TextRequest.ManagerPriority.HIGHER,
    )
    TextRequest.objects.create(**base, text="Coś niejasnego", status=TextRequest.Status.NEEDS_MANAGER)
    TextRequest.objects.create(**base, text="Odrzucona", status=TextRequest.Status.REJECTED, manager_rejected=True)
    TextRequest.objects.create(
        **base,
        text="Nie z Janem",
        status=TextRequest.Status.INTERPRETED,
        interpretation={"type": "unikaj_osoby", "subject_employee": str(jan.id), "level": "wazne"},
    )

    problem = build_problem([period], today=TODAY).problem

    assert {e.id for e in problem.employees} == {str(anna.id), str(ewa.id)}  # Jan is switched off
    assert [(a.employee, a.date, a.state) for a in problem.availability] == [(str(anna.id), MON, "cannot")]
    kinds = sorted((r.type, r.manager_priority) for r in problem.requests)
    assert kinds == [
        (RequestType.AVOID_PERSON, "higher"),
        (RequestType.OTHER, "normal"),  # unclear: left to the manager
        (RequestType.OTHER, "normal"),  # about someone not in the schedule
    ]


@pytest.mark.django_db
def test_published_version_pins_frozen_days_and_other_periods(shop):
    anna, ewa, _ = shop["people"]
    period = shop["period"]
    built = build_problem([period], today=TODAY)
    version = ScheduleVersion.objects.create(period=period, number=1, status=ScheduleVersion.Status.PUBLISHED)
    for i, slot in enumerate(sorted(built.problem.slots, key=lambda s: s.id)):
        source = built.sources[slot.id]
        shift = Shift.objects.create(
            version=version,
            location_id=source.location_id,
            date=slot.date,
            shift_type_id=source.shift_type_id,
            position_id=source.position_id,
            start_at=slot.start,
            end_at=slot.end,
            slot_key=slot.id,
        )
        Assignment.objects.create(shift=shift, employee=anna if i % 2 else ewa, pinned=i == 0)
    # The previous week, published: Anna worked late on Sunday.
    previous = SchedulePeriod.objects.create(
        location=shop["location"], start=MON - timedelta(days=7), end=MON - timedelta(days=1)
    )
    old = ScheduleVersion.objects.create(period=previous, number=1, status=ScheduleVersion.Status.PUBLISHED)
    sunday = MON - timedelta(days=1)
    shift = Shift.objects.create(
        version=old,
        location=shop["location"],
        date=sunday,
        shift_type=shop["shift_type"],
        position=shop["position"],
        start_at=timezone.make_aware(timezone.datetime.combine(sunday, time(14))),
        end_at=timezone.make_aware(timezone.datetime.combine(sunday, time(22))),
        slot_key="old",
    )
    Assignment.objects.create(shift=shift, employee=anna)

    # Three days into the period: Monday–Wednesday are frozen and keep the published shifts.
    problem = build_problem([period], today=MON + timedelta(days=3)).problem

    assert len(problem.published) == len(built.problem.slots)
    assert len(problem.pinned) == 1
    assert problem.frozen_before == MON + timedelta(days=3)
    assert [(e.employee, e.date) for e in problem.external_shifts] == [(str(anna.id), sunday)]


@pytest.mark.django_db
def test_periods_of_different_dates_or_groups_are_refused(shop, make_company):
    other = SchedulePeriod.objects.create(
        location=make_company("B")["location"], start=MON, end=MON + timedelta(days=6)
    )
    with pytest.raises(BuildError):
        build_problem([shop["period"], other])


# ----------------------------------------------------------------- the API


@pytest.mark.django_db
def test_generate_saves_a_run_and_defers_the_job_together(api, shop):
    api.login(shop["manager"])

    response = generate(api, shop["period"])

    assert response.status_code == 202, response.json()
    [body] = response.json()
    assert body["status"] == "queued" and body["versions"] == []
    run = GenerationRun.objects.get(pk=body["id"])
    job = ProcrastinateJob.objects.get(task_name="scheduling.solve_schedule")
    assert job.queue_name == "solver" and job.args == {"run_id": str(run.pk)}
    assert GenerationUsage.objects.get(company=shop["company"]).count == 1

    again = generate(api, shop["period"])
    assert again.status_code == 409


@pytest.mark.django_db
def test_monthly_generation_limit(api, shop, settings):
    settings.GENERATION_MONTHLY_LIMIT = 1
    api.login(shop["manager"])
    assert generate(api, shop["period"]).status_code == 202
    GenerationRun.objects.update(status=GenerationRun.Status.SUCCEEDED)

    response = generate(api, shop["period"])

    assert response.status_code == 429
    assert "limit to 1 ułożeń" in response.json()["detail"]


@pytest.mark.django_db
def test_read_only_company_and_employees_cannot_generate(api, shop, subscribe):
    api.login(shop["worker"])
    assert generate(api, shop["period"]).status_code == 403
    subscribe(shop["company"], days=-1)
    api.login(shop["manager"])
    assert generate(api, shop["period"]).status_code == 402
    assert not GenerationRun.objects.exists()


@pytest.mark.django_db
def test_other_company_gets_404_on_every_scheduling_endpoint(api, shop, make_company):
    run = request_generation(_ctx(shop), [shop["period"]])[0]
    stranger = make_company("Obca")
    api.login(stranger["manager"])

    assert generate(api, shop["period"]).status_code == 404
    assert api.get(f"/api/generation-runs/{run.pk}").status_code == 404
    assert api.get(f"/api/locations/{shop['location'].id}/periods").status_code == 404
    response = api.post(f"/api/locations/{shop['location'].id}/periods", {"start": "2027-01-04", "end": "2027-01-10"})
    assert response.status_code == 404
    # Mixing a period of another company into a request is a 404 too.
    own = SchedulePeriod.objects.create(location=stranger["location"], start=MON, end=MON + timedelta(days=6))
    assert generate(api, own, shop["period"]).status_code == 404


@pytest.mark.django_db
def test_create_and_list_periods(api, shop):
    api.login(shop["manager"])
    url = f"/api/locations/{shop['location'].id}/periods"

    created = api.post(url, {"start": "2027-01-04", "end": "2027-01-10"})
    overlapping = api.post(url, {"start": "2027-01-10", "end": "2027-01-16"})
    backwards = api.post(url, {"start": "2027-01-10", "end": "2027-01-04"})
    listed = api.get(url).json()

    assert created.status_code == 201 and created.json()["status"] == "collecting"
    assert overlapping.status_code == 409
    assert backwards.status_code == 400
    assert [p["start"] for p in listed] == ["2027-01-04", str(MON)]


def _ctx(data):
    from apps.tenancy.context import TenantContext

    membership = Membership.objects.get(user=data["manager"], company=data["company"])
    return TenantContext(company=data["company"], membership=membership)


# ----------------------------------------------------------------- running a generation


@pytest.mark.django_db(transaction=True)
def test_worker_arranges_the_schedule_and_saves_a_draft_version(api, shop, settings):
    settings.SOLVER_TIME_LIMIT_S = 3
    settings.SOLVER_WORKERS = 4
    api.login(shop["manager"])
    with transaction.atomic():
        run_id = generate(api, shop["period"]).json()[0]["id"]

    worker_app = app.with_connector(app.connector.get_worker_connector())
    worker_app.run_worker(queues=["solver"], wait=False, install_signal_handlers=False, listen_notify=False)

    body = api.get(f"/api/generation-runs/{run_id}").json()
    assert body["status"] == "succeeded", body["error"]
    assert body["solver_status"] in ("optimal", "feasible")
    [version] = body["versions"]
    assert version["number"] == 1 and version["is_complete"]
    assert version["scores"]["holes"] == 0 and version["scores"]["slots"] == 12
    assert version["scores"]["hard_violations"] == 0
    saved = ScheduleVersion.objects.get(pk=version["id"])
    assert saved.status == ScheduleVersion.Status.DRAFT
    assert Assignment.objects.filter(shift__version=saved, employee__isnull=False).count() == 12
    shop["period"].refresh_from_db()
    assert shop["period"].status == SchedulePeriod.Status.DRAFT
    periods = api.get(f"/api/locations/{shop['location'].id}/periods").json()
    assert periods[0]["latest_version_id"] == version["id"]


@pytest.mark.django_db
def test_failed_generation_gives_the_generation_back(shop):
    StaffingRule.objects.all().delete()
    run = request_generation(_ctx(shop), [shop["period"]])[0]
    assert GenerationUsage.objects.get(company=shop["company"]).count == 1

    run = run_generation(run.pk, **FAST)

    assert run.status == GenerationRun.Status.FAILED
    assert "nie ma żadnych zmian" in run.error
    assert GenerationUsage.objects.get(company=shop["company"]).count == 0
    assert run_generation(run.pk, **FAST).status == GenerationRun.Status.FAILED  # a second run does nothing


@pytest.mark.django_db
def test_impossible_no_exceptions_rule_fails_with_an_explanation(shop):
    anna = shop["people"][0]
    anna.target_hours_month = 160  # 37 h in this week, but there are at most 7 mornings of 8 h minus "cannot"
    anna.save()
    AvailabilityDay.objects.bulk_create(
        AvailabilityDay(company=shop["company"], employee=anna, date=MON + timedelta(days=d), state="cannot")
        for d in range(4)
    )
    RuleSetting.objects.create(location=shop["location"], rule_code="target_hours", position=1, is_hard=True)
    run = request_generation(_ctx(shop), [shop["period"]])[0]

    run = run_generation(run.pk, **FAST)

    assert run.status == GenerationRun.Status.FAILED
    assert run.solver_status == GenerationRun.SolverStatus.INFEASIBLE
    assert "„Cel godzin”" in run.error
    assert not ScheduleVersion.objects.exists()


@pytest.mark.django_db
def test_holes_when_people_are_missing(shop):
    for person in shop["people"][1:]:
        person.positions.clear()
    run = run_generation(request_generation(_ctx(shop), [shop["period"]])[0].pk, **FAST)

    version = run.versions.get()
    assert run.status == GenerationRun.Status.SUCCEEDED
    assert not version.is_complete
    assert version.scores["holes"] == 12 - 7  # one person, at most one shift a day
    assert Assignment.objects.filter(shift__version=version, employee__isnull=True).count() == 5


@pytest.mark.django_db
def test_stale_runs_are_failed(shop):
    run = request_generation(_ctx(shop), [shop["period"]])[0]
    GenerationRun.objects.filter(pk=run.pk).update(
        status=GenerationRun.Status.RUNNING, started_at=timezone.now() - timedelta(hours=1)
    )

    assert fail_stale_runs() == 1

    run.refresh_from_db()
    assert run.status == GenerationRun.Status.FAILED
    assert GenerationUsage.objects.get(company=shop["company"]).count == 0


@pytest.mark.django_db
def test_regenerating_a_published_schedule_mid_period_keeps_the_past_and_most_of_the_rest(shop):
    period = shop["period"]
    first = run_generation(request_generation(_ctx(shop), [period])[0].pk, **FAST).versions.get()
    ScheduleVersion.objects.filter(pk=first.pk).update(status=ScheduleVersion.Status.PUBLISHED)
    before = dict(Assignment.objects.filter(shift__version=first).values_list("shift__slot_key", "employee"))
    # Ewa cannot work on Friday any more; we are on Wednesday.
    ewa = shop["people"][1]
    AvailabilityDay.objects.create(employee=ewa, date=MON + timedelta(days=4), state="cannot")

    run = run_generation(request_generation(_ctx(shop), [period])[0].pk, today=MON + timedelta(days=2), **FAST)

    second = run.versions.get()
    after = dict(Assignment.objects.filter(shift__version=second).values_list("shift__slot_key", "employee"))
    assert second.number == 2
    assert set(after) == set(before)
    past = [k for k in before if date.fromisoformat(k[:10]) < MON + timedelta(days=2)]
    assert all(after[k] == before[k] for k in past)
    changed = [k for k in before if after[k] != before[k]]
    assert len(changed) <= 2  # Ewa's Friday shift and at most one swap
    assert second.scores["stability_changes"] == len(changed)


@pytest.mark.django_db
def test_arrange_all_runs_each_demo_bakery_on_its_own():
    from apps.core.demo_data import BAKERY_COMPANY_ID, create_demo_data
    from apps.tenancy.context import TenantContext

    create_demo_data(today=TODAY)
    periods = list(SchedulePeriod.objects.filter(company_id=BAKERY_COMPANY_ID).select_related("location"))
    manager = Membership.objects.get(company_id=BAKERY_COMPANY_ID, role="owner")

    runs = request_generation(TenantContext(company=manager.company, membership=manager), periods)

    assert len(runs) == 4 and GenerationUsage.objects.get(company_id=BAKERY_COMPANY_ID).count == 4
    worked = set()
    for run in runs:
        run = run_generation(run.pk, time_limit_s=8, workers=4, today=TODAY)
        assert run.status == GenerationRun.Status.SUCCEEDED, run.error
        [period] = run.periods.all()
        assert run.location_id == period.location_id and run.group_id is None
        version = run.versions.get()
        schedule = {
            key: str(employee) if employee else None
            for key, employee in Assignment.objects.filter(shift__version=version).values_list(
                "shift__slot_key", "employee"
            )
        }
        report = validate(build_problem([period], today=TODAY).problem, schedule)
        assert report.ok
        worked |= {e for e, hours in report.hours.items() if hours > 0}
    # Employment-contract people (one shift lead and one baker per bakery) are in the schedule.
    employment = EmployeeProfile.objects.filter(company_id=BAKERY_COMPANY_ID, contract=Contract.EMPLOYMENT)
    assert {str(e.id) for e in employment} <= worked


@pytest.mark.django_db
def test_too_few_generations_left_for_all_locations(api, shop, settings, make_company):
    settings.GENERATION_MONTHLY_LIMIT = 1
    second = SchedulePeriod.objects.create(
        location=shop["location"], start=MON + timedelta(days=7), end=MON + timedelta(days=13)
    )
    api.login(shop["manager"])

    response = generate(api, shop["period"], second)

    assert response.status_code == 429
    assert "zostało 1, a potrzeba 2" in response.json()["detail"]
    assert not GenerationRun.objects.exists()
