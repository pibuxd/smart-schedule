"""The problem description: shift times across midnight and DST, availability windows, input checks."""

from datetime import UTC, date, datetime, time

import pytest

from engine.problem import (
    Availability,
    ExternalShift,
    ManagerPriority,
    Problem,
    ProblemError,
    Request,
    RequestLevel,
    RuleConfig,
    Slot,
    WeightProfile,
    shift_bounds,
)
from engine.rules_catalog import RULES
from tests.engine.factory import LOC, employee, problem, slot

SPRING_FORWARD = date(2026, 3, 29)  # 02:00 -> 03:00 in Warsaw
FALL_BACK = date(2026, 10, 25)  # 03:00 -> 02:00 in Warsaw


def test_overnight_shift_ends_next_day():
    start, end = shift_bounds(date(2026, 11, 13), time(22), time(6))
    assert (start.day, end.day) == (13, 14)
    assert (end - start).total_seconds() == 8 * 3600


def test_shift_hours_are_real_hours_across_dst():
    assert slot("s", date(2026, 3, 28), "22:00", "06:00").hours == 7  # night the clock jumps forward
    assert slot("s", date(2026, 10, 24), "22:00", "06:00").hours == 9  # night the clock goes back
    assert slot("s", date(2026, 11, 13), "22:00", "06:00").hours == 8


def test_time_skipped_by_dst_moves_forward_an_hour():
    start, _ = shift_bounds(SPRING_FORWARD, time(2, 30), time(10))
    assert start.astimezone(UTC) == datetime(2026, 3, 29, 1, 30, tzinfo=UTC)  # = 03:30 local
    assert start.astimezone(start.tzinfo).hour == 3


def test_slot_needs_aware_times_and_positive_length():
    naive = datetime(2026, 11, 13, 6)
    with pytest.raises(ProblemError):
        Slot("s", LOC, date(2026, 11, 13), "t", "p", naive, naive)
    good = slot("s", date(2026, 11, 13))
    with pytest.raises(ProblemError):
        Slot("s", LOC, good.date, "t", "p", good.end, good.start)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"employees": (employee("a"), employee("a"))}, "Duplicate employee"),
        ({"slots": (slot("s", date(2026, 11, 2)), slot("s", date(2026, 11, 3)))}, "Duplicate slot"),
        ({"availability": (Availability("ghost", date(2026, 11, 2), "cannot"),)}, "Unknown employee"),
        ({"requests": (Request("r", "a", "avoid_person", subject_employee="ghost"),)}, "unknown subject"),
        ({"pinned": {"s1": "ghost"}}, "Pin"),
        (
            {"rules": (RuleConfig("max_consecutive_days", LOC, 1), RuleConfig("max_consecutive_days", LOC, 2))},
            "twice",
        ),
        (
            {
                "external_shifts": (
                    ExternalShift("ghost", date(2026, 11, 1), *shift_bounds(date(2026, 11, 1), time(6), time(14))),
                )
            },
            "Unknown employee",
        ),
    ],
)
def test_inconsistent_problem_is_rejected(kwargs, message):
    base = {"employees": (employee("a"),), "slots": (slot("s1", date(2026, 11, 2)),)}
    with pytest.raises(ProblemError, match=message):
        problem(**{**base, **kwargs})


def test_slot_outside_period_is_rejected():
    with pytest.raises(ProblemError, match="outside"):
        problem([employee("a")], [slot("s", date(2026, 11, 9))], start=date(2026, 11, 2), end=date(2026, 11, 8))


def test_rule_config_accepts_only_catalog_rules_and_params():
    with pytest.raises(ProblemError, match="Unknown rule"):
        RuleConfig("no_such_rule", LOC, 1)
    with pytest.raises(ProblemError, match="Nieznany parametr"):
        RuleConfig("min_rest_between_shifts", LOC, 1, params={"minutes": 5})
    assert RuleConfig("min_rest_between_shifts", LOC, 1).params == {"hours": 11}
    assert RuleConfig("min_rest_between_shifts", LOC, 1, params={"hours": 12}).params == {"hours": 12}


