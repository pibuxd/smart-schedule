"""The structure a sentence becomes: one wish about one person, of a type from a closed list.

Used for an employee's text request (`TextRequest.interpretation`) and for a manager's instruction
(`ManagerInstruction.data`). Keys: type (unikaj_osoby, preferuj_osobe, typ_zmiany, limit_godzin, limit_zmian,
wolne_dni, chce_pracowac, inne), subject_employee (id), shift_type (id; for unikaj_osoby / preferuj_osobe it narrows
the pair to that shift: "nie razem na zamknięciu"), avoid, max_hours, max_shifts, hours_period (day, week, period:
the window of limit_godzin and limit_zmian), min_days, shifts_per_day, dates (ISO), weekdays (0 = Monday), cannot
(wolne_dni the person cannot work at all).
An employee's message with several wishes keeps the others in `more` (a list of readings like this one).

What the assistant returns is never trusted as is: names are matched against the location's own lists and
anything that cannot be checked makes the reading unusable (`clean` returns None).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from typing import Any

TYPES = (
    "unikaj_osoby",
    "preferuj_osobe",
    "typ_zmiany",
    "limit_godzin",
    "limit_zmian",
    "wolne_dni",
    "chce_pracowac",
    "inne",
)
LIMITS = ("limit_godzin", "limit_zmian")  # the types counted per day, week or period (`hours_period`)
# Types where a shift name may narrow the wish (for typ_zmiany it is the wish itself).
SHIFT_TYPED = ("typ_zmiany", "chce_pracowac", "unikaj_osoby", "preferuj_osobe", "limit_zmian")
LEVELS = ("bardzo_wazne", "wazne", "mile_widziane")

_WEEKDAYS = ("w poniedziałki", "we wtorki", "w środy", "w czwartki", "w piątki", "w soboty", "w niedziele")
_WEEKDAY_OF = ("poniedziałku", "wtorku", "środy", "czwartku", "piątku", "soboty", "niedzieli")
HOURS_PERIODS = ("day", "week", "period")


def labels(people: Iterable[tuple[str, str, str]]) -> dict[str, str]:
    """(id, first name, last name) -> label -> id. Only what is needed to tell people apart leaves the app:
    the first name, with the first letter of the surname (then a number) when two people share it."""
    people = [(pid, first.strip() or "Bez imienia", last.strip()) for pid, first, last in people]
    counts: dict[str, int] = {}
    for _, first, _ in people:
        counts[first.casefold()] = counts.get(first.casefold(), 0) + 1
    result: dict[str, str] = {}
    for pid, first, last in sorted(people, key=lambda p: (p[1].casefold(), p[2].casefold(), p[0])):
        label = first if counts[first.casefold()] == 1 or not last else f"{first} {last[0]}."
        base, number = label, 2
        while label in result:
            label = f"{base} ({number})"
            number += 1
        result[label] = pid
    return result


def _lookup(name: str | None, by_label: Mapping[str, str]) -> str | None:
    if not name:
        return None
    wanted = name.strip().casefold()
    for label, value in by_label.items():
        if label.casefold() == wanted:
            return value
    return None


def hour_scope(scope: str | None, text: str, max_hours: float | None) -> str:
    """Recognise an explicit per-day or per-week limit if the model dropped its unit on a single request."""
    amount = r"\b(\d+(?:[,.]\d+)?)\s*(?:godzin(?:y|ę)?|godz\.?|h)\b"
    if scope in (None, "period") and len(re.findall(amount, text, re.I)) == 1:
        for unit, words in (
            ("week", r"(?:w każdym tygodniu|na każdy tydzień|tygodniowo|na tydzień|w tygodniu)"),
            ("day", r"(?:dziennie|na dzień|każdego dnia|w ciągu dnia|na zmianę)"),
        ):
            match = re.search(rf"{amount}\s+{words}(?!\w)", text, re.I)
            if match and float(match[1].replace(",", ".")) == max_hours:
                return unit
    return scope or "period"


def saved_reading(data: dict | None, text: str) -> dict:
    """Older readings had no unit. Recover it only from an explicit weekly quantity in the original text."""
    data = data or {}
    if data.get("type") == "limit_godzin" and "hours_period" not in data:
        return {**data, "hours_period": hour_scope(None, text, data.get("max_hours"))}
    return data


def legacy_hours_notice(data: dict | None, text: str) -> str:
    if data and "hours_period" not in data and saved_reading(data, text).get("hours_period") == "week":
        return " Od aktualizacji generator liczy ten zapisany limit osobno w każdym tygodniu."
    return ""


def clean(
    *,
    type: str,
    person: str | None = None,
    shift_type: str | None = None,
    avoid: bool = False,
    max_hours: float | None = None,
    max_shifts: int | None = None,
    hours_period: str = "period",
    dates: Iterable[str] = (),
    weekdays: Iterable[int] = (),
    min_days: int | None = None,
    shifts_per_day: int | None = None,
    people: Mapping[str, str],
    shift_types: Mapping[str, str],
) -> dict[str, Any] | None:
    """The checked reading, or None when it is not something the generator can use.

    `people` and `shift_types` map the labels sent to the assistant back to ids. `weekdays` come as 1 = Monday
    … 7 = Sunday (as people count them) and are stored as 0–6.
    """
    if type not in TYPES or type == "inne":
        return None
    # Reject combinations we cannot preserve, instead of silently narrowing the user's intent.
    if (
        (person and type not in ("unikaj_osoby", "preferuj_osobe"))
        or (shift_type and type not in SHIFT_TYPED)
        or (avoid and type != "typ_zmiany")
        or (max_hours is not None and type != "limit_godzin")
        or (max_shifts is not None and type != "limit_zmian")
        or ((min_days is not None or shifts_per_day is not None) and type != "chce_pracowac")
    ):
        return None
    if type not in LIMITS:
        hours_period = "period"  # the window means nothing for other types (the answer schema always fills it)
    dates, weekdays = list(dates), list(weekdays)
    if any(_parse_date(v) is None for v in dates) or any(not isinstance(w, int) or not 1 <= w <= 7 for w in weekdays):
        return None
    if hours_period not in HOURS_PERIODS:
        return None
    days = sorted({d for d in (_parse_date(v) for v in dates) if d is not None})
    week = sorted({int(w) - 1 for w in weekdays if isinstance(w, int) and 1 <= w <= 7})
    data: dict[str, Any] = {"type": type, "dates": [d.isoformat() for d in days], "weekdays": week}
    if type in ("unikaj_osoby", "preferuj_osobe"):
        subject = _lookup(person, people)
        if subject is None:
            return None
        data["subject_employee"] = subject
        if shift_type:
            found = _lookup(shift_type, shift_types)
            if found is None:
                return None
            data["shift_type"] = found
    elif type == "typ_zmiany":
        found = _lookup(shift_type, shift_types)
        if found is None:
            return None
        data["shift_type"] = found
        data["avoid"] = bool(avoid)
    elif type == "limit_godzin":
        if max_hours is None or not 0 <= max_hours <= 744:
            return None
        data["max_hours"] = float(max_hours)
        data["hours_period"] = hours_period
    elif type == "limit_zmian":
        if not isinstance(max_shifts, int) or isinstance(max_shifts, bool) or not 0 <= max_shifts <= 93:
            return None
        if shift_type:
            found = _lookup(shift_type, shift_types)
            if found is None:
                return None
            data["shift_type"] = found
        data["max_shifts"] = max_shifts
        data["hours_period"] = hours_period
    elif type == "wolne_dni" and not days and not week:
        return None
    elif type == "chce_pracowac":
        if not days and not week:
            return None
        if shift_type:
            found = _lookup(shift_type, shift_types)
            if found is None:
                return None
            data["shift_type"] = found
        if min_days is not None and (not isinstance(min_days, int) or min_days < 1):
            return None
        if shifts_per_day is not None and (not isinstance(shifts_per_day, int) or not 1 <= shifts_per_day <= 3):
            return None
        if min_days is not None and days and not week and min_days >= len(days):
            min_days = None  # "all of them" said as a number
        data["min_days"] = min_days
        data["shifts_per_day"] = shifts_per_day or 1
    return data


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def dates_in(data: Mapping[str, Any], start: date, end: date) -> set[date]:
    """Days of [start, end] the reading is about: its dates plus every day of its weekdays."""
    days = {d for d in (_parse_date(v) for v in data.get("dates") or []) if d is not None and start <= d <= end}
    week = {w for w in data.get("weekdays") or [] if isinstance(w, int)}
    day = start
    while week and day <= end:
        if day.weekday() in week:
            days.add(day)
        day += timedelta(days=1)
    return days


def has_days(data: Mapping[str, Any]) -> bool:
    return bool(data.get("dates") or data.get("weekdays"))


def is_over(data: Mapping[str, Any], today: date) -> bool:
    """True when the reading names only dates that have passed (nothing left to keep)."""
    if data.get("weekdays"):
        return False
    days = [d for d in (_parse_date(v) for v in data.get("dates") or []) if d is not None]
    return bool(days) and max(days) < today


def _weekday_words(week: list[int]) -> str:
    week = sorted({w for w in week if isinstance(w, int) and 0 <= w <= 6})
    if week == [5, 6]:
        return "w weekendy"
    parts, run = [], []
    for w in [*week, None]:
        if w is not None and run and w == run[-1] + 1:
            run.append(w)
            continue
        if len(run) >= 3:
            parts.append(f"od {_WEEKDAY_OF[run[0]]} do {_WEEKDAY_OF[run[-1]]}")
        else:
            parts += [_WEEKDAYS[d] for d in run]
        run = [w] if w is not None else []
    return " i ".join(parts)


def _date_words(days: list[date]) -> str:
    """14.12–18.12, 24.12: runs of three or more days in a row as a range, at most six groups."""
    groups: list[list[date]] = []
    for d in sorted(set(days)):
        if groups and d == groups[-1][-1] + timedelta(days=1):
            groups[-1].append(d)
        else:
            groups.append([d])

    def short(d: date) -> str:
        return f"{d.day}.{d.month:02d}"

    words = []
    for group in groups[:6]:
        if len(group) >= 3:
            words.append(f"{short(group[0])}–{short(group[-1])}")
        else:
            words += [short(d) for d in group]
    return ", ".join(words) + (" i inne dni" if len(groups) > 6 else "")


def _when(data: Mapping[str, Any]) -> str:
    parts = []
    week = _weekday_words(data.get("weekdays") or [])
    if week:
        parts.append(week)
    days = [d for d in (_parse_date(v) for v in data.get("dates") or []) if d is not None]
    if days:
        parts.append(_date_words(days))
    return " " + " i ".join(parts) if parts else ""


def _shift_count(count: int) -> str:
    """3 zmiany, 5 zmian, 1 zmiana (Polish plural)."""
    if count == 1:
        return "1 zmiana"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} zmiany"
    return f"{count} zmian"


def describe(data: Mapping[str, Any], who: str, people: Mapping[str, str], shift_types: Mapping[str, str]) -> str:
    """One plain Polish sentence for the manager. `people` and `shift_types` map ids to names here."""
    when = _when(data)
    match data.get("type"):
        case "unikaj_osoby":
            other = people.get(str(data.get("subject_employee")), "ktoś")
            if data.get("shift_type"):
                name = shift_types.get(str(data["shift_type"]), "?")
                return f"{who} i {other}: nie razem na zmianie „{name}”{when}"
            return f"{who} i {other}: osobno, nie na tej samej zmianie{when}"
        case "preferuj_osobe":
            other = people.get(str(data.get("subject_employee")), "ktoś")
            if data.get("shift_type"):
                name = shift_types.get(str(data["shift_type"]), "?")
                return f"{who} i {other}: razem na zmianie „{name}”{when}"
            return f"{who} i {other}: razem na zmianie{when}"
        case "typ_zmiany":
            name = shift_types.get(str(data.get("shift_type")), "?")
            return f"{who}: bez zmiany „{name}”{when}" if data.get("avoid") else f"{who}: tylko zmiana „{name}”{when}"
        case "limit_godzin":
            hours = data.get("max_hours") or 0
            shown = int(hours) if float(hours).is_integer() else hours
            if data.get("hours_period") == "week":
                return f"{who}: najwyżej {shown} godz. w każdym tygodniu{when}"
            if data.get("hours_period") == "day":
                return f"{who}: najwyżej {shown} godz. dziennie{when}"
            return f"{who}: najwyżej {shown} godz.{when or ' w okresie grafiku'}"
        case "limit_zmian":
            count = int(data.get("max_shifts") or 0)
            name = f" „{shift_types.get(str(data['shift_type']), '?')}”" if data.get("shift_type") else ""
            limit = f"żadnej zmiany{name}" if count == 0 else f"najwyżej {_shift_count(count)}{name}"
            if data.get("hours_period") == "week":
                return f"{who}: {limit} w każdym tygodniu{when}"
            if data.get("hours_period") == "day":
                return f"{who}: {limit} dziennie{when}"
            return f"{who}: {limit}{when or ' w okresie grafiku'}"
        case "wolne_dni":
            if sorted(data.get("weekdays") or []) == [0, 1, 2, 3, 4] and not data.get("dates"):
                return f"{who}: tylko weekendy (wolne od poniedziałku do piątku)"
            if data.get("cannot"):
                return f"{who}: wolne{when} („nie mogę”)"
            return f"{who}: wolne{when}"
        case "chce_pracowac":
            shifts = data.get("shifts_per_day") or 1
            what = {1: "praca", 2: "dwie zmiany jednego dnia", 3: "trzy zmiany jednego dnia"}.get(shifts, "praca")
            if data.get("shift_type"):
                what += f" na zmianie „{shift_types.get(str(data['shift_type']), '?')}”"
            need = data.get("min_days")
            if need:
                which = "jeden z tych dni" if need == 1 else f"{need} z tych dni"
                return f"{who}: {what}{when} ({which})"
            return f"{who}: {what}{when}"
        case _:
            return f"{who}: do Twojej oceny"
