"""The generator (CP-SAT) checked against the independent validator. No database needed."""

import itertools
import random
import time as clock
from datetime import date, time, timedelta

import pytest

from engine.problem import (
    Availability,
    ExternalShift,
    Request,
    RuleConfig,
    WeightProfile,
    shift_bounds,
)
from engine.scoring import penalty, score
from engine.solver import SolveStatus, solve
from engine.validator import validate
from tests.engine.factory import BAKER, LOC, SALES, employee, problem, slot

MON = date(2026, 11, 2)  # a Monday
FAST = {"time_limit_s": 5, "workers": 4}


def day(n: int) -> date:
    return MON + timedelta(days=n)


def week(days: int = 7, *, places: int = 1, closing: bool = True, position: str = SALES, prefix: str = ""):
    """Morning 06–14 and afternoon 14–22 every day, `places` people each."""
    slots = []
    for d in range(days):
        for p in range(places):
            slots.append(slot(f"{prefix}m{d}.{p}", day(d), "06:00", "14:00", position=position, shift_type="morning"))
            slots.append(
                slot(
                    f"{prefix}a{d}.{p}",
                    day(d),
                    "14:00",
                    "22:00",
                    position=position,
                    shift_type="afternoon",
                    closing=closing,
                )
            )
    return slots


def solved(p, **kwargs):
    result = solve(p, **{**FAST, **kwargs})
    assert result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE), result.messages
    report = validate(p, result.schedule)
    assert report.ok, [v.message for v in report.hard]
    assert result.holes == len(report.holes)
    return result, report


# ----------------------------------------------------------------- basics


def test_fills_every_slot_when_there_are_enough_people():
    p = problem([employee(f"e{i}") for i in range(4)], week())
    result, report = solved(p)
    assert report.holes == ()
    assert result.status == SolveStatus.OPTIMAL


def test_leaves_holes_when_people_are_missing_and_still_returns_a_schedule():
    # One person, two people needed at the same time every day: one hole per morning, nothing breaks.
    slots = [slot(f"m{d}.{k}", day(d)) for d in range(3) for k in range(2)]
    p = problem([employee("anna")], slots)
    result, _report = solved(p)
    assert result.holes == 3
    assert sorted(v for v in result.schedule.values() if v) == ["anna"] * 3


def test_minimises_holes_before_anything_else():
    # Anna asked for that day off, but she is the only one who can cover it: the slot is filled anyway.
    p = problem(
        [employee("anna")],
        [slot("m0", day(0))],
        requests=[Request("off", "anna", "days_off", dates=frozenset({day(0)}), level="bardzo_wazne")],
    )
    result, _ = solved(p)
    assert result.schedule == {"m0": "anna"}


def test_respects_cannot_position_and_home_location():
    p = problem(
        [
            employee("anna", positions=(SALES,)),
            employee("piotr", positions=(BAKER,)),
            employee("ewa", home="loc-2"),
        ],
        [slot("m0", day(0)), slot("m1", day(1))],
        availability=[Availability("anna", day(1), "cannot")],
    )
    result, _ = solved(p)
    assert result.schedule == {"m0": "anna", "m1": None}


def test_cannot_with_hours_blocks_only_overlapping_shifts():
    p = problem(
        [employee("anna")],
        [slot("m0", day(0), "06:00", "14:00", shift_type="m"), slot("a0", day(0), "15:00", "22:00", shift_type="a")],
        availability=[Availability("anna", day(0), "cannot", from_time=time(5), to_time=time(13))],
    )
    result, _ = solved(p)
    assert result.schedule == {"m0": None, "a0": "anna"}


def test_never_gives_one_person_two_overlapping_shifts():
    slots = [
        slot("a", day(0), "06:00", "14:00"),
        slot("b", day(0), "10:00", "18:00"),
        slot("c", day(0), "14:00", "22:00"),
    ]
    result, _ = solved(problem([employee("anna")], slots))
    # Touching shifts (06–14, 14–22) are fine for a civil contract; the 10–18 overlaps both.
    assert result.schedule == {"a": "anna", "b": None, "c": "anna"}


