"""Quick explanations of one slot and the list of people who could take it."""

from dataclasses import replace
from datetime import date

from engine.explain import explain_slot
from engine.problem import Availability, AvailabilityState, Request, RuleConfig
from tests.engine.factory import BAKER, LOC, employee, problem, slot

MON = date(2026, 11, 2)
TUE = date(2026, 11, 3)


def by_id(explanation):
    return {c.employee: c for c in explanation.candidates}


def test_empty_slot_names_why_nobody_could_take_it():
    p = problem(
        [employee("anna"), employee("ewa"), employee("jan", positions=(BAKER,))],
        [slot("a", MON), slot("b", MON, "08:00", "16:00")],
        availability=(Availability("anna", MON, AvailabilityState.CANNOT),),
    )

    explanation = explain_slot(p, {"a": "ewa", "b": None}, "b")

    people = by_id(explanation)
    assert set(people) == {"anna", "ewa"}  # Jan bakes, he is not a candidate for the shop
    assert people["anna"].blocked and "nie mogę" in people["anna"].blocked[0]
    assert people["ewa"].blocked and "dwie zmiany" in people["ewa"].blocked[0]
    assert explanation.summary.startswith("Nikt nie mógł wziąć tej zmiany")
    assert "zaznaczone „nie mogę” (1 osoba)" in explanation.summary
    assert "inna zmiana w tym czasie (1 osoba)" in explanation.summary


def test_empty_slot_says_the_staffing_asks_for_an_experienced_person():
    p = problem([employee("anna"), employee("ewa", experience=1)], [replace(slot("a", MON), needs_experienced=True)])
    explanation = explain_slot(p, {"a": None}, "a")
    assert "obsada wymaga tu doświadczonej osoby (2 osoby)" in explanation.summary
    assert all("ma być doświadczona osoba" in c.blocked[0] for c in explanation.candidates)


def test_assigned_slot_lists_the_person_first_and_who_else_could_work():
    p = problem(
        [employee("anna", target_hours_month=40), employee("ewa"), employee("ola")],
        [slot("a", MON)],
        availability=(Availability("anna", MON, AvailabilityState.PREFER),),
        requests=(Request("off", "ola", "days_off", dates=frozenset({MON})),),
    )

    explanation = explain_slot(p, {"a": "anna"}, "a")

    first, *rest = explanation.candidates
    assert first.employee == "anna" and first.current and first.possible
    assert [c.employee for c in rest] == ["ewa", "ola"]
    assert rest[1].wish == AvailabilityState.NEUTRAL  # Ola asked in words for this day off
    assert rest[1].scores.employee_requests < first.scores.employee_requests
    assert "Anna chętnie pracuje tego dnia" in explanation.summary
    assert "cel na miesiąc: 40 h" in explanation.summary
    assert "jeszcze 2 osoby" in explanation.summary


def test_a_pinned_slot_does_not_block_other_people():
    p = problem([employee("anna"), employee("ewa")], [slot("a", MON)], pinned={"a": "anna"})

    explanation = explain_slot(p, {"a": "anna"}, "a")

    assert by_id(explanation)["ewa"].possible


def test_soft_rule_costs_are_shown_as_notes():
    p = problem(
        [employee("anna"), employee("ewa")],
        [slot("late", MON, "14:00", "22:00"), slot("early", TUE, "06:00", "14:00")],
        rules=(RuleConfig("min_rest_between_shifts", LOC, rank=1, params={"hours": 11}),),
    )

    explanation = explain_slot(p, {"late": "anna", "early": "ewa"}, "early")

    anna = by_id(explanation)["anna"]
    assert anna.possible
    assert anna.notes and "przerwy" in anna.notes[0]
    assert anna.scores.manager_rules < by_id(explanation)["ewa"].scores.manager_rules


def test_inactive_people_are_left_out_unless_they_work_the_slot():
    p = problem([employee("anna", available=False), employee("ewa", available=False)], [slot("a", MON)])

    explanation = explain_slot(p, {"a": "anna"}, "a")

    assert [c.employee for c in explanation.candidates] == ["anna"]


def test_nobody_with_the_position():
    p = problem([employee("jan", positions=(BAKER,))], [slot("a", MON)], position_names={"sales": "Sprzedawca"})

    explanation = explain_slot(p, {}, "a")

    assert explanation.candidates == ()
    assert "Nikt w tym lokalu nie pracuje na stanowisku Sprzedawca" in explanation.summary
