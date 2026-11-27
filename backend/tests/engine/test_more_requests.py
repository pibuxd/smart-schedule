"""Request types added on 27.11.2026 (docs/plan.md section 48): the validator's degree and what the generator does.
No database needed."""

from dataclasses import replace
from datetime import date, time, timedelta

import pytest

from engine.problem import Availability, AvailabilityState, ExternalShift, Request, shift_bounds
from engine.solver import SolveStatus, solve
from engine.validator import validate
from tests.engine.factory import BAKER, SALES, employee, problem, slot

MON = date(2026, 11, 2)  # a Monday
FAST = {"time_limit_s": 5, "workers": 1}  # one worker: the same search every run


def day(n: int) -> date:
    return MON + timedelta(days=n)


def solved(p):
    result = solve(p, **FAST)
    assert result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE), result.messages
    report = validate(p, result.schedule)
    assert report.ok, [v.message for v in report.hard]
    return result.schedule, report


def degrees(p, schedule) -> list[float]:
    return [r.degree for r in validate(p, schedule).requests]


def external(person: str, n: int, start: str = "06:00", end: str = "14:00") -> ExternalShift:
    hours = [time(int(v[:2]), int(v[3:])) for v in (start, end)]
    return ExternalShift(person, day(n), *shift_bounds(day(n), *hours), label="Dworcowa")


def two_shifts_a_day(days: int, *, closing: bool = False):
    """Morning 06–14 and afternoon 14–22 every day."""
    return [
        s
        for n in range(days)
        for s in (
            slot(f"m{n}", day(n), "06:00", "14:00", shift_type="morning"),
            slot(f"a{n}", day(n), "14:00", "22:00", shift_type="afternoon", closing=closing),
        )
    ]


# ----------------------------------------------------------------- pora dnia ("wolę zaczynać po 10")


def test_time_of_day_counts_shifts_outside_the_hours():
    slots = [
        slot("early", day(0), "06:00", "14:00"),
        slot("late", day(0), "10:00", "18:00", shift_type="late"),
        slot("night", day(1), "22:00", "06:00", shift_type="night"),
    ]
    after_ten = Request("r", "ola", "time_of_day", from_time=time(10))
    before_six_pm = Request("r2", "ola", "time_of_day", to_time=time(18))
    p = problem([employee("ola"), employee("ewa")], slots, requests=[after_ten, before_six_pm])
    assert after_ten.wrong_hours(p, slots[0]) and not after_ten.wrong_hours(p, slots[1])
    assert not after_ten.wrong_hours(p, slots[2])  # starts at 22: after ten, whenever it ends
    assert not before_six_pm.wrong_hours(p, slots[0]) and before_six_pm.wrong_hours(p, slots[2])
    assert degrees(p, {"early": "ola", "late": "ewa", "night": "ewa"}) == [1, 0]
    assert degrees(p, {"early": "ewa", "late": "ola", "night": "ola"}) == [0, 0.5]


def test_time_of_day_to_avoid_counts_every_overlap_also_from_the_day_before():
    """ "Wolę nie pracować od 0 do 6": a night shift that starts the evening before overlaps those hours."""
    slots = [slot("night", day(0), "22:00", "06:00", shift_type="night"), slot("day", day(1), "08:00", "16:00")]
    wish = Request("r", "ola", "time_of_day", to_time=time(6), avoid=True)
    p = problem([employee("ola"), employee("ewa")], slots, requests=[wish])
    assert wish.wrong_hours(p, slots[0]) and not wish.wrong_hours(p, slots[1])
    noon = Request("r", "ola", "time_of_day", from_time=time(12), to_time=time(14), avoid=True)
    assert noon.wrong_hours(p, slots[1]) and not noon.wrong_hours(p, slots[0])


def test_time_of_day_gives_the_person_the_later_shift():
    slots = [slot(f"e{n}", day(n), "06:00", "14:00", shift_type="early") for n in range(3)]
    slots += [slot(f"l{n}", day(n), "10:00", "18:00", shift_type="late") for n in range(3)]
    wish = Request("r", "ola", "time_of_day", from_time=time(10))
    p = problem([employee("ola"), employee("ewa")], slots, requests=[wish])
    schedule, report = solved(p)
    assert all(schedule[f"l{n}"] == "ola" for n in range(3)), schedule
    assert report.requests[0].degree == 0


# ----------------------------------------------------------------- dni z rzędu ("najwyżej 3 dni z rzędu")