def test_external_shifts_count_for_overlaps():
    start, end = shift_bounds(day(0), time(8), time(12))
    p = problem(
        [employee("anna")],
        [slot("m0", day(0))],
        external_shifts=[ExternalShift("anna", day(0), start, end, label="inny lokal")],
    )
    result, _ = solved(p)
    assert result.schedule == {"m0": None}


# ----------------------------------------------------------------- employment contract


def test_employment_contract_gets_11_hours_rest_and_8_hours_a_day():
    # Touching 06–14 and 14–22 would be fine for a civil contract, not for an employment one.
    slots = [slot("m0", day(0), "06:00", "14:00"), slot("a0", day(0), "14:00", "22:00"), slot("m1", day(1))]
    p = problem([employee("kasia", contract="employment")], slots)
    result, _ = solved(p)
    assert result.holes == 1
    assert result.schedule["m0"] == "kasia"
    assert result.schedule["m1"] == "kasia"


def test_employment_contract_rest_counts_external_shifts():
    start, end = shift_bounds(day(0) - timedelta(days=1), time(14), time(22))
    p = problem(
        [employee("kasia", contract="employment")],
        [slot("m0", day(0), "06:00", "14:00"), slot("a0", day(0), "14:00", "22:00", shift_type="a")],
        external_shifts=[ExternalShift("kasia", day(0) - timedelta(days=1), start, end)],
    )
    result, _ = solved(p)
    # 22:00 → 06:00 is only 8 h of rest; 22:00 → 14:00 is 16 h.
    assert result.schedule == {"m0": None, "a0": "kasia"}


def test_employment_contract_gets_35_hours_weekly_rest():
    # Two people needed every day, 7 days: one employment-contract person cannot work all 7 days of the week.
    slots = [slot(f"m{d}", day(d), "08:00", "16:00") for d in range(7)]
    p = problem([employee("kasia", contract="employment")], slots)
    result, _ = solved(p)
    assert result.holes == 1  # six days work: the free day plus nights give 35 h+


def test_civil_contract_has_no_labour_law_limits():
    slots = [slot(f"m{d}", day(d), "08:00", "16:00") for d in range(7)]
    result, _ = solved(problem([employee("anna")], slots))
    assert result.holes == 0


# ----------------------------------------------------------------- pins, past days, impossible settings


def test_keeps_pinned_and_frozen_assignments():
    p = problem(
        [employee("anna"), employee("ewa")],
        [slot("m0", day(0)), slot("m1", day(1)), slot("m2", day(2))],
        pinned={"m2": "ewa"},
        published={"m0": None, "m1": "anna", "m2": "anna"},
        frozen_before=day(1),
        availability=[Availability("ewa", day(1), "prefer")],
    )
    result, _ = solved(p)
    assert result.schedule["m0"] is None  # a past hole stays a hole
    assert result.schedule["m2"] == "ewa"


def test_pinned_person_who_cannot_work_is_reported_not_solved():
    p = problem(
        [employee("anna"), employee("ewa")],
        [slot("m0", day(0))],
        pinned={"m0": "anna"},
        availability=[Availability("anna", day(0), "cannot")],
    )
    result = solve(p, **FAST)
    assert result.status == SolveStatus.INFEASIBLE
    assert result.schedule is None
    assert any("Anna ma zaznaczone „nie mogę”" in m for m in result.messages)


def test_impossible_hard_rule_is_named():
    # Target hours "no exceptions" for someone who can work only one 8 h shift: impossible.
    p = problem(
        [employee("anna", target_hours_month=120)],
        [slot("m0", day(0))],
        rules=[RuleConfig("target_hours", LOC, rank=1, hard=True), RuleConfig("fair_weekends", LOC, rank=2, hard=True)],
    )
    result = solve(p, **FAST)
    assert result.status == SolveStatus.INFEASIBLE
    assert "„Cel godzin”" in result.messages[0]
    assert "Równy podział weekendów" not in result.messages[0]


