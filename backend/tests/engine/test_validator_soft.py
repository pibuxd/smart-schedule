"""Soft rules from the catalog and employee requests: how much each is broken; "no exceptions" makes a rule hard."""

from datetime import date, time, timedelta

import pytest

from engine.problem import Availability, ExternalShift, Request, RuleConfig, shift_bounds
from engine.validator import Code, RequestKind, validate
from tests.engine.factory import BAKER, LOC, SALES, employee, problem, slot

MON = date(2026, 11, 16)
SAT, SUN = MON + timedelta(days=5), MON + timedelta(days=6)


def day(n: int) -> date:
    return MON + timedelta(days=n)


def rule(code: str, rank: int = 1, hard: bool = False, **params) -> RuleConfig:
    return RuleConfig(code, LOC, rank, hard=hard, params=params)


def measure(report, code: str):
    (found,) = [m for m in report.rules if m.code == code]
    return found


class TestMinRest:
    slots = (slot("a", MON, "14:00", "22:00"), slot("b", day(1), "08:00", "16:00"))  # 10 h rest

    def test_soft_rule_is_measured_not_blocking(self):
        report = validate(
            problem([employee("anna")], self.slots, rules=(rule("min_rest_between_shifts"),)),
            {
                "a": "anna",
                "b": "anna",
            },
        )
        assert report.ok
        m = measure(report, "min_rest_between_shifts")
        assert (m.instances, m.degree) == (1, 1.0)
        assert "10 h" in m.violations[0].message

    def test_no_exceptions_makes_it_hard(self):
        p = problem([employee("anna")], self.slots, rules=(rule("min_rest_between_shifts", hard=True, hours=10),))
        assert validate(p, {"a": "anna", "b": "anna"}).ok  # 10 h is enough with hours=10
        p = problem([employee("anna")], self.slots, rules=(rule("min_rest_between_shifts", hard=True),))
        report = validate(p, {"a": "anna", "b": "anna"})
        assert [(v.code, v.rule_code, v.location) for v in report.hard] == [(Code.RULE, "min_rest_between_shifts", LOC)]


class TestConsecutiveDays:
    def test_seventh_day_in_a_row(self):
        slots = [slot(f"d{i}", day(i)) for i in range(7)]
        report = validate(
            problem([employee("anna")], slots, rules=(rule("max_consecutive_days"),)), {s.id: "anna" for s in slots}
        )
        m = measure(report, "max_consecutive_days")
        assert m.instances == 7
        assert m.degree == pytest.approx(1 / 7)
        assert len(m.violations) == 1

    def test_days_from_the_previous_period_count(self):
        before = [MON - timedelta(days=i) for i in range(1, 4)]
        external = tuple(ExternalShift("anna", d, *shift_bounds(d, time(6), time(14))) for d in before)
        slots = [slot(f"d{i}", day(i)) for i in range(4)]  # 3 + 4 = 7 days in a row
        p = problem([employee("anna")], slots, rules=(rule("max_consecutive_days"),), external_shifts=external)
        m = measure(validate(p, {s.id: "anna" for s in slots}), "max_consecutive_days")
        assert m.degree == pytest.approx(1 / 4)

    def test_a_day_off_resets_the_count(self):
        slots = [slot(f"d{i}", day(i)) for i in (0, 1, 2, 3, 4, 6, 7, 8)]
        p = problem([employee("anna")], slots, rules=(rule("max_consecutive_days", hard=True),))
        assert validate(p, {s.id: "anna" for s in slots}).ok


class TestFairness:
    def employees(self):
        return [employee("anna"), employee("ola"), employee("ewa")]

    def test_weekends_spread_evenly_with_difference_of_one_allowed(self):
        slots = [slot("sat1", SAT), slot("sat2", SAT, "14:00", "22:00"), slot("sun", SUN), slot("mon", MON)]
        p = problem(self.employees(), slots, rules=(rule("fair_weekends"),))
        fair = validate(p, {"sat1": "anna", "sat2": "ola", "sun": "ewa", "mon": "anna"})
        assert measure(fair, "fair_weekends").degree == 0.0  # one weekend day each
        unfair = validate(p, {"sat1": "anna", "sat2": None, "sun": "anna", "mon": "ewa"})
        m = measure(unfair, "fair_weekends")
        assert m.degree == pytest.approx(0.5)  # (2 − 0 − 1) / 2; ola has no shifts at all, so she is not compared
        assert "od 0 do 2" in m.violations[0].message

    def test_hard_fairness(self):
        slots = [slot("sat", SAT), slot("sun", SUN), slot("mon", MON), slot("tue", day(1))]
        p = problem(self.employees()[:2], slots, rules=(rule("fair_weekends", hard=True),))
        assert not validate(p, {"sat": "anna", "sun": "anna", "mon": "ola"}).ok
        assert validate(p, {"sat": "anna", "sun": "ola", "mon": "ola"}).ok

    def test_closings(self):
        slots = [slot(f"c{i}", day(i), "14:00", "22:00", closing=True) for i in range(4)]
        p = problem(self.employees()[:2], slots, rules=(rule("fair_closings"),))
        m = measure(validate(p, {"c0": "anna", "c1": "anna", "c2": "anna", "c3": "ola"}), "fair_closings")
        assert m.degree == pytest.approx(1 / 3)