def test_days_in_row_counts_days_after_the_limit_and_shifts_elsewhere():
    slots = [slot(f"s{n}", day(n)) for n in range(1, 6)]
    wish = Request("r", "ola", "days_in_row", max_in_row=3)
    p = problem([employee("ola"), employee("ewa")], slots, requests=[wish], external_shifts=[external("ola", 0)])
    all_ola = {f"s{n}": "ola" for n in range(1, 6)}
    # Monday elsewhere + Tuesday to Saturday here: Thursday, Friday and Saturday are the 4th to 6th day in a row.
    assert degrees(p, all_ola) == [pytest.approx(3 / 5)]
    assert degrees(p, all_ola | {"s3": "ewa"}) == [0]  # Mon–Wed, then Fri–Sat
    _schedule, report = solved(p)
    assert report.requests[0].degree == 0


def test_nights_in_a_row_count_only_that_shift():
    """ "Nie więcej niż 2 nocki pod rząd": a morning between nights breaks the run, mornings never count."""
    nights = [slot(f"n{n}", day(n), "22:00", "06:00", shift_type="night") for n in range(4)]
    morning = slot("m2", day(2), "06:00", "12:00", shift_type="morning")
    wish = Request("r", "roman", "days_in_row", max_in_row=2, shift_type="night")
    p = problem([employee("roman"), employee("ewa")], [*nights, morning], requests=[wish])
    assert degrees(p, {f"n{n}": "roman" for n in range(4)} | {"m2": "ewa"}) == [0.5]
    assert degrees(p, {"n0": "roman", "n1": "roman", "n2": "ewa", "n3": "roman", "m2": "roman"}) == [0]
    every_night = Request("likes", "roman", "want_work", dates=frozenset(day(n) for n in range(4)), shift_type="night")
    schedule, report = solved(replace(p, requests=(wish, replace(every_night, level="mile_widziane"))))
    assert report.requests[0].degree == 0
    assert [schedule[f"n{n}"] for n in range(4)].count("roman") == 3


# ----------------------------------------------------------------- wolne z rzędu ("2 dni wolne pod rząd")


def test_days_off_in_a_row_in_each_week():
    slots = [slot(f"s{n}", day(n)) for n in range(7)]
    wish = Request("r", "ola", "days_off_in_row", free_in_row=2, weekly_hours=True)
    p = problem([employee("ola"), employee("ewa")], slots, requests=[wish])
    every_other = {f"s{n}": "ola" if n % 2 == 0 else "ewa" for n in range(7)}
    assert degrees(p, every_other) == [1]  # four days off, never two in a row
    assert degrees(p, every_other | {"s4": "ewa"}) == [0]  # Thursday and Friday off
    # Ola has to work five days: the generator puts her two days off together.
    cannot = [Availability("ewa", day(n), AvailabilityState.CANNOT) for n in (0, 2, 4)]
    _schedule, report = solved(replace(p, availability=tuple(cannot)))
    assert report.requests[0].degree == 0


def test_days_off_in_a_row_counts_days_worked_elsewhere():
    slots = [slot(f"s{n}", day(n)) for n in range(3)]
    wish = Request("r", "ola", "days_off_in_row", free_in_row=2)
    p = problem([employee("ola"), employee("ewa")], slots, requests=[wish], external_shifts=[external("ola", 1)])
    assert degrees(p, {"s0": "ewa", "s1": "ewa", "s2": "ewa"}) == [1]  # Tuesday elsewhere: no two days in a row


# ----------------------------------------------------------------- po zmianie ("po nocce dzień wolny")


def test_rest_after_a_night():
    nights = [slot(f"n{n}", day(n), "22:00", "06:00", shift_type="night") for n in range(3)]
    days_ = [slot(f"d{n}", day(n), "14:00", "20:00", shift_type="day") for n in range(3)]
    wish = Request("r", "roman", "rest_after", shift_type="night")
    p = problem([employee("roman"), employee("ewa")], nights + days_, requests=[wish])
    base = {s.id: "ewa" for s in nights + days_}
    assert degrees(p, base | {"n0": "roman", "d1": "roman"}) == [1]
    assert degrees(p, base | {"n0": "roman", "d2": "roman"}) == [0]
    after_close = Request("r", "roman", "rest_after", shift_type="night", next_shift_type="night")
    q = replace(p, requests=(after_close,))
    assert degrees(q, base | {"n0": "roman", "d1": "roman"}) == [0]  # only another night is unwelcome
    assert degrees(q, base | {"n0": "roman", "n1": "roman"}) == [0.5]  # the second night has no night after it
    two = replace(wish, days_after=2)
    assert degrees(replace(p, requests=(two,)), base | {"n0": "roman", "d2": "roman"}) == [1]