def test_time_limit_is_kept_on_a_big_problem():
    rng = random.Random(7)
    people = [employee(f"e{i}", target_hours_month=rng.choice([None, 80, 120])) for i in range(40)]
    slots = []
    for d in range(30):
        for k in range(8):
            slots.append(slot(f"m{d}.{k}", MON + timedelta(days=d), "06:00", "14:00", shift_type="m"))
            slots.append(slot(f"a{d}.{k}", MON + timedelta(days=d), "13:00", "21:00", shift_type="a", closing=True))
    rules = [
        RuleConfig(code, LOC, rank=i)
        for i, code in enumerate(
            ["min_rest_between_shifts", "target_hours", "fair_weekends", "fair_closings", "same_shift_type_in_week"], 1
        )
    ]
    availability = [
        Availability(e.id, MON + timedelta(days=d), rng.choice(["cannot", "prefer", "neutral"]))
        for e in people
        for d in range(30)
        if rng.random() < 0.4
    ]
    p = problem(people, slots, start=MON, end=MON + timedelta(days=29), rules=rules, availability=availability)
    started = clock.monotonic()
    result = solve(p, time_limit_s=2, workers=4)
    elapsed = clock.monotonic() - started
    assert elapsed < 4, elapsed  # 2 s of solving plus building the model
    assert result.status in (SolveStatus.FEASIBLE, SolveStatus.OPTIMAL, SolveStatus.TIMEOUT_NO_SOLUTION)
    if result.schedule is not None:
        assert validate(p, result.schedule).ok


# ----------------------------------------------------------------- stability


def test_regenerating_after_one_absence_changes_little():
    people = [employee(f"e{i}") for i in range(6)]
    base = problem(people, week(places=2), start=MON, end=day(6))
    first, _ = solved(base)

    # e0 now cannot work on Wednesday; everything else is the same.
    changed = problem(
        people,
        week(places=2),
        start=MON,
        end=day(6),
        published=dict(first.schedule),
        availability=[Availability("e0", day(2), "cannot")],
    )
    _second, report = solved(changed)
    lost = [s for s, e in first.schedule.items() if e == "e0" and s.startswith(("m2.", "a2."))]
    assert report.holes == ()
    assert len(report.stability_changes) <= 2 * len(lost)  # the lost shift and at most one swap for it


def test_stability_penalty_zero_allows_a_better_reshuffle():
    # Published: Anna on both mornings. Later Anna asked for day 1 off; Ewa is free.
    people = [employee("anna"), employee("ewa")]
    slots = [slot("m0", day(0)), slot("m1", day(1))]
    published = {"m0": "anna", "m1": "anna"}
    requests = [Request("off", "anna", "days_off", dates=frozenset({day(1)}))]
    sticky = problem(people, slots, published=published, requests=requests, weights=WeightProfile(stability_penalty=50))
    loose = problem(people, slots, published=published, requests=requests, weights=WeightProfile(stability_penalty=0))
    assert solved(sticky)[0].schedule == published
    assert solved(loose)[0].schedule["m1"] == "ewa"


# ----------------------------------------------------------------- soft rules and requests


def test_prefers_people_who_marked_prefer():
    people = [employee("anna"), employee("ewa"), employee("ola")]
    p = problem(people, [slot("m0", day(0))], availability=[Availability("ewa", day(0), "prefer")])
    result, _ = solved(p)
    assert result.schedule == {"m0": "ewa"}


def test_keeps_days_off_asked_for_in_text():
    people = [employee("anna"), employee("ewa")]
    p = problem(
        people,
        [slot("m0", day(0)), slot("m1", day(1))],
        requests=[
            Request("anna-off", "anna", "days_off", dates=frozenset({day(0)})),
            Request("ewa-off", "ewa", "days_off", dates=frozenset({day(1)})),
        ],
    )
    result, _ = solved(p)
    assert result.schedule == {"m0": "ewa", "m1": "anna"}


def test_days_off_without_dates_is_left_to_the_manager():
    p = problem([employee("anna")], [slot("m0", day(0))], requests=[Request("off", "anna", "days_off")])
    result, report = solved(p)
    assert result.schedule == {"m0": "anna"}
    assert report.unscored_requests == ("off",)