class TestHours:
    month = (date(2026, 11, 1), date(2026, 11, 30))

    def slots(self, n: int):
        return [slot(f"d{i}", date(2026, 11, 2) + timedelta(days=i)) for i in range(n)]

    def test_target_hours_over_a_whole_month(self):
        slots = self.slots(2)
        p = problem(
            [employee("anna", target_hours_month=32)],
            slots,
            start=self.month[0],
            end=self.month[1],
            rules=(rule("target_hours"),),
        )
        m = measure(validate(p, {s.id: "anna" for s in slots}), "target_hours")
        assert m.degree == pytest.approx(0.5)  # 16 h of 32 h

    def test_target_is_prorated_for_part_of_a_month(self):
        slots = self.slots(2)
        p = problem(
            [employee("anna", target_hours_month=48)],
            slots,
            start=date(2026, 11, 1),
            end=date(2026, 11, 10),  # a third of November
            rules=(rule("target_hours", hard=True),),
        )
        assert validate(p, {s.id: "anna" for s in slots}).ok  # 16 h = 48 h / 3

    def test_personal_maximum(self):
        slots = self.slots(3)
        employees = [employee("anna", max_hours_month=16), employee("ola")]
        p = problem(employees, slots, start=self.month[0], end=self.month[1], rules=(rule("personal_max_hours"),))
        m = measure(validate(p, {s.id: "anna" for s in slots}), "personal_max_hours")
        assert m.instances == 1  # only people with a maximum
        assert m.degree == pytest.approx(0.5)
        assert "24 h" in m.violations[0].message
        assert validate(p, {"d0": "anna", "d1": "anna", "d2": "ola"}).rules[0].degree == 0


class TestOtherRules:
    def test_preferred_shift_type_without_params_measures_nothing(self):
        p = problem([employee("anna")], [slot("a", MON)], rules=(rule("preferred_shift_type_for_position"),))
        assert measure(validate(p, {"a": "anna"}), "preferred_shift_type_for_position").instances == 0

    def test_preferred_shift_type_for_bakers(self):
        bakers = [employee("jan", positions=(BAKER,))]
        slots = [
            slot("n1", MON, "22:00", "06:00", position=BAKER, shift_type="night"),
            slot("m1", day(2), "06:00", "14:00", position=BAKER, shift_type="morning"),
        ]
        p = problem(
            bakers, slots, rules=(rule("preferred_shift_type_for_position", position=BAKER, shift_type="night"),)
        )
        m = measure(validate(p, {"n1": "jan", "m1": "jan"}), "preferred_shift_type_for_position")
        assert (m.instances, m.degree) == (2, 0.5)

    def test_someone_responsible_on_closing(self):
        people = [employee("anna"), employee("szef", positions=(SALES, "lead"))]
        slots = [
            slot("c1", MON, "14:00", "22:00", closing=True, shift_type="close"),
            slot("c2", MON, "14:00", "22:00", closing=True, shift_type="close"),
            slot("c3", day(1), "14:00", "22:00", closing=True, shift_type="close"),
        ]
        p = problem(people, slots, rules=(rule("min_position_on_closing", hard=True, position="lead"),))
        report = validate(p, {"c1": "anna", "c2": "szef", "c3": "anna"})
        assert [v.slots for v in report.hard] == [("c3",)]

    def test_beginners_need_as_many_experienced_on_the_shift(self):
        people = [
            employee("nowa", experience=1),
            employee("nowy", experience=1),
            employee("stara", experience=3),
            employee("ola"),
        ]
        slots = [slot(f"m{i}", MON, shift_type="am") for i in range(3)] + [slot("p", MON, "14:00", "22:00")]
        p = problem(people, slots, rules=(rule("experience_mix"),))
        report = validate(p, {"m0": "nowa", "m1": "nowy", "m2": "stara", "p": "ola"})
        m = measure(report, "experience_mix")
        assert (m.instances, m.degree) == (2, 0.5)
        assert (
            m.violations[0].message
            == "Na zmianie 16.11 Zmiana 06:00–14:00 jest 2 początkujących, a doświadczonych tylko 1."
        )
        # Skilled people (the default) do not count either way.
        assert measure(validate(p, {"m0": "nowa", "m1": "ola", "m2": "stara"}), "experience_mix").degree == 0.0

    def test_experience_mix_for_one_position(self):
        people = [employee("nowa", experience=1), employee("jan", positions=(BAKER,), experience=3)]
        slots = [slot("s", MON), slot("b", MON, position=BAKER)]
        p = problem(people, slots, rules=(rule("experience_mix", hard=True, position=SALES),))
        assert not validate(p, {"s": "nowa", "b": "jan"}).ok
        assert validate(
            problem(people, slots, rules=(rule("experience_mix", hard=True),)), {"s": "nowa", "b": "jan"}
        ).ok

    def test_same_shift_type_in_week(self):
        slots = [slot("a", MON, shift_type="am"), slot("b", day(1), "14:00", "22:00", shift_type="pm")]
        p = problem([employee("anna")], slots, rules=(rule("same_shift_type_in_week"),))
        assert measure(validate(p, {"a": "anna", "b": "anna"}), "same_shift_type_in_week").degree == 1.0
        assert measure(validate(p, {"a": "anna"}), "same_shift_type_in_week").degree == 0.0

    def test_max_shifts_per_week(self):
        slots = [slot(f"d{i}", day(i)) for i in range(4)]
        p = problem([employee("anna")], slots, rules=(rule("max_shifts_per_week", hard=True, shifts=3),))
        assert not validate(p, {s.id: "anna" for s in slots}).ok
        assert validate(p, {"d0": "anna", "d1": "anna", "d2": "anna"}).ok

    def test_rules_apply_to_their_own_location_only(self):
        slots = [slot("a", MON, "14:00", "22:00"), slot("b", day(1), "08:00", "16:00")]
        p = problem(
            [employee("anna", home="loc-2")],
            slots,
            rules=(rule("min_rest_between_shifts", hard=True),),
        )
        assert validate(p, {"a": "anna", "b": "anna"}).ok