def test_rest_after_is_kept_by_the_generator():
    nights = [slot(f"n{n}", day(n), "22:00", "06:00", shift_type="night") for n in range(4)]
    wish = Request("r", "roman", "rest_after", shift_type="night", level="bardzo_wazne")
    likes = Request("likes", "roman", "want_work", dates=frozenset(day(n) for n in range(4)), level="mile_widziane")
    p = problem([employee("roman"), employee("ewa")], nights, requests=[wish, likes])
    schedule, report = solved(p)
    assert report.requests[0].degree == 0
    assert [schedule[f"n{n}"] for n in range(4)].count("roman") == 2


# ----------------------------------------------------------------- lokal ("wolę Rynek")


def test_location_only_or_not_one_location():
    slots = [slot("r", day(0), location="rynek"), slot("d", day(0), "14:00", "22:00", location="dworcowa")]
    both = employee("ola", home="rynek", extra_locations=frozenset({"dworcowa"}))
    others = [employee("ewa", home="rynek"), employee("iza", home="dworcowa")]
    rynek = Request("r1", "ola", "location", locations=frozenset({"rynek"}))
    not_dworcowa = Request("r2", "ola", "location", locations=frozenset({"dworcowa"}), avoid=True)
    p = problem([both, *others], slots, requests=[rynek, not_dworcowa])
    assert degrees(p, {"r": "ewa", "d": "ola"}) == [1, 1]
    assert degrees(p, {"r": "ola", "d": "iza"}) == [0, 0]
    schedule, _report = solved(replace(p, employees=(both, others[1])))  # Ola is the only one for Rynek
    assert schedule["r"] == "ola" and schedule["d"] == "iza"


# ----------------------------------------------------------------- wolne weekendy ("co drugi weekend wolny")


def weekends(count: int):
    """A Saturday and a Sunday shift in each of `count` weekends, from Saturday 7.11."""
    return [slot(f"w{k}.{d}", day(5 + 7 * k + d)) for k in range(count) for d in range(2)]


def test_one_free_weekend_in_the_period():
    slots = weekends(3)
    wish = Request("r", "ola", "free_weekends", free_weekends=1)
    p = problem([employee("ola"), employee("ewa")], slots, start=MON, end=day(20), requests=[wish])
    assert [[str(s) for s in sats] for sats, _ in wish.weekend_groups(p)] == [
        ["2026-11-07", "2026-11-14", "2026-11-21"]
    ]
    one_day_each = {s.id: "ola" if s.id.endswith(".0") else "ewa" for s in slots}
    assert degrees(p, one_day_each) == [1]  # a Saturday every weekend: none free
    assert degrees(p, one_day_each | {"w1.0": "ewa"}) == [0]
    # Ewa cannot work the first two Saturdays, so Ola has them; the third weekend stays free for her.
    cannot = [Availability("ewa", day(5 + 7 * k), AvailabilityState.CANNOT) for k in range(2)]
    schedule, report = solved(replace(p, availability=tuple(cannot)))
    assert report.requests[0].degree == 0 and schedule["w0.0"] == schedule["w1.0"] == "ola"


def test_every_other_weekend_counts_the_weekend_before_the_period():
    slots = weekends(2)
    wish = Request("r", "ola", "free_weekends", free_weekends=1, of_weekends=2)
    before = external("ola", -2)  # Saturday 31.10
    p = problem(
        [employee("ola"), employee("ewa")],
        slots,
        start=MON,
        end=day(13),
        requests=[wish],
        external_shifts=[before],
    )
    groups = [[str(s) for s in sats] for sats, _ in wish.weekend_groups(p)]
    assert groups == [["2026-10-31", "2026-11-07"], ["2026-11-07", "2026-11-14"]]
    first_weekend = {"w0.0": "ola", "w0.1": "ewa", "w1.0": "ewa", "w1.1": "ewa"}
    assert degrees(p, first_weekend) == [0.5]  # 31.10 and 7.11 both worked
    schedule, report = solved(
        replace(p, requests=(wish, Request("more", "ola", "shift_type", shift_type="06:00-14:00")))
    )
    assert report.requests[0].degree == 0 and "ola" not in (schedule["w0.0"], schedule["w0.1"])


