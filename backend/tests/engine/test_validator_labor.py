"""Employment contract (umowa o pracę): 11 h rest, max 8 h a day, 35 h weekly rest; to the minute and across DST.

The same schedules for a civil contract (umowa zlecenie) are valid: these limits are hard only for employment.
"""

from datetime import date, time, timedelta

import pytest

from engine.problem import ExternalShift, shift_bounds
from engine.validator import Code, validate
from tests.engine.factory import employee, problem, slot

MON = date(2026, 11, 16)


def check(contract: str, slots, **kwargs):
    p = problem([employee("anna", contract=contract)], slots, **kwargs)
    return validate(p, {s.id: "anna" for s in slots})


def hard_codes(report):
    return sorted({v.code for v in report.hard})


def days(n: int):
    return [MON + timedelta(days=i) for i in range(n)]


class TestDailyRest:
    def test_exactly_11_hours_is_enough(self):
        slots = [slot("a", MON, "06:00", "14:00"), slot("b", MON + timedelta(days=1), "01:00", "05:00")]
        assert check("employment", slots).ok

    def test_one_minute_short_is_a_violation(self):
        slots = [slot("a", MON, "06:00", "14:00"), slot("b", MON + timedelta(days=1), "00:59", "05:00")]
        report = check("employment", slots)
        assert hard_codes(report) == [Code.LABOR_DAILY_REST]
        assert "10 h 59 min" in report.hard[0].message
        assert check("civil", slots).ok

    def test_rest_after_overnight_shift(self):
        slots = [slot("night", MON, "22:00", "06:00"), slot("next", MON + timedelta(days=1), "16:00", "22:00")]
        assert hard_codes(check("employment", slots)) == [Code.LABOR_DAILY_REST]  # 06:00 -> 16:00 = 10 h
        slots[1] = slot("next", MON + timedelta(days=1), "17:00", "22:00")
        assert check("employment", slots).ok

    def test_rest_counts_real_hours_when_clocks_go_back(self):
        # 20:00 -> 06:00 is 10 h on the wall clock but 11 h in reality on the night of 24/25 October 2026.
        slots = [slot("a", date(2026, 10, 24), "12:00", "20:00"), slot("b", date(2026, 10, 25), "06:00", "14:00")]
        assert check("employment", slots).ok

    def test_rest_counts_real_hours_when_clocks_go_forward(self):
        # 19:00 -> 06:00 is 11 h on the wall clock but only 10 h in reality on the night of 28/29 March 2026.
        slots = [slot("a", date(2026, 3, 28), "11:00", "19:00"), slot("b", date(2026, 3, 29), "06:00", "14:00")]
        assert hard_codes(check("employment", slots)) == [Code.LABOR_DAILY_REST]
        assert check("civil", slots).ok

    def test_rest_after_a_shift_from_the_previous_period(self):
        start, end = shift_bounds(MON - timedelta(days=1), time(16), time(23))
        external = (ExternalShift("anna", MON - timedelta(days=1), start, end),)
        report = check("employment", [slot("a", MON, "06:00", "14:00")], external_shifts=external)
        assert hard_codes(report) == [Code.LABOR_DAILY_REST]
        assert report.hard[0].slots == ("a",)


class TestDailyHours:
    def test_exactly_8_hours_is_allowed(self):
        assert check("employment", [slot("a", MON, "06:00", "14:00")]).ok

    def test_more_than_8_hours(self):
        slots = [slot("a", MON, "06:00", "14:30")]
        assert hard_codes(check("employment", slots)) == [Code.LABOR_DAILY_HOURS]
        assert check("civil", [slot("a", MON, "06:00", "18:00")]).ok

    def test_two_shifts_in_one_day_add_up(self):
        slots = [slot("a", MON, "00:00", "04:00"), slot("b", MON, "15:00", "20:00")]  # 11 h rest between, 9 h total
        assert hard_codes(check("employment", slots)) == [Code.LABOR_DAILY_HOURS]

    def test_night_shift_is_9_hours_when_clocks_go_back(self):
        assert hard_codes(check("employment", [slot("n", date(2026, 10, 24), "22:00", "06:00")])) == [
            Code.LABOR_DAILY_HOURS
        ]

    def test_night_shift_is_8_hours_when_clocks_go_forward(self):
        assert check("employment", [slot("n", date(2026, 3, 28), "22:00", "07:00")]).ok


class TestWeeklyRest:
    def test_five_days_monday_to_friday_is_fine(self):
        assert check("employment", [slot(f"d{i}", d, "08:00", "16:00") for i, d in enumerate(days(5))]).ok

    def test_six_days_leave_only_32_hours(self):
        slots = [slot(f"d{i}", d, "08:00", "16:00") for i, d in enumerate(days(6))]
        report = check("employment", slots)
        assert hard_codes(report) == [Code.LABOR_WEEKLY_REST]
        assert "32 h" in report.hard[0].message
        assert check("civil", slots).ok

    def test_exactly_35_hours_is_enough(self):
        # Mon–Fri 08–16 and Sat 08:00–13:00: Saturday 13:00 -> Monday 00:00 = 35 h.
        slots = [slot(f"d{i}", d, "08:00", "16:00") for i, d in enumerate(days(5))]
        slots.append(slot("sat", MON + timedelta(days=5), "08:00", "13:00"))
        assert check("employment", slots).ok
        slots[-1] = slot("sat", MON + timedelta(days=5), "08:00", "13:01")
        assert hard_codes(check("employment", slots)) == [Code.LABOR_WEEKLY_REST]

    def test_week_with_clocks_going_back_has_an_extra_hour(self):
        # Week 19–25 October 2026 is 169 h long: Saturday 14:00 -> Monday 00:00 is 35 h only thanks to DST.
        week = [date(2026, 10, 19) + timedelta(days=i) for i in range(6)]
        slots = [slot(f"d{i}", d, "06:00", "14:00") for i, d in enumerate(week)]
        assert check("employment", slots, start=week[0], end=date(2026, 10, 25)).ok
        ordinary = [slot(f"d{i}", d, "06:00", "14:00") for i, d in enumerate(days(6))]
        assert hard_codes(check("employment", ordinary)) == [Code.LABOR_WEEKLY_REST]  # 34 h in a 168 h week

    def test_rest_is_checked_within_each_week_with_known_shifts(self):
        # Only Monday in this period, but the previous period's Sunday shift is known: still plenty of rest.
        start, end = shift_bounds(MON - timedelta(days=1), time(8), time(16))
        external = (ExternalShift("anna", MON - timedelta(days=1), start, end),)
        assert check("employment", [slot("a", MON, "08:00", "16:00")], external_shifts=external).ok


@pytest.mark.parametrize("contract", ["civil", "employment"])
def test_one_ordinary_week_is_valid_for_both_contracts(contract):
    slots = [slot(f"d{i}", d, "06:00", "14:00") for i, d in enumerate(days(5))]
    assert check(contract, slots).ok
