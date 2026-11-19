"""One person in several locations (docs/plan.md, section 27): the generator may put them in each of their locations,
location rules cover them, and the monthly maximum and target count hours worked in other locations."""

from datetime import date, time, timedelta

import pytest

from engine.problem import ExternalShift, Request, RuleConfig, shift_bounds
from engine.scoring import score
from engine.validator import validate
from tests.engine.factory import LOC, employee, problem, slot
from tests.engine.test_solver import solved

OTHER = "loc-2"
DEC = (date(2026, 12, 1), date(2026, 12, 31))


def days(n: int, start: date = date(2026, 12, 7)):
    return [start + timedelta(days=i) for i in range(n)]


def external(employee_id: str, day: date, start: int = 6, end: int = 14) -> ExternalShift:
    return ExternalShift(employee_id, day, *shift_bounds(day, time(start), time(end)), label="Rynek")


def test_generator_puts_a_person_in_their_extra_location_only():
    slots = [slot(f"s{i}", d, location=OTHER) for i, d in enumerate(days(3))]
    both = employee("anna", extra_locations=frozenset({OTHER}))
    result, _ = solved(problem([both], slots))
    assert set(result.schedule.values()) == {"anna"}

    result, _ = solved(problem([employee("anna")], slots))  # only the main location
    assert result.holes == 3


def test_location_rules_cover_people_from_extra_locations():
    p = problem(
        [employee("anna", home=OTHER, extra_locations=frozenset({LOC}))],
        [slot(f"s{i}", d) for i, d in enumerate(days(3))],
        rules=(RuleConfig("max_consecutive_days", LOC, 1, params={"days": 2}),),
    )
    report = validate(p, {f"s{i}": "anna" for i in range(3)})
    assert report.rules[0].violations  # anna counts here although her main location is another one


@pytest.mark.parametrize(("worked_elsewhere", "broken"), [(0, False), (6, False), (7, True)])
def test_monthly_maximum_counts_hours_in_other_locations(worked_elsewhere, broken):
    # Maximum 62 h in December. 8 h here plus 6 shifts elsewhere (48 h) is 56 h; plus 7 shifts (56 h) is 64 h.
    elsewhere = tuple(external("anna", d) for d in days(worked_elsewhere, date(2026, 12, 8)))
    p = problem(
        [employee("anna", max_hours_month=62, extra_locations=frozenset({OTHER}))],
        [slot("s0", date(2026, 12, 7))],
        start=DEC[0],
        end=DEC[1],
        rules=(RuleConfig("personal_max_hours", LOC, 1, params={"tolerance_pct": 0}),),
        external_shifts=elsewhere,
    )
    rule = validate(p, {"s0": "anna"}).rules[0]
    assert (rule.degree > 0) is broken
    if broken:
        assert "64 h" in rule.violations[0].message  # counted together with the other locations
    # Hours elsewhere alone are not this location's problem.
    assert validate(p, {"s0": None}).rules[0].degree == 0


def test_hard_monthly_maximum_leaves_only_the_rest_for_this_location():
    # Maximum 31 h in December, 24 h already worked elsewhere: one 8 h shift here would be 32 h.
    slots = [slot(f"s{i}", d) for i, d in enumerate(days(2))]
    p = problem(
        [employee("anna", max_hours_month=31, extra_locations=frozenset({OTHER}))],
        slots,
        start=DEC[0],
        end=DEC[1],
        rules=(RuleConfig("personal_max_hours", LOC, 1, hard=True, params={"tolerance_pct": 0}),),
        external_shifts=tuple(external("anna", d) for d in days(3, date(2026, 12, 14))),
    )
    result, _ = solved(p)
    assert result.holes == 2
    assert not validate(p, {"s0": "anna"}).ok


def test_target_hours_count_only_in_the_main_location():
    slots = [slot("s0", date(2026, 12, 7), location=OTHER)]
    p = problem(
        [employee("anna", target_hours_month=100, extra_locations=frozenset({OTHER}))],
        slots,
        start=DEC[0],
        end=DEC[1],
        rules=(RuleConfig("target_hours", OTHER, 1),),
    )
    assert validate(p, {"s0": None}).rules[0].instances == 0


def test_request_counts_in_the_location_it_belongs_to():
    slots = [slot("a", date(2026, 12, 7)), slot("b", date(2026, 12, 7), location=OTHER)]
    person = employee("anna", extra_locations=frozenset({OTHER}))
    request = Request("r1", "anna", "days_off", dates=frozenset({date(2026, 12, 7)}), location=OTHER)
    p = problem([person], slots, requests=(request,))
    report = validate(p, {"a": None, "b": "anna"})
    assert score(p, report, location=OTHER).employee_requests < 100
    assert score(p, report, location=LOC).employee_requests == 100
