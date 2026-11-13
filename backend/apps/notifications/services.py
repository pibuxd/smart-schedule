"""Writing in-app notifications and turning them into Polish sentences for the screen.

Notifications are rows only: nothing goes out by SMS or e-mail (only login codes do). The text is built when the
notification is read, from its kind and payload, so a wording fix also changes old notifications.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from apps.notifications.models import Notification
from apps.tenancy.models import Location, Membership, Role

WEEKDAYS = ("pon.", "wt.", "śr.", "czw.", "pt.", "sob.", "niedz.")

# Where the screen sends the person from a notification.
LINKS = {
    "availability_requested": "availability",
    "schedule_published": "schedule",
    "shift_offered": "schedule",
    "shift_claimed": "offers",
    "claim_approved": "schedule",
    "claim_rejected": "schedule",
    "offer_taken": "schedule",
    "offer_cancelled": "schedule",
    "offer_expired": "schedule",
}


def notify(company_id, user_ids: Iterable, kind: str, payload: dict) -> int:
    """One notification per person (duplicates dropped). Returns how many were written."""
    unique = sorted({str(u) for u in user_ids if u})
    Notification.objects.for_company(company_id).bulk_create(
        Notification(company_id=company_id, user_id=user_id, kind=kind, payload=payload) for user_id in unique
    )
    return len(unique)


def location_manager_ids(location: Location) -> list:
    """Users who decide about a location: the company's owners and the managers assigned to it."""
    rows = Membership.objects.for_company(location.company_id).filter(role__in=(Role.OWNER, Role.MANAGER))
    owners = rows.filter(role=Role.OWNER).values_list("user_id", flat=True)
    managers = rows.filter(role=Role.MANAGER, locations=location).values_list("user_id", flat=True)
    return list(owners) + list(managers)


def _day(value: str | None) -> str:
    if not value:
        return ""
    try:
        day = date.fromisoformat(value)
    except ValueError:
        return value
    return f"{WEEKDAYS[day.weekday()]} {day:%d.%m}"


def _range(payload: dict) -> str:
    return f"{_day(payload.get('start'))} – {_day(payload.get('end'))}"


def shift_words(payload: dict) -> str:
    """'pt. 11.12, 06:00–14:00, Sprzedawca, Piekarnia Rynek'"""
    parts = [f"{_day(payload.get('date'))}, {payload.get('start_time', '')}–{payload.get('end_time', '')}"]
    parts += [str(payload[key]) for key in ("position_name", "location_name") if payload.get(key)]
    return ", ".join(parts)


def notification_text(kind: str, payload: dict) -> str:
    p = payload or {}
    shift = shift_words(p)
    giver = p.get("offered_by_name") or "Ktoś"
    taker = p.get("claimed_by_name") or "Ktoś"
    match kind:
        case "availability_requested":
            return (
                f"Kierownik prosi o dyspozycje na okres {_range(p)} ({p.get('location_name', '')}). "
                f"Zaznacz, kiedy możesz pracować, najpóźniej do {_day(p.get('deadline'))}."
            )
        case "schedule_published":
            where = f"na okres {_range(p)} ({p.get('location_name', '')})"
            if p.get("changed"):
                return f"Grafik {where} został poprawiony. Sprawdź swoje zmiany."
            return f"Jest nowy grafik {where}. Sprawdź swoje zmiany."
        case "shift_offered":
            return f"{giver} oddaje zmianę: {shift}. Jeśli możesz ją wziąć, naciśnij „Biorę” w „Mój grafik”."
        case "shift_claimed":
            return f"{taker} chce wziąć zmianę od: {giver} ({shift}). Zatwierdź albo odrzuć w „Oddane zmiany”."
        case "claim_approved":
            return f"Kierownik zatwierdził: bierzesz zmianę {shift}. Jest już w Twoim grafiku."
        case "claim_rejected":
            return f"Kierownik nie zatwierdził wzięcia zmiany {shift}. Ta zmiana nie jest Twoja."
        case "offer_taken":
            return f"Kierownik zatwierdził: Twoją zmianę {shift} bierze {taker}. Nie musisz na nią przychodzić."
        case "offer_cancelled":
            return f"{giver} jednak zostaje na zmianie {shift}. Nie musisz jej brać."
        case "offer_expired":
            return f"Oddanie zmiany {shift} jest nieaktualne, bo grafik się zmienił. Sprawdź „Mój grafik”."
    return "Masz nowe powiadomienie."