def test_rule_weights_fall_with_place_on_the_list():
    weights = WeightProfile(rank_decay=0.5)
    assert [weights.rule_weight(place) for place in (1, 2, 3)] == [1.0, 0.5, 0.25]


def test_request_weight_combines_level_and_manager_priority():
    weights = WeightProfile()
    assert weights.request_weight(RequestLevel.VERY_IMPORTANT) == 9.0
    assert weights.request_weight(RequestLevel.IMPORTANT, ManagerPriority.HIGHER) == 6.0
    assert weights.request_weight(RequestLevel.NICE_TO_HAVE, ManagerPriority.LOWER) == 0.5


def test_default_level_weights_match_the_django_model():
    from apps.rules.models import default_level_weights

    assert dict(WeightProfile().level_weights) == default_level_weights()


def test_every_catalog_rule_is_measured_by_the_validator():
    from engine.validator import _Checker

    assert [r.code for r in RULES if not hasattr(_Checker, f"rule_{r.code}")] == []


def test_every_catalog_rule_is_modelled_in_the_solver():
    from engine.solver import _Builder

    assert [r.code for r in RULES if not hasattr(_Builder, f"_rule_{r.code}")] == []


class TestAvailability:
    day = date(2026, 11, 13)

    def state(self, entry: Availability, shift: Slot) -> str:
        p: Problem = problem([employee("a")], [shift], availability=(entry,))
        return p.availability_for("a", shift)

    def test_whole_day_entry_covers_every_shift_starting_that_day(self):
        entry = Availability("a", self.day, "cannot")
        assert self.state(entry, slot("s", self.day, "22:00", "06:00")) == "cannot"

    def test_overnight_shift_belongs_to_the_day_it_starts(self):
        entry = Availability("a", date(2026, 11, 14), "cannot")
        night = slot("s", self.day, "22:00", "06:00")
        p = problem([employee("a")], [night], end=date(2026, 11, 14), availability=(entry,))
        assert p.availability_for("a", night) == "neutral"

    def test_cannot_with_hours_applies_only_to_overlapping_shifts(self):
        entry = Availability("a", self.day, "cannot", from_time=time(14))
        assert self.state(entry, slot("s", self.day, "06:00", "14:00")) == "neutral"  # ends exactly at 14:00
        assert self.state(entry, slot("s", self.day, "06:00", "14:01")) == "cannot"
        assert self.state(entry, slot("s", self.day, "22:00", "06:00")) == "cannot"

    def test_prefer_with_hours_means_only_inside_the_window(self):
        entry = Availability("a", self.day, "prefer", from_time=time(14), to_time=time(22))
        assert self.state(entry, slot("s", self.day, "14:00", "22:00")) == "prefer"
        assert self.state(entry, slot("s", self.day, "13:00", "21:00")) == "cannot"

    def test_neutral_with_hours_means_only_inside_the_window(self):
        entry = Availability("a", self.day, "neutral", to_time=time(12))
        assert self.state(entry, slot("s", self.day, "06:00", "12:00")) == "neutral"
        assert self.state(entry, slot("s", self.day, "06:00", "14:00")) == "cannot"

    def test_window_ending_before_it_starts_runs_into_the_next_morning(self):
        entry = Availability("a", self.day, "prefer", from_time=time(22), to_time=time(6))
        assert self.state(entry, slot("s", self.day, "22:00", "06:00")) == "prefer"
        assert self.state(entry, slot("s", self.day, "06:00", "14:00")) == "cannot"
        nights = Availability("a", self.day, "cannot", from_time=time(20), to_time=time(4))
        assert self.state(nights, slot("s", self.day, "22:00", "06:00")) == "cannot"
        assert self.state(nights, slot("s", self.day, "06:00", "14:00")) == "neutral"

    def test_hours_must_not_be_an_empty_window(self):
        with pytest.raises(ProblemError):
            Availability("a", self.day, "cannot", from_time=time(14), to_time=time(14))