class TestCalendarRequests:
    def test_unmarked_day_is_not_a_request(self):
        # "Wolę nie" left the calendar (13.11.2026): an unmarked day, even a stored one, asks for nothing.
        p = problem([employee("anna")], [slot("a", MON)], availability=(Availability("anna", MON, "neutral"),))
        assert validate(p, {"a": "anna"}).requests == ()

    def test_prefer_days_count_against_days_actually_worked(self):
        availability = tuple(Availability("anna", day(i), "prefer") for i in range(4))
        slots = [slot(f"d{i}", day(i)) for i in range(6)]
        p = problem([employee("anna")], slots, availability=availability)
        assert validate(p, {"d0": "anna", "d1": "anna"}).requests[0].degree == 0.0  # both on liked days
        assert validate(p, {"d0": "anna", "d5": "anna"}).requests[0].degree == 0.5
        assert validate(p, {}).requests[0].degree == 0.0  # no shifts: nothing to place on liked days


class TestTextRequests:
    people = (employee("anna"), employee("ola"), employee("ewa"))
    slots = (slot("a1", MON), slot("o1", MON), slot("a2", day(1)), slot("e2", day(1)))

    def degree(self, request: Request, schedule) -> float | None:
        report = validate(problem(self.people, self.slots, requests=(request,)), schedule)
        texts = [r for r in report.requests if r.kind == RequestKind.TEXT]
        return texts[0].degree if texts else None

    def test_avoid_person(self):
        request = Request("r", "anna", "avoid_person", subject_employee="ola")
        assert self.degree(request, {"a1": "anna", "o1": "ola", "a2": "anna", "e2": "ewa"}) == 0.5
        assert self.degree(request, {"a1": "anna", "o1": "ewa", "a2": "anna", "e2": "ola"}) == 0.5
        assert self.degree(request, {"a1": "anna", "o1": "ewa", "a2": "ola"}) == 0.0

    def test_prefer_person_on_given_dates(self):
        request = Request("r", "anna", "prefer_person", subject_employee="ola", dates=frozenset({MON}))
        assert self.degree(request, {"a1": "anna", "o1": "ola", "a2": "anna", "e2": "ewa"}) == 0.0
        assert self.degree(request, {"a1": "anna", "o1": "ewa", "a2": "anna", "e2": "ola"}) == 1.0

    def test_shift_type(self):
        only_mornings = Request("r", "anna", "shift_type", shift_type="06:00-14:00")
        no_mornings = Request("r", "anna", "shift_type", shift_type="06:00-14:00", avoid=True)
        assert self.degree(only_mornings, {"a1": "anna"}) == 0.0
        assert self.degree(no_mornings, {"a1": "anna"}) == 1.0

    def test_days_off(self):
        request = Request("r", "anna", "days_off", dates=frozenset({MON, day(1)}))
        assert self.degree(request, {"o1": "ola", "e2": "ewa"}) == 0.0
        assert self.degree(request, {"a1": "anna"}) == 0.5
        assert self.degree(request, {"a1": "anna", "a2": "anna"}) == 1.0
        assert self.degree(Request("r", "anna", "days_off"), {"a1": "anna"}) is None  # no dates: for the manager

    def test_hours_limit(self):
        request = Request("r", "anna", "hours_limit", max_hours=8)
        assert self.degree(request, {"a1": "anna"}) == 0.0
        assert self.degree(request, {"a1": "anna", "a2": "anna"}) == 1.0

    def test_other_requests_are_left_to_the_manager(self):
        request = Request("r", "anna", "other", summary="Chcę mieć wolne w urodziny")
        assert self.degree(request, {}) is None
        assert validate(problem(self.people, self.slots, requests=(request,)), {}).unscored_requests == ("r",)

    def test_weight_follows_level_and_manager_priority(self):
        request = Request("r", "anna", "hours_limit", max_hours=8, level="bardzo_wazne", manager_priority="lower")
        report = validate(problem(self.people, self.slots, requests=(request,)), {})
        assert report.requests[0].weight == 4.5
