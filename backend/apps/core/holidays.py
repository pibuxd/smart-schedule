"""Public holidays in Poland (days off by law, ustawa o dniach wolnych od pracy), computed for any year.

Christmas Eve is a public holiday since 2025. Easter Sunday and Pentecost fall on a Sunday but are holidays too.
The assistant gets them as a line of its context, so it never works out Easter by itself.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

FIXED = (
    (1, 1, "Nowy Rok"),
    (1, 6, "Trzech Króli"),
    (5, 1, "Święto Pracy"),
    (5, 3, "Święto Konstytucji 3 Maja"),
    (8, 15, "Wniebowzięcie Najświętszej Maryi Panny"),
    (11, 1, "Wszystkich Świętych"),
    (11, 11, "Narodowe Święto Niepodległości"),
    (12, 25, "Boże Narodzenie (pierwszy dzień)"),
    (12, 26, "Boże Narodzenie (drugi dzień)"),
)
CHRISTMAS_EVE_FROM = 2025
WEEKDAY_SHORT = ("pon.", "wt.", "śr.", "czw.", "pt.", "sob.", "niedz.")


def easter(year: int) -> date:
    """Easter Sunday in the Gregorian calendar (the anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


def polish_holidays(year: int) -> list[tuple[date, str]]:
    """The year's public holidays in Poland, in date order."""
    sunday = easter(year)
    days = [(date(year, month, day), name) for month, day, name in FIXED]
    days += [
        (sunday, "Wielkanoc"),
        (sunday + timedelta(days=1), "Poniedziałek Wielkanocny"),
        (sunday + timedelta(days=49), "Zielone Świątki"),
        (sunday + timedelta(days=60), "Boże Ciało"),
    ]
    if year >= CHRISTMAS_EVE_FROM:
        days.append((date(year, 12, 24), "Wigilia"))
    return sorted(days)


def holidays_line(days: Iterable[date]) -> str:
    """One line for the assistant: the public holidays of every year the given days fall in."""
    parts = []
    for year in sorted({d.year for d in days}):
        listed = ", ".join(
            f"{WEEKDAY_SHORT[d.weekday()]} {d.day}.{d.month:02d} {name}" for d, name in polish_holidays(year)
        )
        parts.append(f"{year}: {listed}")
    return "Dni ustawowo wolne od pracy w Polsce: " + "; ".join(parts) + "."