def test_manager_rules_outweigh_employee_requests():
    # Rest of 11 h (manager rule) against Anna's wish to work the evening and the next morning.
    people = [employee("anna"), employee("ewa")]
    slots = [slot("a0", day(0), "14:00", "22:00", shift_type="a"), slot("m1", day(1), "06:00", "14:00", shift_type="m")]
    p = problem(
        people,
        slots,
        rules=[RuleConfig("min_rest_between_shifts", LOC, rank=1)],
        availability=[
            Availability("anna", day(0), "prefer"),
            Availability("anna", day(1), "prefer"),
        ],
        requests=[Request("ewa-off", "ewa", "days_off", dates=frozenset({day(0), day(1)}))],
    )
    result, report = solved(p)
    # Ewa works one shift she would rather not, so that Anna gets her 11 h rest.
    assert result.schedule["a0"] != result.schedule["m1"]
    assert score(p, report).employee_requests < 100
    assert score(p, report).manager_rules == 100


def test_hours_target_is_met_when_possible():
    people = [
        employee("anna", target_hours_month=16 * 30 / 7),
        employee("ewa", target_hours_month=40 * 30 / 7),
        employee("ola"),  # no target: takes the rest
    ]
    p = problem(people, week(), start=MON, end=day(6), rules=[RuleConfig("target_hours", LOC, rank=1)])
    _result, report = solved(p)
    assert report.hours["anna"] == pytest.approx(16)
    assert report.hours["ewa"] == pytest.approx(40)


def test_avoid_person_request_is_kept():
    people = [employee("anna"), employee("ewa"), employee("ola")]
    slots = [slot(f"m{d}.{k}", day(d)) for d in range(3) for k in range(2)]
    request = Request("r1", "anna", "avoid_person", subject_employee="ewa", level="bardzo_wazne")
    result, _report = solved(problem(people, slots, requests=[request]))
    for d in range(3):
        assert {result.schedule[f"m{d}.0"], result.schedule[f"m{d}.1"]} != {"anna", "ewa"}


def test_hours_limit_and_shift_type_requests_are_kept():
    people = [employee("anna"), employee("ewa"), employee("ola")]
    requests = [
        Request("r1", "anna", "shift_type", shift_type="morning", avoid=False, level="bardzo_wazne"),
        Request("r2", "ewa", "hours_limit", max_hours=16, level="bardzo_wazne"),
    ]
    result, report = solved(problem(people, week(3), requests=requests))
    assert all(result.schedule[s] != "anna" for s in result.schedule if s.startswith("a"))
    assert report.hours["ewa"] <= 16


@pytest.mark.parametrize("code", ["fair_weekends", "fair_closings"])
def test_fair_split_rules_as_hard_constraints(code):
    people = [employee(f"e{i}") for i in range(3)]
    p = problem(people, week(14), rules=[RuleConfig(code, LOC, rank=1, hard=True)])
    _, report = solved(p)
    measure = next(m for m in report.rules if m.code == code)
    assert measure.violations == ()


def test_beginner_is_put_with_an_experienced_colleague():
    people = [
        employee("nowa", experience=1),
        employee("nowy", experience=1),
        employee("stara", experience=3),
        employee("ola"),
    ]
    # Two places on each of two shifts a day: without the rule the two beginners could work together.
    slots = week(3, places=2, closing=False)
    p = problem(people, slots, rules=[RuleConfig("experience_mix", LOC, rank=1)])
    result, report = solved(p)
    assert next(m for m in report.rules if m.code == "experience_mix").violations == ()
    for shift in {(s.date, s.shift_type) for s in p.slots}:
        team = {result.schedule[s.id] for s in p.slots if (s.date, s.shift_type) == shift}
        assert not {"nowa", "nowy"} <= team