# ----------------------------------------------------------------- co najmniej N dni w tygodniu, jeden z dni wolny


def test_want_work_at_least_days_in_each_week_and_a_cut_week():
    """ "Co najmniej 4 dni w tygodniu": a week with 3 of its days in the period needs 2 (4 × 3/7, rounded)."""
    slots = [slot(f"s{n}", day(n)) for n in range(10)]
    every_day = frozenset(day(n) for n in range(-4, 14))  # as the builder gives it: whole weeks
    wish = Request("r", "ola", "want_work", dates=every_day, min_days=4, weekly_hours=True)
    p = problem([employee("ola"), employee("ewa")], slots, requests=[wish])
    windows = wish.count_windows(p)
    assert [(len(days), need) for days, need in windows] == [(7, 4), (3, 2)]
    three_and_two = {f"s{n}": "ola" if n in (0, 1, 2, 7, 8) else "ewa" for n in range(10)}
    assert degrees(p, three_and_two) == [pytest.approx((1 / 4 + 0) / 2)]
    _schedule, report = solved(
        replace(p, requests=(wish, Request("less", "ola", "hours_limit", max_hours=0, level="mile_widziane")))
    )
    assert report.requests[0].degree == 0


def test_days_off_on_one_of_two_days():
    """ "Albo 24, albo 31 wolne", "sobota albo niedziela wolna": one free day is enough."""
    slots = [slot("a", day(0)), slot("b", day(1))]
    wish = Request("r", "ola", "days_off", dates=frozenset({day(0), day(1)}), min_days=1)
    p = problem([employee("ola"), employee("ewa")], slots, requests=[wish])
    assert degrees(p, {"a": "ola", "b": "ola"}) == [1]
    assert degrees(p, {"a": "ola", "b": "ewa"}) == [0]
    elsewhere = replace(p, external_shifts=(external("ola", 1),))
    assert degrees(elsewhere, {"a": "ola", "b": "ewa"}) == [1]  # Tuesday elsewhere is no day off
    cannot = [Availability("ewa", day(n), AvailabilityState.CANNOT) for n in (0, 1)]
    _schedule, report = solved(
        replace(p, employees=(employee("ola"), employee("ewa"), employee("iza")), availability=tuple(cannot))
    )
    assert report.requests[0].degree == 0


def test_weekend_day_off_in_each_week():
    slots = weekends(2)
    sat_sun = frozenset(day(n) for n in (5, 6, 12, 13))
    wish = Request("r", "ola", "days_off", dates=sat_sun, min_days=1, weekly_hours=True)
    p = problem([employee("ola"), employee("ewa")], slots, start=MON, end=day(13), requests=[wish])
    assert [need for _, need in wish.count_windows(p)] == [1, 1]
    assert degrees(p, {"w0.0": "ola", "w0.1": "ola", "w1.0": "ola", "w1.1": "ewa"}) == [0.5]


# ----------------------------------------------------------------- te same dni co ktoś


def test_not_on_the_same_days_counts_any_shift_that_day_and_shifts_elsewhere():
    slots = two_shifts_a_day(2)
    wish = Request("r", "ola", "avoid_person", subject_employee="marek", same_day=True)
    p = problem([employee("ola"), employee("marek"), employee("ewa")], slots, requests=[wish])
    morning_and_afternoon = {"m0": "ola", "a0": "marek", "m1": "ewa", "a1": "ewa"}
    assert degrees(p, morning_and_afternoon) == [1]  # not at the same time, but the same day
    assert degrees(p, {"m0": "ola", "a0": "ewa", "m1": "ewa", "a1": "marek"}) == [0]
    q = replace(p, external_shifts=(external("marek", 1),))
    assert degrees(q, {"m0": "ewa", "a0": "ewa", "m1": "ola", "a1": "ewa"}) == [1]
    monday = frozenset({day(0)})
    pulls = [Request(f"w-{e}", e, "want_work", dates=monday, level="mile_widziane") for e in ("ola", "marek")]
    schedule, report = solved(replace(p, requests=(replace(wish, level="bardzo_wazne"), *pulls)))
    assert report.requests[0].degree == 0
    assert {schedule["m0"], schedule["a0"]} != {"ola", "marek"}


