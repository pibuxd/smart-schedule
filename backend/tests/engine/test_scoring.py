"""The three numbers for the manager: unfilled slots, manager rules %, employee requests %."""

from datetime import date, timedelta

import pytest

from engine.problem import Availability, Request, RuleConfig, WeightProfile
from engine.scoring import penalty, score, unmet_requests
from engine.validator import validate
from tests.engine.factory import LOC, employee, problem, slot

MON = date(2026, 11, 16)


def day(n: int) -> date:
    return MON + timedelta(days=n)


def test_perfect_schedule():
    p = problem([employee("anna")], [slot("a", MON)], rules=(RuleConfig("min_rest_between_shifts", LOC, 1),))
    scores = score(p, validate(p, {"a": "anna"}))
    assert (scores.manager_rules, scores.employee_requests) == (100.0, 100.0)
    assert scores.is_complete and scores.is_valid
    assert scores.as_dict()["is_complete"] is True


def test_holes_make_the_schedule_incomplete():
    p = problem([employee("anna")], [slot("a", MON), slot("b", MON, "14:00", "22:00")])
    scores = score(p, validate(p, {"a": "anna"}))
    assert (scores.holes, scores.slots, scores.is_complete) == (1, 2, False)


def test_place_on_the_list_decides_how_much_a_rule_counts():
    # anna: 10 h rest (breaks min rest) and 7 days in a row (breaks consecutive days on 1 of 7 days)
    slots = [slot("late", MON, "14:00", "22:00"), slot("early", day(1), "08:00", "16:00")]

    def manager_score(first: str, second: str) -> float:
        rules = (RuleConfig(first, LOC, 1), RuleConfig(second, LOC, 2))
        p = problem([employee("anna")], slots, rules=rules)
        return score(p, validate(p, {"late": "anna", "early": "anna"})).manager_rules

    # Only the rest rule is broken (degree 1); consecutive days is measured and kept (degree 0).
    assert manager_score("min_rest_between_shifts", "max_consecutive_days") == pytest.approx(100 * (1 - 1 / 1.75), 0.01)
    assert manager_score("max_consecutive_days", "min_rest_between_shifts") == pytest.approx(
        100 * (1 - 0.75 / 1.75), 0.01
    )


def test_hard_rules_and_rules_with_nothing_to_measure_are_not_scored():
    rules = (
        RuleConfig("min_rest_between_shifts", LOC, 1, hard=True),
        RuleConfig("fair_closings", LOC, 2),  # no closing shifts
        RuleConfig("max_consecutive_days", LOC, 3),
    )
    slots = [slot("late", MON, "14:00", "22:00"), slot("early", day(1), "08:00", "16:00")]
    p = problem([employee("anna")], slots, rules=rules)
    scores = score(p, validate(p, {"late": "anna", "early": "anna"}))
    assert scores.manager_rules == 100.0
    assert scores.hard_violations == 1
    assert scores.unmeasured_rules == 1  # fair_closings: shown as "nic do oceny", not as kept


def test_requests_left_to_the_manager_are_counted_next_to_the_score():
    p = problem([employee("anna")], [slot("a", MON)], requests=(Request("r", "anna", "other"),))
    scores = score(p, validate(p, {"a": "anna"}))
    assert (scores.employee_requests, scores.unscored_requests) == (100.0, 1)


def test_requests_score_is_weighted():
    people = [employee("anna"), employee("ola")]
    slots = [slot("a", MON), slot("b", day(1))]
    p = problem(
        people,
        slots,
        requests=(
            Request("off", "anna", "days_off", dates=frozenset({MON})),  # weight 3, broken
            Request("r", "ola", "hours_limit", max_hours=8, level="bardzo_wazne"),  # weight 9, kept
        ),
    )
    report = validate(p, {"a": "anna", "b": "ola"})
    assert score(p, report).employee_requests == pytest.approx(75.0)
    assert [r.employee for r in unmet_requests(report)] == ["anna"]


def test_scores_per_location():
    people = [employee("anna"), employee("ola", home="loc-2")]
    slots = [slot("a", MON), slot("b", MON, location="loc-2"), slot("c", day(1), location="loc-2")]
    p = problem(people, slots, requests=(Request("off", "ola", "days_off", dates=frozenset({MON})),))
    report = validate(p, {"a": "anna", "b": "ola"})
    first, second = score(p, report, LOC), score(p, report, "loc-2")
    assert (first.holes, first.slots, first.employee_requests) == (0, 1, 100.0)
    assert (second.holes, second.slots, second.employee_requests) == (1, 2, 0.0)


def test_penalty_weighs_manager_rules_over_requests_and_counts_changes():
    slots = [slot("late", MON, "14:00", "22:00"), slot("early", day(1), "08:00", "16:00")]
    people = [employee("anna"), employee("ola")]
    p = problem(
        people,
        slots,
        rules=(RuleConfig("min_rest_between_shifts", LOC, 1),),
        requests=(Request("off", "ola", "days_off", dates=frozenset({day(1)})),),
        published={"late": "anna", "early": "anna"},
        weights=WeightProfile(manager_share=0.8, stability_penalty=5),
    )
    rule_broken = validate(p, {"late": "anna", "early": "anna"})  # manager 0 %, requests 100 %
    request_broken = validate(p, {"late": "anna", "early": "ola"})  # manager 100 %, requests 0 %, one change
    assert penalty(p, rule_broken) == pytest.approx(80.0)
    assert penalty(p, request_broken) == pytest.approx(20.0 + 5.0)


def test_a_month_for_four_bakeries_is_checked_quickly():
    """Realistic size: 4 locations × 20 people × 30 days × 8 slots, every catalog rule switched on."""
    import time as clock

    from engine.rules_catalog import RULES

    locations = [f"loc-{i}" for i in range(4)]
    people = [employee(f"{loc}-e{i}", home=loc, target_hours_month=120) for loc in locations for i in range(20)]
    slots, schedule = [], {}
    start = date(2026, 11, 1)
    for loc in locations:
        staff = [e.id for e in people if e.home_location == loc]
        for d in range(30):
            for n, (begin, end) in enumerate([("06:00", "14:00")] * 4 + [("14:00", "22:00")] * 4):
                s = slot(f"{loc}-{d}-{n}", start + timedelta(days=d), begin, end, location=loc, closing=n >= 4)
                slots.append(s)
                schedule[s.id] = staff[(d * 8 + n) % 20]
    rules = tuple(RuleConfig(r.code, loc, rank) for loc in locations for rank, r in enumerate(RULES, start=1))
    availability = tuple(Availability(e.id, start + timedelta(days=d), "prefer") for e in people[::3] for d in (0, 7))
    days_off = tuple(
        Request(f"off-{e.id}", e.id, "days_off", dates=frozenset({start + timedelta(days=3)})) for e in people[1::3]
    )
    p = problem(
        people, slots, start=start, end=date(2026, 11, 30), rules=rules, availability=availability, requests=days_off
    )

    began = clock.perf_counter()
    report = validate(p, schedule)
    scores = score(p, report)
    elapsed = clock.perf_counter() - began

    assert elapsed < 2.0
    assert scores.slots == 960
    assert 0 <= scores.manager_rules <= 100
    assert 0 <= scores.employee_requests <= 100
