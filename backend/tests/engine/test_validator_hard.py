"""Hard rules for everyone: position, "cannot", overlaps, pins, frozen days, unknown ids."""

from dataclasses import replace
from datetime import date, time

import pytest

from engine.problem import Availability, ExternalShift, ProblemError, shift_bounds
from engine.validator import Code, validate
from tests.engine.factory import BAKER, employee, problem, slot

DAY = date(2026, 11, 16)  # Monday


def codes(report):
    return sorted(v.code for v in report.hard)


def test_valid_schedule_has_no_violations():
    p = problem([employee("anna")], [slot("s1", DAY)])
    report = validate(p, {"s1": "anna"})
    assert report.ok
    assert report.holes == ()
    assert report.hours == {"anna": 8.0}


def test_unfilled_slot_is_a_hole_not_a_violation():
    p = problem([employee("anna")], [slot("s1", DAY), slot("s2", DAY, "14:00", "22:00")])
    report = validate(p, {"s1": "anna", "s2": None})
    assert report.ok
    assert report.holes == ("s2",)
    assert validate(p, {"s1": "anna"}).holes == ("s2",)  # a missing key is a hole too


def test_wrong_position():
    p = problem([employee("anna")], [slot("s1", DAY, position=BAKER)], position_names={BAKER: "Piekarz"})
    report = validate(p, {"s1": "anna"})
    assert codes(report) == [Code.POSITION]
    assert "Piekarz" in report.hard[0].message


def test_cannot_day():
    p = problem([employee("anna")], [slot("s1", DAY)], availability=(Availability("anna", DAY, "cannot"),))
    report = validate(p, {"s1": "anna"})
    assert codes(report) == [Code.CANNOT]
    assert report.hard[0].employee == "anna"
    assert report.hard[0].slots == ("s1",)


def test_cannot_from_given_hour_allows_a_shift_ending_at_that_hour():
    p = problem(
        [employee("anna")],
        [slot("s1", DAY, "06:00", "14:00"), slot("s2", DAY + date.resolution, "06:00", "14:30")],
        availability=(
            Availability("anna", DAY, "cannot", from_time=time(14)),
            Availability("anna", DAY + date.resolution, "cannot", from_time=time(14)),
        ),
    )
    report = validate(p, {"s1": "anna", "s2": "anna"})
    assert [v.slots for v in report.hard] == [("s2",)]


def test_overlapping_shifts():
    p = problem(
        [employee("anna")],
        [slot("s1", DAY, "06:00", "14:00"), slot("s2", DAY, "13:00", "21:00", location="loc-2")],
    )
    report = validate(p, {"s1": "anna", "s2": "anna"})
    assert Code.OVERLAP in codes(report)


def test_touching_shifts_do_not_overlap():
    p = problem([employee("anna")], [slot("s1", DAY, "06:00", "14:00"), slot("s2", DAY, "14:00", "22:00")])
    assert validate(p, {"s1": "anna", "s2": "anna"}).ok


def test_overnight_shift_overlaps_next_morning():
    p = problem(
        [employee("anna")],
        [slot("night", DAY, "22:00", "06:00"), slot("morning", DAY + date.resolution, "05:00", "13:00")],
    )
    report = validate(p, {"night": "anna", "morning": "anna"})
    assert codes(report) == [Code.OVERLAP]
    assert set(report.hard[0].slots) == {"night", "morning"}


def test_overlap_with_a_shift_outside_the_problem():
    start, end = shift_bounds(DAY, time(10), time(18))
    p = problem(
        [employee("anna")],
        [slot("s1", DAY)],
        external_shifts=(ExternalShift("anna", DAY, start, end, label="Lokal 2"),),
    )
    report = validate(p, {"s1": "anna"})
    assert codes(report) == [Code.OVERLAP]
    assert "Lokal 2" in report.hard[0].message
    assert report.hard[0].slots == ("s1",)


def test_pinned_slot_must_keep_its_person():
    p = problem([employee("anna"), employee("ola")], [slot("s1", DAY)], pinned={"s1": "anna"})
    assert validate(p, {"s1": "anna"}).ok
    assert codes(validate(p, {"s1": "ola"})) == [Code.PINNED]
    assert codes(validate(p, {"s1": None})) == [Code.PINNED]


def test_days_that_passed_are_frozen():
    yesterday, today = DAY, DAY + date.resolution
    p = problem(
        [employee("anna"), employee("ola")],
        [slot("old", yesterday), slot("new", today)],
        published={"old": "anna", "new": "anna"},
        frozen_before=today,
    )
    assert validate(p, {"old": "anna", "new": "ola"}).ok
    assert codes(validate(p, {"old": "ola", "new": "anna"})) == [Code.FROZEN]
    assert codes(validate(p, {"old": None, "new": "anna"})) == [Code.FROZEN]


def test_a_pin_on_a_day_that_passed_is_the_managers_correction():
    yesterday, today = DAY, DAY + date.resolution
    p = problem(
        [employee("anna"), employee("ola")],
        [slot("old", yesterday), slot("new", today)],
        published={"old": "anna", "new": "anna"},
        pinned={"old": "ola"},
        frozen_before=today,
    )
    assert validate(p, {"old": "ola", "new": "anna"}).ok


