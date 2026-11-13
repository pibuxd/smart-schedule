"""Work-time rules the manager can switch on (there is no contract type or built-in labour law):
"Odpoczynek między zmianami", "Godziny pracy w ciągu dnia" and "Wolne w tygodniu"; to the minute and across DST.

Without these rules the same schedules are valid.
"""

from datetime import date, time, timedelta

from engine.problem import ExternalShift, RuleConfig, shift_bounds
from engine.validator import Code, validate
from tests.engine.factory import LOC, employee, problem, slot

MON = date(2026, 11, 16)

REST = RuleConfig("min_rest_between_shifts", LOC, 1, hard=True, params={"hours": 11})
DAY_HOURS = RuleConfig("max_hours_per_day", LOC, 1, hard=True, params={"max_hours": 8})
WEEK_REST = RuleConfig("min_weekly_rest", LOC, 1, hard=True, params={"rest_hours": 35})


def check(rule: RuleConfig | None, slots, **kwargs):
    p = problem([employee("anna")], slots, rules=(rule,) if rule else (), **kwargs)
    return validate(p, {s.id: "anna" for s in slots})


def hard_rules(report):
    return sorted({v.rule_code for v in report.hard})


def days(n: int):
    return [MON + timedelta(days=i) for i in range(n)]


class TestDailyRest:
    def test_exactly_11_hours_is_enough(self):
        slots = [slot("a", MON, "06:00", "14:00"), slot("b", MON + timedelta(days=1), "01:00", "05:00")]
        assert check(REST, slots).ok

    def test_one_minute_short_is_a_violation(self):
        slots = [slot("a", MON, "06:00", "14:00"), slot("b", MON + timedelta(days=1), "00:59", "05:00")]
        report = check(REST, slots)
        assert hard_rules(report) == ["min_rest_between_shifts"]
        assert report.hard[0].code == Code.RULE
        assert "10 h 59 min" in report.hard[0].message
        assert check(None, slots).ok

    def test_rest_counts_real_hours_when_clocks_go_forward(self):
        # 19:00 -> 06:00 is 11 h on the wall clock but only 10 h in reality on the night of 28/29 March 2026.
        slots = [slot("a", date(2026, 3, 28), "11:00", "19:00"), slot("b", date(2026, 3, 29), "06:00", "14:00")]
        assert hard_rules(check(REST, slots)) == ["min_rest_between_shifts"]

    def test_rest_after_a_shift_from_the_previous_period(self):
        start, end = shift_bounds(MON - timedelta(days=1), time(16), time(23))
        external = (ExternalShift("anna", MON - timedelta(days=1), start, end),)
        report = check(REST, [slot("a", MON, "06:00", "14:00")], external_shifts=external)
        assert hard_rules(report) == ["min_rest_between_shifts"]
        assert report.hard[0].slots == ("a",)


class TestDailyHours:
    def test_exactly_8_hours_is_allowed(self):
        assert check(DAY_HOURS, [slot("a", MON, "06:00", "14:00")]).ok

    def test_more_than_8_hours(self):
        report = check(DAY_HOURS, [slot("a", MON, "06:00", "14:30")])
        assert hard_rules(report) == ["max_hours_per_day"]
        assert "8 h 30 min" in report.hard[0].message
        assert check(None, [slot("a", MON, "06:00", "18:00")]).ok

    def test_two_shifts_in_one_day_add_up(self):
        slots = [slot("a", MON, "00:00", "04:00"), slot("b", MON, "15:00", "20:00")]
        assert hard_rules(check(DAY_HOURS, slots)) == ["max_hours_per_day"]

    def test_limit_is_a_parameter(self):
        rule = RuleConfig("max_hours_per_day", LOC, 1, hard=True, params={"max_hours": 10})
        assert check(rule, [slot("a", MON, "06:00", "16:00")]).ok

    def test_night_shift_is_9_hours_when_clocks_go_back(self):
        assert hard_rules(check(DAY_HOURS, [slot("n", date(2026, 10, 24), "22:00", "06:00")])) == ["max_hours_per_day"]

    def test_night_shift_is_8_hours_when_clocks_go_forward(self):
        assert check(DAY_HOURS, [slot("n", date(2026, 3, 28), "22:00", "07:00")]).ok

    def test_soft_rule_measures_share_of_days(self):
        slots = [slot("a", MON, "06:00", "16:00"), slot("b", MON + timedelta(days=1), "06:00", "14:00")]
        soft = RuleConfig("max_hours_per_day", LOC, 1, params={"max_hours": 8})
        report = check(soft, slots)
        assert report.ok
        (measure,) = report.rules
        assert (measure.instances, measure.degree, len(measure.violations)) == (2, 0.5, 1)


class TestWeeklyRest:
    def test_five_days_monday_to_friday_is_fine(self):
        assert check(WEEK_REST, [slot(f"d{i}", d, "08:00", "16:00") for i, d in enumerate(days(5))]).ok

    def test_six_days_leave_only_32_hours(self):
        slots = [slot(f"d{i}", d, "08:00", "16:00") for i, d in enumerate(days(6))]
        report = check(WEEK_REST, slots)
        assert hard_rules(report) == ["min_weekly_rest"]
        assert "32 h" in report.hard[0].message
        assert check(None, slots).ok

    def test_exactly_35_hours_is_enough(self):
        # Mon–Fri 08–16 and Sat 08:00–13:00: Saturday 13:00 -> Monday 00:00 = 35 h.
        slots = [slot(f"d{i}", d, "08:00", "16:00") for i, d in enumerate(days(5))]
        slots.append(slot("sat", MON + timedelta(days=5), "08:00", "13:00"))
        assert check(WEEK_REST, slots).ok
        slots[-1] = slot("sat", MON + timedelta(days=5), "08:00", "13:01")
        assert hard_rules(check(WEEK_REST, slots)) == ["min_weekly_rest"]

    def test_week_with_clocks_going_back_has_an_extra_hour(self):
        # Week 19–25 October 2026 is 169 h long: Saturday 14:00 -> Monday 00:00 is 35 h only thanks to DST.
        week = [date(2026, 10, 19) + timedelta(days=i) for i in range(6)]
        slots = [slot(f"d{i}", d, "06:00", "14:00") for i, d in enumerate(week)]
        assert check(WEEK_REST, slots, start=week[0], end=date(2026, 10, 25)).ok
        ordinary = [slot(f"d{i}", d, "06:00", "14:00") for i, d in enumerate(days(6))]
        assert hard_rules(check(WEEK_REST, ordinary)) == ["min_weekly_rest"]  # 34 h in a 168 h week

    def test_rest_is_checked_within_each_week_with_known_shifts(self):
        # Only Monday in this period, but the previous period's Sunday shift is known: still plenty of rest.
        start, end = shift_bounds(MON - timedelta(days=1), time(8), time(16))
        external = (ExternalShift("anna", MON - timedelta(days=1), start, end),)
        assert check(WEEK_REST, [slot("a", MON, "08:00", "16:00")], external_shifts=external).ok


def test_touching_shifts_are_fine_without_rules():
    slots = [slot("s1", MON, "06:00", "14:00"), slot("s2", MON, "14:00", "22:00")]
    assert check(None, slots).ok
    assert hard_rules(check(DAY_HOURS, slots)) == ["max_hours_per_day"]
    assert hard_rules(check(REST, slots)) == ["min_rest_between_shifts"]