def test_experience_mix_can_count_one_position_only():
    people = [employee("nowa", experience=1), employee("piekarz", positions=(BAKER,), experience=3)]
    slots = [slot("s", MON), slot("b", MON, position=BAKER)]
    whole_shift = problem(people, slots, rules=[RuleConfig("experience_mix", LOC, rank=1, hard=True)])
    sales_only = problem(
        people, slots, rules=[RuleConfig("experience_mix", LOC, rank=1, hard=True, params={"position": SALES})]
    )
    assert solved(whole_shift)[0].schedule == {"s": "nowa", "b": "piekarz"}
    # Counting sellers only, the experienced baker does not help: the beginner may not sell alone.
    assert solved(sales_only)[0].schedule == {"s": None, "b": "piekarz"}


# ----------------------------------------------------------------- hard rules never broken (random problems)

HARD_SAFE_RULES = [
    ("min_rest_between_shifts", {"hours": 11}),
    ("max_consecutive_days", {"days": 4}),
    ("fair_weekends", {}),
    ("fair_closings", {}),
    ("personal_max_hours", {}),
    ("same_shift_type_in_week", {}),
    ("max_shifts_per_week", {"shifts": 4}),
    ("experience_mix", {}),
]


def random_problem(seed: int):
    rng = random.Random(seed)
    days = rng.choice([7, 14])
    people = []
    for i in range(rng.randint(4, 9)):
        people.append(
            employee(
                f"e{i}",
                positions=tuple(rng.sample([SALES, BAKER], rng.choice([1, 1, 2]))),
                contract=rng.choice(["civil", "civil", "employment"]),
                max_hours_month=rng.choice([None, 60, 120]),
                target_hours_month=rng.choice([None, 40, 80]),
                home=rng.choice([LOC, LOC, "loc-2"]),
                experience=1 + i % 3,
            )
        )
    slots = []
    for d in range(days):
        current = MON + timedelta(days=d)
        for location in (LOC, "loc-2"):
            for shift, (start, end) in {
                "m": ("06:00", "14:00"),
                "a": ("13:00", "21:00"),
                "n": ("22:00", "06:00"),
            }.items():
                for k in range(rng.randint(0, 2)):
                    position = BAKER if shift == "n" else SALES
                    slots.append(
                        slot(
                            f"{location}/{d}/{shift}/{k}",
                            current,
                            start,
                            end,
                            position=position,
                            shift_type=shift,
                            location=location,
                            closing=shift == "a",
                        )
                    )
    availability = []
    for person in people:
        for d in range(-1, days + 1):
            if rng.random() < 0.35:
                state = rng.choice(["cannot", "prefer", "neutral"])
                hours = rng.choice([(None, None), (None, None), (time(12), None), (None, time(15))])
                availability.append(Availability(person.id, MON + timedelta(days=d), state, *hours))
    rules = []
    for location in (LOC, "loc-2"):
        chosen = rng.sample(HARD_SAFE_RULES, rng.randint(1, 4))
        for rank, (code, params) in enumerate(chosen, start=1):
            rules.append(RuleConfig(code, location, rank=rank, hard=rng.random() < 0.5, params=params))
    externals = []
    for person in rng.sample(people, 2):
        start, end = shift_bounds(MON - timedelta(days=1), time(14), time(22))
        externals.append(ExternalShift(person.id, MON - timedelta(days=1), start, end))
    requests = [
        Request("r1", people[0].id, "avoid_person", subject_employee=people[1].id),
        Request("r2", people[1].id, "prefer_person", subject_employee=people[2].id, level="mile_widziane"),
        Request("r3", people[2].id, "hours_limit", max_hours=24),
        Request("r4", people[3].id, "shift_type", shift_type="m", avoid=True),
        Request("r5", people[0].id, "other"),
    ]
    published = {s.id: rng.choice([None, *[p.id for p in people]]) for s in slots if rng.random() < 0.3}
    return problem(
        people,
        slots,
        start=MON,
        end=MON + timedelta(days=days - 1),
        availability=availability,
        rules=rules,
        requests=requests,
        external_shifts=externals,
        published=published,
    )


