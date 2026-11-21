"""A month written as RRRR-MM in query parameters (hours report, "Zmień godziny sam")."""

from datetime import date

from ninja.errors import HttpError


def month_range(value: str) -> tuple[date, date]:
    """'2026-12' -> (the 1st of December, the 1st of January), or a Polish 400."""
    try:
        first = date.fromisoformat(f"{value}-01")
        nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    except ValueError:
        raise HttpError(400, "Podaj miesiąc w postaci RRRR-MM, np. 2026-12.") from None
    return first, nxt