def test_the_same_days_off_as_someone():
    slots = two_shifts_a_day(3)
    wish = Request("r", "ola", "prefer_person", subject_employee="kasia", same_day=True)
    p = problem([employee("ola"), employee("kasia"), employee("ewa")], slots, requests=[wish])
    apart = {"m0": "ola", "a0": "ewa", "m1": "kasia", "a1": "ewa", "m2": "ewa", "a2": "ewa"}
    assert degrees(p, apart) == [1]
    same = {"m0": "ola", "a0": "kasia", "m1": "ewa", "a1": "ewa", "m2": "ewa", "a2": "ewa"}
    assert degrees(p, same) == [0]
    _schedule, report = solved(p)
    assert report.requests[0].degree == 0


# ----------------------------------------------------------------- ta sama pora, nie więcej niż inni, długość, nie sam


def test_same_shift_type_in_each_week():
    slots = two_shifts_a_day(7)
    wish = Request("r", "ola", "same_shift_type")
    p = problem([employee("ola"), employee("ewa")], slots, requests=[wish])
    mixed = {s.id: "ewa" for s in slots} | {"m0": "ola", "a1": "ola"}
    assert degrees(p, mixed) == [1]
    assert degrees(p, mixed | {"a1": "ewa", "m1": "ola"}) == [0]
    likes = [Request("m", "ola", "want_work", dates=frozenset({day(0)}), shift_type="morning")]
    likes.append(
        Request("a", "ola", "want_work", dates=frozenset({day(3)}), shift_type="afternoon", level="mile_widziane")
    )
    _schedule, report = solved(replace(p, requests=(replace(wish, level="bardzo_wazne"), *likes)))
    assert report.requests[0].degree == 0


def test_not_more_closings_than_the_others():
    slots = two_shifts_a_day(6, closing=True)
    wish = Request("r", "ola", "not_more_than_others", closing=True)
    people = [employee("ola"), employee("ewa"), employee("iza")]
    p = problem(people, slots, requests=[wish])
    closings = {f"a{n}": "ola" if n < 4 else "ewa" for n in range(6)} | {f"m{n}": "iza" for n in range(6)}
    # Ola 4, the others 2 and 0: average 1, so 3 of her 4 are above it.
    assert degrees(p, closings) == [0.75]
    fair = {f"a{n}": ["ola", "ewa", "iza"][n % 3] for n in range(6)} | {f"m{n}": "iza" for n in range(6)}
    assert degrees(p, fair) == [0]
    likes = Request("likes", "ola", "shift_type", shift_type="afternoon", level="mile_widziane")
    _schedule, report = solved(replace(p, requests=(replace(wish, level="bardzo_wazne"), likes)))
    assert report.requests[0].degree == 0


def test_shift_length_and_not_alone():
    slots = [
        slot("short", day(0), "06:00", "10:00", shift_type="short"),
        slot("long", day(0), "10:00", "18:00", shift_type="long"),
        slot("close", day(1), "14:00", "22:00", shift_type="close", closing=True),
        slot("close2", day(1), "16:00", "22:00", shift_type="close2", closing=True),
    ]
    length = Request("r1", "ola", "shift_length", min_shift_hours=6)
    alone = Request("r2", "ola", "not_alone", closing=True)
    p = problem([employee("ola"), employee("ewa")], slots, requests=[length, alone])
    assert degrees(p, {"short": "ola", "long": "ewa", "close": "ola", "close2": None}) == [0.5, 1]
    assert degrees(p, {"short": "ewa", "long": "ola", "close": "ola", "close2": "ewa"}) == [0, 0]
    # Only one closing person can be found: someone else takes it, so Ola is not alone there.
    q = replace(
        p,
        slots=tuple(slots[:3]),
        requests=(alone, Request("w", "ola", "want_work", dates=frozenset({day(1)}), level="mile_widziane")),
    )
    schedule, _report = solved(q)
    assert schedule["close"] == "ewa"


def test_closing_narrows_any_request_with_shifts():
    slots = two_shifts_a_day(1, closing=True)
    wish = Request("r", "ola", "shifts_limit", max_shifts=0, closing=True)
    p = problem([employee("ola"), employee("ewa", positions=(SALES, BAKER))], slots, requests=[wish])
    assert wish.counts_slot(slots[1]) and not wish.counts_slot(slots[0])
    assert degrees(p, {"m0": "ola", "a0": "ewa"}) == [0]
    assert degrees(p, {"m0": "ewa", "a0": "ola"}) == [1]