@pytest.mark.parametrize("seed", range(25))
def test_random_problems_never_break_hard_rules(seed):
    p = random_problem(seed)
    result = solve(p, time_limit_s=3, workers=4, seed=seed)
    if result.status == SolveStatus.INFEASIBLE:
        assert result.messages  # explained, never a silent failure
        return
    assert result.schedule is not None, result.status
    report = validate(p, result.schedule)
    assert report.ok, [v.message for v in report.hard]
    # Generator never assigns outside the home location (borrowing is manual) or an inactive role.
    for slot_id, employee_id in result.schedule.items():
        if employee_id is not None:
            assert p.employee_by_id[employee_id].home_location == p.slot_by_id[slot_id].location


# ----------------------------------------------------------------- the objective matches the score


def all_schedules(p):
    options = [[None, *[e.id for e in p.employees]] for _ in p.slots]
    for combo in itertools.product(*options):
        yield dict(zip([s.id for s in p.slots], combo, strict=True))


@pytest.mark.parametrize("seed", range(6))
def test_finds_the_lowest_penalty_on_tiny_problems(seed):
    """For rules modelled exactly, the solver's choice must be as good as the best of all schedules."""
    rng = random.Random(seed)
    people = [
        employee("anna", target_hours_month=rng.choice([16, 24]) * 30 / 7, max_hours_month=24 * 30 / 7, experience=1),
        employee("ewa", target_hours_month=rng.choice([8, 16]) * 30 / 7, positions=(SALES, BAKER), experience=3),
        employee("ola", positions=(BAKER,)),
    ]
    slots = [
        slot("m0", day(0)),
        slot("a0", day(0), "14:00", "22:00", shift_type="a", closing=True),
        slot("m1", day(1)),
        slot("b1", day(1), "06:00", "14:00", position=BAKER, shift_type="b"),
        slot("a1", day(1), "14:00", "22:00", shift_type="a", closing=True),
    ]
    # "chętnie" is left out: its share of possible days is only approximated in the model.
    days_off = [
        Request(f"off-{e.id}-{d}", e.id, "days_off", dates=frozenset({day(d)}))
        for e in people
        for d in range(2)
        if rng.random() < 0.5
    ]
    p = problem(
        people,
        slots,
        start=MON,
        end=day(6),
        rules=[
            RuleConfig("target_hours", LOC, rank=1),
            RuleConfig("personal_max_hours", LOC, rank=2),
            RuleConfig("min_position_on_closing", LOC, rank=3, params={"position": BAKER}),
            RuleConfig("experience_mix", LOC, rank=4),
        ],
        requests=[
            Request("r1", "anna", "hours_limit", max_hours=8, level=rng.choice(["wazne", "mile_widziane"])),
            *days_off,
        ],
    )
    _result, report = solved(p)
    best = min((len(r.holes), penalty(p, r)) for r in (validate(p, s) for s in all_schedules(p)) if r.ok)
    mine = (len(report.holes), penalty(p, report))
    assert mine[0] == best[0]
    assert mine[1] <= best[1] + 0.01


# ----------------------------------------------------------------- variants (prepared for later)


def test_second_variant_differs_by_at_least_15_percent():
    people = [employee(f"e{i}") for i in range(5)]
    p = problem(people, week(places=2))
    first, _ = solved(p)
    second, _ = solved(p, diversity_from=[first.schedule])
    same = sum(1 for s, e in first.schedule.items() if e is not None and second.schedule[s] == e)
    filled = sum(1 for e in first.schedule.values() if e is not None)
    assert same <= 0.85 * filled


def test_weights_can_be_replaced_for_a_variant():
    # Manager share 1.0: employee requests do not count at all, so a wish may be ignored for a rule.
    people = [employee("anna"), employee("ewa")]
    slots = [slot("a0", day(0), "14:00", "22:00", shift_type="a"), slot("m1", day(1), "06:00", "14:00", shift_type="m")]
    p = problem(people, slots, rules=[RuleConfig("min_rest_between_shifts", LOC, rank=1)])
    _result, report = solved(p, weights=WeightProfile(manager_share=1.0))
    assert score(p, report).manager_rules == 100
