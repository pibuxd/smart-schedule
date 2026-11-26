"""The structure a sentence becomes: one wish about one person, of a type from a closed list.

Used for an employee's text request (`TextRequest.interpretation`) and for a manager's instruction
(`ManagerInstruction.data`). Keys: type (unikaj_osoby, preferuj_osobe, typ_zmiany, stanowisko, limit_godzin,
limit_zmian, cel_godzin, wolne_dni, chce_pracowac, inne), subject_employee (id), shift_type (id; for unikaj_osoby /
preferuj_osobe it narrows the pair to that shift: "nie razem na zamknięciu"), positions (stanowisko: the ids of one
position name among the person's positions, one per location) with position_name, avoid (typ_zmiany, stanowisko: not
this one), rather (stanowisko: rather this one, the others stay fine), max_hours, max_shifts, target_hours
(cel_godzin: about this many hours, "chcę wyrobić 30 godzin"; with at_least: true at least this many, "co najmniej
30 godzin"), hours_period (day, week, period: the window of
limit_godzin, limit_zmian and cel_godzin), prefer_weekdays (cel_godzin: the hours rather on these weekdays,
0 = Monday; "najlepiej pod koniec tygodnia"), min_days, shifts_per_day, dates (ISO), weekdays (0 = Monday), cannot
(wolne_dni the person cannot work at all), from_time / to_time (wolne_dni with cannot: the hours they cannot work,
"HH:MM", either may be missing; no hours = the whole day). "Nie mogę" is always a whole day in the calendar (Piotr,
25.11.2026), so such hours are never scored: they only offer to mark the rest of those days "mogę" (`complement`).
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
    "stanowisko",
    "limit_godzin",
    "limit_zmian",
    "cel_godzin",
    "wolne_dni",
    "chce_pracowac",
    "inne",
)
# The types counted per day, week or period (`hours_period`).
WINDOWED = ("limit_godzin", "limit_zmian", "cel_godzin")
# Most hours a target can name in one window (a day, a week, the longest period).
TARGET_MOST = {"day": 24, "week": 7 * 24, "period": 744}
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
    target_hours: float | None = None,
    at_least: bool = False,
    prefer_weekdays: Iterable[int] = (),
    hours_period: str = "period",
    dates: Iterable[str] = (),
    weekdays: Iterable[int] = (),
    min_days: int | None = None,
    shifts_per_day: int | None = None,
    position: str | None = None,
    avoid_position: bool = False,
    rather: bool = False,
    from_time: str | None = None,
    to_time: str | None = None,
    people: Mapping[str, str],
    shift_types: Mapping[str, str],
    positions: Mapping[str, list[str]] | None = None,
) -> dict[str, Any] | None:
    """The checked reading, or None when it is not something the generator can use.

    `people` and `shift_types` map the labels sent to the assistant back to ids, `positions` the names of the
    person's positions to their ids. `weekdays` come as 1 = Monday … 7 = Sunday (as people count them) and are stored
    as 0–6, like `prefer_weekdays`.
    """
    if type not in TYPES or type == "inne":
        return None
    # Reject combinations we cannot preserve, instead of silently narrowing the user's intent.
    if (
        (person and type not in ("unikaj_osoby", "preferuj_osobe"))
        or (shift_type and type not in SHIFT_TYPED)
        or (avoid and type not in ("typ_zmiany", "stanowisko"))  # stanowisko reads `avoid_position` only
        or ((position or avoid_position) and type != "stanowisko")
        or (max_hours is not None and type != "limit_godzin")
        or (max_shifts is not None and type != "limit_zmian")
        or ((target_hours is not None or prefer_weekdays or at_least) and type != "cel_godzin")
        or ((min_days is not None or shifts_per_day is not None) and type != "chce_pracowac")
        or ((from_time or to_time) and type != "wolne_dni")
    ):
        return None
    if type not in WINDOWED:
        hours_period = "period"  # the window means nothing for other types (the answer schema always fills it)
    dates, weekdays, prefer_weekdays = list(dates), list(weekdays), list(prefer_weekdays)
    if any(_parse_date(v) is None for v in dates) or any(
        not isinstance(w, int) or not 1 <= w <= 7 for w in [*weekdays, *prefer_weekdays]
    ):
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
    elif type == "stanowisko":
        ids = _lookup(position, positions or {})
        if not ids:
            return None
        data["positions"] = sorted(str(i) for i in ids)
        data["position_name"] = next(label for label in positions or {} if positions[label] == ids)
        data["avoid"] = bool(avoid_position)
        if rather and not avoid_position:
            data["rather"] = True  # "wolę salę": the other positions stay fine, unlike "tylko na sali"
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
    elif type == "cel_godzin":
        if (
            not isinstance(target_hours, int | float)
            or isinstance(target_hours, bool)
            or not 0 < target_hours <= TARGET_MOST[hours_period]
        ):
            return None
        data["target_hours"] = float(target_hours)
        data["hours_period"] = hours_period
        if at_least:
            data["at_least"] = True  # "co najmniej 30 godzin": more hours are fine
        preferred = sorted({int(w) - 1 for w in prefer_weekdays})
        if 0 < len(preferred) < 7:  # every day of the week is no preference
            data["prefer_weekdays"] = preferred
    elif type == "wolne_dni":
        if not days and not week:
            return None
        start, end = _clock(from_time), _clock(to_time)
        if start is False or end is False or (start is not None and start == end):
            return None
        if start == "00:00":
            start = None  # "od północy"
        if end == "00:00":
            end = None  # "do północy"
        if start:
            data["from_time"] = start
        if end:
            data["to_time"] = end
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


def _clock(value: str | None) -> str | bool | None:
    """ "9:00" -> "09:00"; empty -> None; anything else -> False (not a time of day)."""
    text = (value or "").strip()
    if not text:
        return None
    match = re.fullmatch(r"(\d{1,2})[:.](\d{2})", text)
    if match and match[0] in ("24:00", "24.00"):
        return "00:00"  # midnight, as an end
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        return False
    return f"{int(match[1]):02d}:{match[2]}"


def calendar_only(data: Mapping[str, Any]) -> bool:
    """wolne_dni in some hours ("we wtorki nie mogę od 9 do 11"): not a wish for the generator, only an offer to mark
    those days "mogę" outside the hours (`complement`), since "nie mogę" is always a whole day."""
    return data.get("type") == "wolne_dni" and bool(data.get("from_time") or data.get("to_time"))


def complement(data: Mapping[str, Any]) -> list[tuple[str, str]]:
    """The windows ("HH:MM", an end "00:00" = midnight) of a day outside the hours someone cannot work: "nie mogę
    9:00–11:00" -> [("00:00", "09:00"), ("11:00", "00:00")], "od 18:00" -> [("00:00", "18:00")], "do 10:00" ->
    [("10:00", "00:00")], "22:00–6:00" (overnight) -> [("06:00", "22:00")]."""
    start, end = data.get("from_time") or None, data.get("to_time") or None
    if start and end and end < start:
        return [(end, start)]
    windows = []
    if start:
        windows.append(("00:00", start))
    if end:
        windows.append((end, "00:00"))
    return windows


DAY_MINUTES = 24 * 60
MAX_WINDOWS = 2  # the calendar keeps at most two windows a day ("lub" / "albo")


def _minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def _clock_at(minutes: int) -> str:
    """ "HH:MM" of a point of the day; the end of the day (and past it, the next morning) as the clock shows it."""
    minutes %= DAY_MINUTES
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def windows_left(
    cannot: Iterable[tuple[str | None, str | None]],
    own: Iterable[tuple[str, str]] | None = None,
    limit: int = MAX_WINDOWS,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """The windows ("HH:MM", an end "00:00" = midnight, an end before the start = the next morning) of a day that
    stay to work after all the hours someone cannot work that day: (windows, the shortest ones that do not fit in
    `limit`). `cannot`: (from, to) like a reading's hours (None = from the start / to the end of the day; an end
    before the start = "22–6": both the morning and the evening). `own`: the day's windows already in the calendar,
    None = the whole day. Dropping a window only takes hours away, so what is left never gives work in those hours.

    9–11 and 14–16 -> [0:00–9:00, 11:00–14:00, 16:00–0:00], of which 11:00–14:00 does not fit in two;
    own 8:00–18:00 and 9–11 -> [8:00–9:00, 11:00–18:00]."""
    blocked = []
    for start, end in cannot:
        a, b = _minutes(start) if start else 0, _minutes(end) if end else DAY_MINUTES
        blocked.extend([(0, b), (a, DAY_MINUTES)] if b < a else [(a, b)])
    spans = []
    for start, end in [("00:00", "00:00")] if own is None else own:
        a, b = _minutes(start), _minutes(end)
        spans.append((a, b + DAY_MINUTES if b <= a else b))
    for a, b in sorted(blocked):
        cut = []
        for x, y in spans:
            if b <= x or y <= a:
                cut.append((x, y))
                continue
            if x < a:
                cut.append((x, a))
            if b < y:
                cut.append((b, y))
        spans = cut
    # A piece that starts after midnight is the next morning: not a window of this day (dropping it is safe).
    spans = sorted(span for span in spans if span[0] < span[1] and span[0] < DAY_MINUTES)
    longest = set(sorted(spans, key=lambda span: span[0] - span[1])[:limit])
    words = [(_clock_at(x), _clock_at(y)) for x, y in spans]
    return (
        [w for w, span in zip(words, spans, strict=True) if span in longest],
        [w for w, span in zip(words, spans, strict=True) if span not in longest],
    )


def can_words(windows: list[tuple[str, str]]) -> str:
    """ "do 9:00 i od 11:00", "do 18:00", "od 10:00", "6:00–22:00"."""

    def short(value: str) -> str:
        return value[1:] if value.startswith("0") else value

    parts = []
    for start, end in windows:
        if start == "00:00":
            parts.append(f"do {short(end)}")
        elif end == "00:00":
            parts.append(f"od {short(start)}")
        else:
            parts.append(f"{short(start)}–{short(end)}")
    return " i ".join(parts)


def hours_words(data: Mapping[str, Any]) -> str:
    """ "9:00–11:00", "od 10:00", "do 11:00"; "" for a whole day."""
    start, end = data.get("from_time"), data.get("to_time")

    def short(value: str) -> str:
        return value[1:] if value.startswith("0") else value

    if start and end:
        return f"{short(start)}–{short(end)}"
    if start:
        return f"od {short(start)}"
    return f"do {short(end)}" if end else ""


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


def _one_week(data: Mapping[str, Any]) -> bool:
    """Concrete days, all in one Monday–Sunday week ("w pierwszym tygodniu lutego")."""
    days = [d for d in (_parse_date(v) for v in data.get("dates") or []) if d is not None]
    return bool(days) and not data.get("weekdays") and len({d - timedelta(days=d.weekday()) for d in days}) == 1


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
        case "stanowisko":
            name = data.get("position_name") or "?"
            if data.get("avoid"):
                return f"{who}: bez stanowiska „{name}”{when}"
            if data.get("rather"):
                return f"{who}: chętniej stanowisko „{name}”{when} (inne też mogą być)"
            return f"{who}: tylko stanowisko „{name}”{when}"
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
        case "cel_godzin":
            hours = data.get("target_hours") or 0
            shown = int(hours) if float(hours).is_integer() else hours
            if data.get("hours_period") == "week":
                window = " w tygodniu" if _one_week(data) else " w każdym tygodniu"
            elif data.get("hours_period") == "day":
                window = " dziennie"
            else:
                window = "" if when else " w okresie grafiku"
            rather = _weekday_words(data.get("prefer_weekdays") or [])
            how = "co najmniej" if data.get("at_least") else "około"
            return f"{who}: {how} {shown} godz.{window}{when}" + (f", najlepiej {rather}" if rather else "")
        case "wolne_dni":
            if sorted(data.get("weekdays") or []) == [0, 1, 2, 3, 4] and not data.get("dates"):
                return f"{who}: tylko weekendy (wolne od poniedziałku do piątku)"
            if calendar_only(data):
                # "Borys: we wtorki „Mogę” tylko do 9:00 i od 11:00 (nie może 9:00–11:00)"
                hours = hours_words(data)
                return f"{who}:{when} „Mogę” tylko {can_words(complement(data))} (nie może {hours})"
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