def test_forced_person_turns_hard_problems_into_waived_ones():
    slots = [slot("s1", DAY), slot("s2", DAY, "10:00", "18:00")]
    p = problem(
        [employee("anna"), employee("ola")],
        slots,
        availability=(Availability("anna", DAY, "cannot"),),
        forced={"s1": "anna", "s2": "anna"},
    )
    report = validate(p, {"s1": "anna", "s2": "anna"})
    # "Nie mogę" is overruled; two shifts at the same time never are.
    assert codes(report) == [Code.OVERLAP]
    assert sorted(v.code for v in report.waived) == [Code.CANNOT, Code.CANNOT]
    assert validate(p, {"s1": "anna"}).ok
    # The override is about that person only: someone else on the slot is checked as usual.
    other = replace(p, availability=(Availability("ola", DAY, "cannot"),))
    assert codes(validate(other, {"s1": "ola"})) == [Code.CANNOT]
    # The position cannot be overruled.
    baker = replace(p, slots=(slot("s1", DAY, position=BAKER), slots[1]), availability=(), forced={"s1": "anna"})
    assert codes(validate(baker, {"s1": "anna"})) == [Code.POSITION]


def test_changes_against_published_schedule_are_counted():
    p = problem(
        [employee("anna"), employee("ola")],
        [slot("s1", DAY), slot("s2", DAY, "14:00", "22:00"), slot("s3", DAY + date.resolution)],
        published={"s1": "anna", "s2": None},
    )
    report = validate(p, {"s1": "ola", "s2": "anna", "s3": "anna"})
    assert report.stability_changes == ("s1", "s2")  # s3 is new, not a change


def test_unknown_ids_in_schedule_are_reported_not_raised():
    p = problem([employee("anna")], [slot("s1", DAY)])
    report = validate(p, {"s1": "ghost", "nope": "anna"})
    assert codes(report) == [Code.UNKNOWN_EMPLOYEE, Code.UNKNOWN_SLOT]
    assert report.holes == ("s1",)


# ----------------------------------------------------------------- staffing "of these, N experienced"


def _pair(need: int = 1):
    first, second = slot("s1", DAY), slot("s2", DAY)
    marked = [replace(s, needs_experienced=i < need) for i, s in enumerate((first, second))]
    people = [employee("stara", experience=3), employee("ola"), employee("nowa", experience=1)]
    return problem(people, marked)


def test_less_experienced_people_may_not_take_the_experienced_place():
    report = validate(_pair(), {"s1": "ola", "s2": "nowa"})
    assert codes(report) == [Code.EXPERIENCE]
    assert "ma być doświadczona osoba" in report.hard[0].message
    assert "Ola" in report.hard[0].message and "Nowa" in report.hard[0].message


def test_it_does_not_matter_which_place_the_experienced_person_stands_on():
    assert validate(_pair(), {"s1": "ola", "s2": "stara"}).ok
    assert validate(_pair(), {"s1": "stara", "s2": "ola"}).ok


def test_a_hole_is_fine_while_the_experienced_place_is_still_free():
    assert validate(_pair(), {"s1": "ola", "s2": None}).ok
    assert validate(_pair(), {"s1": None, "s2": "nowa"}).ok
    assert codes(validate(_pair(need=2), {"s1": "ola"})) == [Code.EXPERIENCE]


def test_the_level_on_the_position_of_the_shift_counts():
    oven = replace(slot("b", DAY, position=BAKER), needs_experienced=True)
    # Experienced in general, but a beginner at the oven.
    jan = employee("jan", positions=("sales", BAKER), experience=3, experience_by_position={BAKER: 1})
    ewa = employee("ewa", positions=("sales", BAKER), experience_by_position={BAKER: 3})
    p = problem([jan, ewa], [oven])
    assert codes(validate(p, {"b": "jan"})) == [Code.EXPERIENCE]
    assert validate(p, {"b": "ewa"}).ok


class TestTwoWindows:
    """ "Mogę 6–10 lub 16–22" and the same with "albo" (at most one shift that day)."""

    def slots(self):
        return [
            slot("rano", DAY, "06:00", "10:00"),
            slot("poludnie", DAY, "11:00", "15:00"),
            slot("wieczor", DAY, "16:00", "22:00"),
        ]

    def entry(self, **kwargs):
        return Availability(
            "anna",
            DAY,
            "neutral",
            from_time=time(6),
            to_time=time(10),
            from_time_2=time(16),
            to_time_2=time(22),
            **kwargs,
        )

    def test_a_shift_fits_either_window(self):
        p = problem([employee("anna")], self.slots(), availability=(self.entry(),))
        assert validate(p, {"rano": "anna", "wieczor": "anna"}).ok
        report = validate(p, {"poludnie": "anna"})
        assert [v.code for v in report.hard] == [Code.CANNOT]

    def test_albo_allows_one_shift_that_day(self):
        p = problem([employee("anna")], self.slots(), availability=(self.entry(one_shift=True),))
        assert validate(p, {"wieczor": "anna"}).ok
        report = validate(p, {"rano": "anna", "wieczor": "anna"})
        assert [v.code for v in report.hard] == [Code.ONE_SHIFT]
        assert "tylko na jednej zmianie" in report.hard[0].message

    def test_cannot_covers_both_windows(self):
        entry = Availability(
            "anna", DAY, "cannot", from_time=time(6), to_time=time(10), from_time_2=time(16), to_time_2=time(22)
        )
        p = problem([employee("anna")], self.slots(), availability=(entry,))
        assert validate(p, {"poludnie": "anna"}).ok
        assert not validate(p, {"wieczor": "anna"}).ok

    def test_a_second_window_needs_both_ends(self):
        with pytest.raises(ProblemError):
            Availability("anna", DAY, "neutral", from_time=time(6), to_time=time(10), from_time_2=time(16))
        with pytest.raises(ProblemError):
            Availability("anna", DAY, "neutral", from_time_2=time(16), to_time_2=time(20))
