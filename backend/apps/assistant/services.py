"""What happens around a call to the assistant: what is sent, how the answer is checked, what is saved.

Employee requests: `queue_request` (API, same transaction as saving the request) and `interpret_request`
(worker). Manager commands: `submit_command` (API), `run_command` (worker) and `apply_command` (API, after the
manager accepts the plan). The assistant's answer is only a proposal; every name and number in it is checked
against the location's own data, and the sentences the manager sees are built here, not by the model.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from ninja.errors import HttpError

from apps.assistant import agreements, llm, readings, tools
from apps.assistant import context as facts
from apps.assistant.models import AssistantCommand, ManagerInstruction
from apps.availability.models import AvailabilityDay, AvailabilityState, TextRequest
from apps.rules.services import NUMBER_PARAMS
from apps.scheduling.models import SchedulePeriod
from apps.staffing.models import EmployeeProfile, Position, ShiftType, StaffingRule, works_in_q
from apps.tenancy.context import TenantContext
from apps.tenancy.models import Location
from engine.rules_catalog import RULES_BY_CODE

logger = logging.getLogger(__name__)

COMMAND_MAX_AGE = timedelta(hours=24)
# A message still "being read" after this long lost its job (worker down, deploy): it is failed, never left waiting.
STALE_AFTER = timedelta(minutes=15)
UNRELATED_REPLY = (
    "Pomagam w sprawach Grafikomatu i tego lokalu: odpowiadam na pytania o grafik, dyspozycje, godziny i oddane "
    "zmiany oraz ustawiam zasady układania grafiku. Na to pytanie nie odpowiem. Nic się nie zmieniło."
)
UNRELATED_REQUEST_REPLY = (
    "Odpowiadam tylko w sprawach pracy w tym lokalu: Twojego grafiku, dyspozycji, godzin, oddawania zmian i próśb "
    "o układanie grafiku. Na to pytanie nie odpowiem."
)
# Kept for messages saved before 19.11.2026 (same marker in `interpretation["type"]`).
OUT_OF_SCOPE_REPLY = UNRELATED_REPLY
OUT_OF_SCOPE_REQUEST_REPLY = UNRELATED_REQUEST_REPLY
LIMIT_REPLY = (
    "Masz już {limit} próśb na ten okres, więc tej nie zapisałem. Usuń albo popraw którąś w „Twoich prośbach” "
    "i napisz jeszcze raz. Na pytania odpowiadam dalej."
)
NOT_UNDERSTOOD_REPLY = "Nie wiem, jak na to odpowiedzieć. Napisz to inaczej albo zapytaj kierownika."
MAX_PREFERENCES = 3
PARTIAL_NOTE = "Części tej wiadomości nie da się zamienić na ustawienie. Kierownik przeczyta ją sam."

WEEKDAY_NAMES = ("poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela")
WEEKDAY_SHORT = ("pon.", "wt.", "śr.", "czw.", "pt.", "sob.", "niedz.")
MAX_ACTIONS = 12  # changes one command may propose


# --------------------------------------------------------------------------------------------- what is sent


def _people(location: Location, exclude_id=None) -> dict[str, str]:
    """label -> employee id for the active people of a location (first names; see `readings.labels`)."""
    profiles = (
        EmployeeProfile.objects.for_company(location.company_id)
        .filter(works_in_q(location), is_active=True)
        .select_related("membership__user")
    )
    return readings.labels(
        (str(p.pk), p.membership.user.first_name, p.membership.user.last_name) for p in profiles if p.pk != exclude_id
    )


def _shift_types(location: Location) -> list[ShiftType]:
    rows = ShiftType.objects.for_company(location.company_id).filter(location=location)
    return list(rows.order_by("start_time", "name"))


def _shift_lines(shift_types: list[ShiftType]) -> str:
    def hours(shift: ShiftType) -> str:
        if shift.start_time is None or shift.end_time is None:
            return "dowolne godziny"
        return f"{shift.start_time:%H:%M}–{shift.end_time:%H:%M}"

    def label(shift: ShiftType) -> str:
        return f"{shift.name} ({hours(shift)}{', zamyka lokal' if shift.is_closing else ''})"

    return ", ".join(label(s) for s in shift_types) or "(brak)"


def _today_line(today: date) -> str:
    return f"Dzisiaj: {today.isoformat()} ({WEEKDAY_NAMES[today.weekday()]})."


def _now_line(location: Location) -> str:
    """The wall-clock time of the location ("wychodzę teraz" in a report of other hours)."""
    return f"Teraz: {timezone.now().astimezone(ZoneInfo(location.timezone)):%H:%M} (czas lokalu)."


def request_span(text_request: TextRequest) -> tuple[date, date]:
    """The days a request can be about: its period, or its whole month when there is no period yet."""
    if text_request.period_id:
        return text_request.period.start, text_request.period.end
    first = text_request.month
    return first, (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def request_context(
    text_request: TextRequest,
    today: date,
    previous: list[TextRequest] | None = None,
    asked: list[TextRequest] | None = None,
) -> tuple[str, dict[str, str], dict[str, str]]:
    location = text_request.location
    start, end = request_span(text_request)
    people = _people(location, exclude_id=text_request.employee_id)
    shift_types = _shift_types(location)
    positions = sorted(p.name for p in text_request.employee.positions.all() if p.removed_at is None)
    if text_request.period_id:
        span = (
            f"Okres tej wiadomości (kierownik prosi o dyspozycje): od {start.isoformat()} do {end.isoformat()}, "
            f"period_id={text_request.period_id}."
        )
    else:
        span = (
            f"Miesiąc tej wiadomości (bez okresu grafiku; prośba będzie czekać na niego): od {start.isoformat()} "
            f"do {end.isoformat()}."
        )
    context = "\n".join(
        [
            _today_line(today),
            _now_line(location),
            f"Lokal główny: {location.name}.",
            span,
            f"Twoje stanowiska: {', '.join(positions) or '(brak)'}.",
            f"Współpracownicy: {', '.join(people) or '(brak)'}.",
            f"Zmiany w lokalu: {_shift_lines(shift_types)}.",
            facts.request_history(previous if previous is not None else facts.prior_requests(text_request)),
            facts.conversation(text_request),
            facts.open_questions(asked) if asked else "",
        ]
    )
    return context, people, {s.name: str(s.pk) for s in shift_types}


# --------------------------------------------------------------------------------------------- employee requests


def queue_request(text_request: TextRequest) -> None:
    """Call inside the transaction that saves the request. Without a key the manager reads it as written."""
    if not llm.is_enabled():
        text_request.status = TextRequest.Status.NEEDS_MANAGER
        text_request.interpretation = None
        text_request.unread_reason = TextRequest.UnreadReason.OFF
        text_request.save(update_fields=["status", "interpretation", "unread_reason", "updated_at"])
        return
    from apps.assistant.tasks import interpret_text_request  # tasks import this module

    interpret_text_request.defer(request_id=str(text_request.pk), text=text_request.text)


def saved_requests(row: TextRequest):
    """The person's requests that count toward `TEXT_REQUESTS_PER_PERIOD` in the scope of `row` (itself excluded)."""
    scope = {"period_id": row.period_id} if row.period_id else {"period__isnull": True, "month": row.month}
    return (
        TextRequest.objects.for_company(row.company_id)
        .filter(employee_id=row.employee_id, status__in=TextRequest.COUNTED, **scope)
        .exclude(pk=row.pk)
    )


def interpret_request(request_id: str, text: str | None = None, today: date | None = None) -> str:
    """Worker: read one message, answer it and save the preferences in it. Returns the new status (or "skipped")."""
    row = (
        TextRequest.objects.select_related(  # worker: by id
            "period__location", "employee__home_location", "employee__membership__user"
        )
        .filter(pk=request_id)
        .first()
    )
    if row is None or row.status != TextRequest.Status.NEW or (text is not None and row.text != text):
        return "skipped"  # deleted, already read, or edited since (the newer job reads it)
    today = today or timezone.localdate()
    outcome = _Outcome(TextRequest.Status.NEEDS_MANAGER, reason=TextRequest.UnreadReason.OFF)
    if llm.is_enabled():
        outcome.reason = TextRequest.UnreadReason.FAILED
        toolbox = tools.employee_toolbox(row.employee.membership.user, row.company_id)
        try:
            previous = facts.prior_requests(row)
            asked = waiting_questions(row)
            context, people, shift_types = request_context(row, today, previous, asked)
            reply = llm.read_request(row.text, context, toolbox)
            outcome = _checked_reply(reply, row, people, shift_types, previous, today, asked)
        except llm.AssistantError as exc:
            logger.warning("request %s left to the manager: %s", row.pk, exc)
            outcome.answer = {"error": str(exc)}
        except Exception as exc:
            # Whatever goes wrong, the request must not stay "being read" forever: the manager reads it.
            logger.exception("request %s left to the manager after an unexpected error", row.pk)
            outcome.answer = {"error": type(exc).__name__}
        if outcome.answer is not None and toolbox.calls:
            outcome.answer["tools"] = toolbox.calls
    with transaction.atomic():
        rows = TextRequest.objects.for_company(row.company_id)
        locked = rows.select_for_update().filter(pk=row.pk, status=TextRequest.Status.NEW, text=row.text).first()
        if locked is None:
            return "skipped"
        replacement = outcome.replacement
        if replacement is not None:
            old = (
                rows.select_for_update()
                .filter(
                    pk=replacement.pk,
                    employee_id=row.employee_id,
                    period_id=row.period_id,
                    month=row.month,
                    updated_at=replacement.updated_at,
                )
                .exclude(
                    status__in=[TextRequest.Status.SUPERSEDED, TextRequest.Status.NEW, TextRequest.Status.ANSWERED]
                )
                .first()
            )
            if old is None:
                outcome.status, outcome.interpretation = TextRequest.Status.NEEDS_MANAGER, None
                outcome.reason = TextRequest.UnreadReason.UNSURE
                outcome.answer = {"why": "wcześniejsza prośba zmieniła się podczas odczytu", **(outcome.raw or {})}
                replacement = None
            else:
                locked.supersedes = old
                locked.employee_corrected = True
                if locked.updated_at == row.updated_at:
                    # A newer manager decision on the correction itself takes precedence.
                    locked.manager_priority = old.manager_priority
                    locked.manager_rejected = old.manager_rejected or old.status == TextRequest.Status.REJECTED
                old.status = TextRequest.Status.SUPERSEDED
                old.save(update_fields=["status", "updated_at"])
        limit = settings.TEXT_REQUESTS_PER_PERIOD
        if (
            limit
            and outcome.status in TextRequest.COUNTED
            and replacement is None
            and llm.is_enabled()
            and saved_requests(row).count() >= limit
        ):
            # Questions keep working at the limit; a new request does not take a place that is not free.
            outcome.status, outcome.interpretation = TextRequest.Status.ANSWERED, None
            outcome.reason = TextRequest.UnreadReason.NONE
            outcome.reply = " ".join(filter(None, [outcome.reply, LIMIT_REPLY.format(limit=limit)]))
        locked.status = outcome.status
        locked.interpretation = outcome.interpretation
        locked.unread_reason = outcome.reason
        locked.assistant_answer = outcome.answer
        locked.reply = outcome.reply[:2000]
        locked.hours_reports = outcome.hours_reports or None
        locked.question = outcome.question[:500]
        # The question may have been taken back (deleted) while the answer was being read.
        answer_to = outcome.answer_to
        locked.answer_to = answer_to if answer_to is not None and rows.filter(pk=answer_to.pk).exists() else None
        locked.save(
            update_fields=[
                "hours_reports",
                "question",
                "answer_to",
                "status",
                "interpretation",
                "unread_reason",
                "assistant_answer",
                "reply",
                "updated_at",
                "supersedes",
                "employee_corrected",
                "manager_priority",
                "manager_rejected",
            ]
        )
    return outcome.status


class _Outcome:
    """What reading one message gives: the new status and what is saved with it."""

    def __init__(self, status, *, reason=TextRequest.UnreadReason.NONE):
        self.status = status
        self.reason = reason
        self.interpretation: dict[str, Any] | None = None
        self.reply = ""
        self.answer: dict[str, Any] | None = None  # for the list of misses (`assistant_answer`)
        self.raw: dict[str, Any] | None = None  # the model's own answer
        self.replacement: TextRequest | None = None
        # Reports of other hours to show with "Wyślij kierownikowi" (checked; nothing is sent by itself).
        self.hours_reports: list[dict[str, Any]] = []
        # The assistant's question back to the person (nothing of the message is saved until they answer).
        self.question = ""
        # The earlier message whose question this one answers.
        self.answer_to: TextRequest | None = None


def waiting_questions(row: TextRequest) -> list[TextRequest]:
    """The assistant's questions waiting for an answer, oldest first: on the person's earlier messages of the same
    chat (period or month) that the assistant still remembers (`context.MAX_CONVERSATION`), when no other message
    answered them. A question waits while the person writes about other things (Piotr, 22.11.2026)."""
    rows = (
        TextRequest.objects.for_company(row.company_id)
        .filter(employee_id=row.employee_id, period_id=row.period_id, month=row.month, created_at__lt=row.created_at)
        .order_by("-created_at", "-pk")
        .prefetch_related("answers")[: facts.MAX_CONVERSATION]
    )
    return [
        r
        for r in reversed(rows)
        if r.status == TextRequest.Status.ANSWERED and r.question and all(a.pk == row.pk for a in r.answers.all())
    ]


def _namesake_question(reply: llm.EmployeeReply, people: dict[str, str]) -> str:
    """A question the app asks by itself when a preference names a first name that several co-workers share
    ("Ania" with Ania K. and Ania M. on the list): never guess which one."""
    for preference in reply.preferences:
        wanted = (preference.person or "").strip().casefold()
        if not wanted or any(label.casefold() == wanted for label in people):
            continue
        namesakes = [label for label in people if label.split(" ", 1)[0].casefold() == wanted]
        if len(namesakes) > 1:
            return f"O którą osobę chodzi: {', '.join(namesakes[:-1])} czy {namesakes[-1]}?"
    return ""


def _checked_reply(
    reply: llm.EmployeeReply,
    row: TextRequest,
    people: dict[str, str],
    shift_types: dict[str, str],
    previous: list[TextRequest],
    today: date | None = None,
    asked: list[TextRequest] | None = None,
) -> _Outcome:
    raw = reply.model_dump(mode="json")
    answer = reply.answer.strip()[:2000]
    if reply.topic == "unrelated":
        outcome = _Outcome(TextRequest.Status.REJECTED)
        outcome.interpretation = {"type": "out_of_scope", "summary": UNRELATED_REQUEST_REPLY}
        outcome.answer, outcome.raw = {"why": "poza tematem", **raw}, raw
        return outcome
    hours, hours_notes = checked_hours(reply.hours_changes, row, today or timezone.localdate())
    # One question per request: the answer to it is read with the first message, and what is still unclear after
    # that goes to the manager.
    number = reply.answers_question
    answered = asked[number - 1] if asked and isinstance(number, int) and 1 <= number <= len(asked) else None
    answering = answered is not None
    question = (reply.question or "").strip() or ("" if answering else _namesake_question(reply, people))
    if question and not answering:
        # Nothing of this message is saved until the person answers (not even the parts the model was sure of).
        outcome = _Outcome(TextRequest.Status.ANSWERED)
        outcome.question, outcome.reply, outcome.raw = question, answer, raw
    elif question:
        outcome = _Outcome(TextRequest.Status.NEEDS_MANAGER, reason=TextRequest.UnreadReason.UNSURE)
        outcome.reply = answer
        outcome.answer, outcome.raw = {"why": "drugie pytanie", **raw}, raw
    else:
        outcome = _checked_preferences(reply, row, people, shift_types, previous, raw, answer, bool(hours))
    if answering:
        outcome.answer_to = answered
    outcome.hours_reports = hours
    if hours_notes:
        outcome.reply = " ".join(filter(None, [outcome.reply, *hours_notes]))
        if (
            not hours
            and outcome.status == TextRequest.Status.ANSWERED
            and outcome.reply.startswith(NOT_UNDERSTOOD_REPLY)
        ):
            outcome.reply = " ".join(hours_notes)
    return outcome


def _checked_preferences(
    reply: llm.EmployeeReply,
    row: TextRequest,
    people: dict[str, str],
    shift_types: dict[str, str],
    previous: list[TextRequest],
    raw: dict[str, Any],
    answer: str,
    has_hours: bool,
) -> _Outcome:
    span = request_span(row)
    parts, why = [], ""
    if len(reply.preferences) > MAX_PREFERENCES:
        why = "za dużo próśb w jednej wiadomości"
    for preference in reply.preferences[:MAX_PREFERENCES]:
        if why:
            break
        data, why = _checked_preference(preference, span, people, shift_types, row.text)
        if data is not None:
            parts.append(data)
    replacement = None
    if parts and not why and reply.replaces_request is not None:
        number = reply.replaces_request
        if 1 <= number <= len(previous) and len(parts) == 1:
            replacement = previous[number - 1]
        else:
            why = "niejednoznaczna korekta"
    if why:
        # The model believed it understood, the app could not check it: the manager reads the text as written.
        outcome = _Outcome(TextRequest.Status.NEEDS_MANAGER, reason=TextRequest.UnreadReason.UNSURE)
        outcome.answer, outcome.raw = {"why": why, **raw}, raw
        return outcome
    if parts:
        outcome = _Outcome(TextRequest.Status.INTERPRETED)
        outcome.interpretation = _combined(parts, row)
        if reply.leave_to_manager:
            # Part of the message is no setting: what could be set is saved, the rest the manager reads.
            outcome.interpretation["partial"] = True
            outcome.interpretation["notes"] = [*outcome.interpretation.get("notes", []), PARTIAL_NOTE]
        outcome.reply = answer
        outcome.replacement = replacement
        outcome.raw = raw
        return outcome
    if reply.leave_to_manager:
        outcome = _Outcome(TextRequest.Status.NEEDS_MANAGER, reason=TextRequest.UnreadReason.UNSURE)
        outcome.reply = answer
        outcome.answer, outcome.raw = {"why": "nie pasuje do żadnego typu", **raw}, raw
        return outcome
    outcome = _Outcome(TextRequest.Status.ANSWERED)
    outcome.reply = answer or (HOURS_READY_REPLY if has_hours else NOT_UNDERSTOOD_REPLY)
    outcome.raw = raw
    return outcome


MAX_HOURS_REPORTS = 3
HOURS_READY_REPLY = "Przygotowałem zgłoszenie innych godzin. Sprawdź je niżej i wyślij kierownikowi."


def _hours_problem(day: date | None, text: str) -> str:
    where = f" na {WEEKDAY_SHORT[day.weekday()]} {day:%d.%m}" if day else ""
    return f"Nie przygotowałem zgłoszenia godzin{where}: {text}"


def _runs_into(moments, shift) -> bool:
    return moments[0] < shift.end_at and moments[1] > shift.start_at


def _clock(text: str):
    """'' -> None (the hour does not change); "GG:MM" -> time; anything else raises a Polish HttpError."""
    from apps.worktime.services import parse_time

    text = (text or "").strip()
    return parse_time(text) if text else None


def _given_hours(assignments: list, start, end) -> list[tuple[Any, Any, Any]]:
    """(assignment, start, end) for published shifts of one person on one day; a missing hour is the one that
    counts now. With two shifts that day, only the one the hours run into."""
    from apps.worktime import services as worktime

    current = worktime.worked_hours(assignments)
    rows = []
    for assignment in assignments:
        tz = ZoneInfo(assignment.shift.location.timezone)
        worked = current[assignment.pk]
        rows.append(
            (
                assignment,
                start or worked.start_at.astimezone(tz).time().replace(second=0, microsecond=0),
                end or worked.end_at.astimezone(tz).time().replace(second=0, microsecond=0),
            )
        )
    if len(rows) > 1:
        rows = [r for r in rows if _runs_into(worktime.resolve(r[0].shift, r[1], r[2]), r[0].shift)]
    return rows


def checked_hours(
    items: list[llm.HoursReport], row: TextRequest, today: date
) -> tuple[list[dict[str, Any]], list[str]]:
    """The assistant's reports of other hours, checked against the person's published shifts as the endpoint
    checks them: (proposals to show with "Wyślij kierownikowi", sentences about the ones that cannot be sent)."""
    from apps.scheduling.models import Assignment, ScheduleVersion
    from apps.worktime import services as worktime

    proposals: dict[str, dict[str, Any]] = {}
    notes: list[str] = []
    for item in items[:MAX_HOURS_REPORTS]:
        day = readings._parse_date(item.date)
        try:
            start, end = _clock(item.start_time), _clock(item.end_time)
        except HttpError:
            notes.append(_hours_problem(day, "nie rozumiem godzin. Zgłoś je w „Mój grafik” przy zmianie."))
            continue
        if day is None or (start is None and end is None):
            notes.append(_hours_problem(day, "nie rozumiem dnia albo godzin. Zgłoś je w „Mój grafik” przy zmianie."))
            continue
        candidates = list(
            Assignment.objects.for_company(row.company_id)
            .filter(
                employee_id=row.employee_id,
                shift__version__status=ScheduleVersion.Status.PUBLISHED,
                shift__date=day,
            )
            .select_related("shift__version", "shift__location", "shift__position")
        )
        if not candidates:
            notes.append(_hours_problem(day, "nie widzę Twojej zmiany tego dnia w opublikowanym grafiku."))
            continue
        found = _given_hours(candidates, start, end)
        if len(found) != 1:
            notes.append(_hours_problem(day, "masz tego dnia kilka zmian. Zgłoś godziny w „Mój grafik”."))
            continue
        assignment, start, end = found[0]
        try:
            start_at, end_at = worktime.check_report(assignment, start, end, today=today)
        except HttpError as exc:
            notes.append(_hours_problem(day, exc.message[:1].lower() + exc.message[1:]))
            continue
        shift = assignment.shift
        tz = ZoneInfo(shift.location.timezone)
        planned = (shift.end_at - shift.start_at).total_seconds()
        proposals[str(assignment.pk)] = {
            "assignment_id": str(assignment.pk),
            "period_id": str(shift.version.period_id),
            "slot_key": shift.slot_key,
            "date": day.isoformat(),
            "start_time": worktime.local_time(start_at, tz),
            "end_time": worktime.local_time(end_at, tz),
            "planned_start_time": worktime.local_time(shift.start_at, tz),
            "planned_end_time": worktime.local_time(shift.end_at, tz),
            "difference": round(((end_at - start_at).total_seconds() - planned) / 60),
            "location_name": shift.location.name,
            "position_name": shift.position.name,
            "reason": item.reason.strip()[: worktime.REASON_MAX],
        }
    if len(items) > MAX_HOURS_REPORTS:
        notes.append(f"Przygotowałem najwyżej {MAX_HOURS_REPORTS} zgłoszenia. Resztę zgłoś w „Mój grafik”.")
    return list(proposals.values()), notes


def _checked_preference(
    preference: llm.Preference, span: tuple[date, date], people: dict[str, str], shift_types: dict[str, str], text: str
) -> tuple[dict[str, Any] | None, str]:
    """(checked part of an interpretation, "") or (None, why it cannot be used). `span`: the days it can be about."""
    start, end = span[0].isoformat(), span[1].isoformat()
    confidence = min(1.0, max(0.0, float(preference.confidence)))
    if any(not start <= d <= end for d in preference.dates):
        return None, "dni spoza okresu"
    data = readings.clean(
        type=preference.type,
        person=preference.person,
        shift_type=preference.shift_type,
        avoid=preference.avoid_shift_type,
        max_hours=preference.max_hours,
        max_shifts=preference.max_shifts,
        hours_period=readings.hour_scope(preference.hours_period, text, preference.max_hours),
        dates=preference.dates,
        weekdays=preference.weekdays,
        min_days=preference.min_days,
        shifts_per_day=preference.shifts_per_day,
        people=people,
        shift_types=shift_types,
    )
    if data is None:
        return None, "osoba, zmiana, godziny lub dni nie pasują do lokalu"
    if confidence < settings.ASSISTANT_MIN_CONFIDENCE:
        return None, f"pewność {confidence:.2f}"
    if preference.cannot and data["type"] == "wolne_dni" and data["dates"]:
        data["cannot"] = True
    summary = readings.describe(
        data,
        "Ty" if data["type"] in ("unikaj_osoby", "preferuj_osobe") else "",
        {pid: name for name, pid in people.items()},
        {sid: name for name, sid in shift_types.items()},
    ).lstrip(": ")
    data.update(level=preference.level, confidence=round(confidence, 2), summary=_sentence(summary))
    return data, ""


def _sentence(text: str) -> str:
    text = text.strip().rstrip(".")
    return f"{text[:1].upper()}{text[1:]}." if text else ""


def _combined(parts: list[dict[str, Any]], row: TextRequest) -> dict[str, Any]:
    """The first part at the top (as single readings always were), the others in `more`, one summary for all."""
    first = dict(parts[0])
    notes = shift_notes(parts, row)
    if len(parts) > 1:
        first["more"] = [dict(part) for part in parts[1:]]
        first["part_summary"] = first["summary"]

        def clause(n: int, summary: str) -> str:
            summary = summary.rstrip(".")
            return summary if n == 0 or summary.startswith("Ty ") else summary[:1].lower() + summary[1:]

        first["summary"] = _sentence("; ".join(clause(n, part["summary"]) for n, part in enumerate(parts)))
    if notes:
        first["notes"] = notes
    return first


def shift_notes(parts: list[dict[str, Any]], row: TextRequest) -> list[str]:
    """A shift preference about a shift the person's positions never staff changes nothing: say so."""
    shift_ids = {
        part["shift_type"]
        for part in parts
        if part.get("type") in ("typ_zmiany", "limit_zmian") and part.get("shift_type")
    }
    if not shift_ids:
        return []
    staffed = {
        str(pk)
        for pk in StaffingRule.objects.for_company(row.company_id)
        .filter(shift_type_id__in=shift_ids, position__in=row.employee.positions.all(), count__gt=0)
        .values_list("shift_type_id", flat=True)
    }
    names = {
        str(pk): name
        for pk, name in ShiftType.objects.for_company(row.company_id).filter(pk__in=shift_ids).values_list("pk", "name")
    }
    return [
        f"Na Twoim stanowisku nie ma zmiany „{names.get(pk, '?')}”, więc ta prośba niczego nie zmieni."
        for pk in sorted(shift_ids)
        if pk not in staffed
    ]


def fail_stale_messages(now=None) -> int:
    """Messages whose job was lost: employee requests go to the manager (who can hand them over again), manager
    commands fail with a message. Run by a periodic job; it never generates or changes a schedule."""
    now = now or timezone.now()
    cutoff = now - STALE_AFTER
    requests = TextRequest.objects.filter(  # periodic job over all companies
        status=TextRequest.Status.NEW, updated_at__lt=cutoff
    ).update(
        status=TextRequest.Status.NEEDS_MANAGER,
        unread_reason=TextRequest.UnreadReason.FAILED,
        assistant_answer={"error": "stale"},
        updated_at=now,
    )
    commands = AssistantCommand.objects.filter(  # periodic job over all companies
        status=AssistantCommand.Status.QUEUED, created_at__lt=cutoff
    ).update(status=AssistantCommand.Status.FAILED, assistant_answer={"error": "stale"})
    return requests + commands


# --------------------------------------------------------------------------------------------- manager commands


def _month_start():
    return timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def submit_command(ctx: TenantContext, location: Location, text: str, period_id=None) -> AssistantCommand:
    """Save the command and defer the assistant's job in one transaction (or mark it "assistant is off")."""
    text = text.strip()
    if not text:
        raise HttpError(400, "Napisz, co ma się zmienić.")
    limit = settings.ASSISTANT_COMMANDS_MONTHLY_LIMIT  # 0 = no limit
    if limit and ctx.qs(AssistantCommand).filter(created_at__gte=_month_start()).count() >= limit:
        raise HttpError(429, "Wykorzystano miesięczny limit poleceń dla asystenta. Zasady możesz zmienić ręcznie.")
    with transaction.atomic():
        agreements.lock_location(location)
        rule_set = agreements.for_command(location, period_id)
        command = AssistantCommand.objects.for_company(ctx.company).create(
            company=ctx.company, location=location, text=text, created_by=ctx.user, rule_set=rule_set
        )
        if llm.is_enabled():
            from apps.assistant.tasks import plan_assistant_command  # tasks import this module

            plan_assistant_command.defer(command_id=str(command.pk))
        else:
            command.status = AssistantCommand.Status.UNAVAILABLE
            command.save(update_fields=["status"])
    return command


def rules_scope(ctx: TenantContext, location: Location, rule_set=None):
    return agreements.scope(ctx, location, rule_set)


def _rule_items(sc) -> list:
    from apps.rules.api import RuleItemIn, _rules_out

    return [
        RuleItemIn(code=i.code, enabled=i.enabled, is_hard=i.is_hard, params=i.params) for i in _rules_out(sc).items
    ]


def _instructions(location: Location, rule_set=None) -> list[ManagerInstruction]:
    rows = ManagerInstruction.objects.for_company(location.company_id).filter(location=location, rule_set=rule_set)
    return list(rows.select_related("employee__membership__user").order_by("position", "created_at"))


def instruction_text(row: ManagerInstruction, names: dict[str, str], shift_names: dict[str, str]) -> str:
    description = readings.describe(
        readings.saved_reading(row.data, row.source_text),
        names.get(str(row.employee_id), "Osoba spoza lokalu"),
        names,
        shift_names,
    )
    return description + readings.legacy_hours_notice(row.data, row.source_text)


def command_context(
    location: Location, sc, today: date, instructions: list[ManagerInstruction], reports: list | None = None
) -> str:
    people = _people(location)
    names = {pid: label for label, pid in people.items()}
    shift_types = _shift_types(location)
    shift_names = {str(s.pk): s.name for s in shift_types}
    positions = (
        Position.objects.for_company(location.company_id)
        .filter(location=location, removed_at__isnull=True)
        .order_by("name")
    )
    position_names = {str(p.pk): p.name for p in positions}
    periods = list(
        SchedulePeriod.objects.for_company(location.company_id)
        .filter(location=location, end__gte=today - timedelta(days=62))
        .order_by("start")[:8]
    )
    period_words = (
        "; ".join(
            f"od {p.start.isoformat()} do {p.end.isoformat()} ({p.get_status_display()}, period_id={p.pk})"
            for p in periods
        )
        or "jeszcze żadnych"
    )
    lines = [
        _today_line(today),
        _now_line(location),
        f"Bieżący lokal: {location.name}.",
        f"Okresy grafiku lokalu (ostatnie i przyszłe): {period_words}.",
        f"Osoby: {', '.join(people) or '(brak)'}.",
        f"Stanowiska: {', '.join(position_names.values()) or '(brak)'}.",
        f"Zmiany: {_shift_lines(shift_types)}.",
        "",
        "Zasady z katalogu (kolejność = ważność, 1 = najważniejsza):",
    ]
    for place, item in enumerate(_rule_items(sc), start=1):
        rule = RULES_BY_CODE[item.code]
        state = "wyłączona" if not item.enabled else "włączona, bez wyjątków" if item.is_hard else "włączona"
        settings_ = []
        for name, value in item.params.items():
            if name in NUMBER_PARAMS:
                settings_.append(f"liczba ({NUMBER_PARAMS[name][2]}): {value}")
            elif name == "position":
                settings_.append(f"stanowisko: {position_names.get(str(value), 'nie wybrano')}")
            elif name == "shift_type":
                settings_.append(f"zmiana: {shift_names.get(str(value), 'nie wybrano')}")
        extra = f"; {'; '.join(settings_)}" if settings_ else ""
        lines.append(f"{place}. [{rule.code}] {rule.label}: {state}{extra}. {rule.description}")
    lines += ["", "Polecenia o osobach (kolejność = ważność):"]
    for number, row in enumerate(instructions, start=1):
        lines.append(f"{number}. {instruction_text(row, names, shift_names)}")
    if not instructions:
        lines.append("(brak)")
    lines += ["", "Zgłoszenia innych godzin czekające na decyzję (numery do hours_decisions):"]
    for number, (change, assignment) in enumerate(reports or [], start=1):
        reason = f" Powód: {change.reason}." if change.reason else ""
        lines.append(f"{number}. {_report_words(change, assignment)}.{reason}")
    if not reports:
        lines.append("(brak)")
    return "\n".join(lines)


def agreements_line(rule_set) -> str:
    """Which period the plan changes: instructions about days outside it would change no schedule."""
    if rule_set is None or rule_set.period_id is None:
        return (
            "Ustalenia na okres: czekają na prośbę o dyspozycje (okresu jeszcze nie ma). Polecenia o osobach "
            "zaczną działać w pierwszym okresie, o którego dyspozycje kierownik poprosi."
        )
    period = rule_set.period
    return (
        f"Ustalenia na okres: od {period.start.isoformat()} do {period.end.isoformat()} "
        f"(period_id={period.pk}). Daty w poleceniach o osobach muszą leżeć w tym okresie."
    )


def run_command(command_id: str, today: date | None = None) -> str:
    """Worker: ask the assistant, check its plan and save it for the manager to accept. Safe to run twice."""
    command = (
        AssistantCommand.objects.select_related("location", "company", "rule_set__period", "created_by")
        .filter(pk=command_id)  # worker: by id
        .first()
    )
    if command is None or command.status != AssistantCommand.Status.QUEUED:
        return "skipped"
    today = today or timezone.localdate()
    status, plan, raw = AssistantCommand.Status.FAILED, None, None
    # Reads run as the manager who wrote: the assistant sees what they see in the app, nothing more.
    toolbox = (
        tools.manager_toolbox(command.created_by, command.company_id, command.location_id)
        if command.created_by is not None
        else None
    )
    try:
        sc = rules_scope(_SystemContext(command.company), command.location, command.rule_set)
        instructions = _instructions(command.location, command.rule_set)
        # Numbered once: the plan's "report 2" is the report the assistant saw as 2.
        reports = pending_hours(command.location)
        context = "\n".join(
            [
                agreements_line(command.rule_set),
                command_context(command.location, sc, today, instructions, reports),
                facts.command_history(command),
            ]
        )
        answer = llm.plan_command(command.text, context, toolbox)
        raw = answer.model_dump(mode="json")
        period = command.rule_set.period if command.rule_set_id and command.rule_set.period_id else None
        status, plan = (
            AssistantCommand.Status.READY,
            check_plan(
                command.location, sc, answer, command.text, instructions, period=period, today=today, reports=reports
            ),
        )
    except llm.AssistantError as exc:
        logger.warning("assistant command %s failed: %s", command.pk, exc)
        raw = {"error": str(exc)}
    except Exception as exc:
        # Whatever goes wrong, the manager must get an answer instead of waiting forever.
        logger.exception("assistant command %s failed with an unexpected error", command.pk)
        raw = {**(raw or {}), "error": type(exc).__name__}
    if toolbox is not None and toolbox.calls:
        raw = {**(raw or {}), "tools": toolbox.calls}
    AssistantCommand.objects.for_company(command.company_id).filter(
        pk=command.pk, status=AssistantCommand.Status.QUEUED
    ).update(status=status, plan=plan, assistant_answer=raw)
    return status


class _SystemContext:
    """Enough of a tenant context for reading one company's rules in the worker (no user, no permissions)."""

    def __init__(self, company) -> None:
        self.company = company

    def qs(self, model):
        return model.objects.for_company(self.company)


def _number_param(code: str) -> str | None:
    return next((name for name in RULES_BY_CODE[code].params if name in NUMBER_PARAMS), None)


# Like the availability calendar: an instruction about days further ahead is most likely a wrong year.
MAX_DAYS_AHEAD = 366
BLOCKED_REPLY = (
    "Nie mogę zapisać tego planu. Sprawdź uwagi poniżej i napisz polecenie jeszcze raz. Nic się nie zmieniło."
)
CHANGES_REPLY = "Proponuję zmiany wymienione niżej. Zapiszę je dopiero, gdy je zatwierdzisz."
NO_CHANGES_REPLY = "Nie ma żadnych zmian do zatwierdzenia. Ustawienia i grafik pozostały bez zmian."


def _out_of_scope_plan() -> dict[str, Any]:
    return {
        "scope": "out_of_scope",
        "out_of_scope": True,
        "reply": UNRELATED_REPLY,
        "question": None,
        "rule_changes": [],
        "new_instructions": [],
        "remove_instructions": [],
        "hours_changes": [],
        "hours_decisions": [],
        "lines": [],
        "effects": [],
        "notes": [],
        "informational": False,
    }


def _day_words(days: list[date]) -> str:
    return ", ".join(f"{d.day}.{d.month:02d}" for d in days[:6]) + (" i inne" if len(days) > 6 else "")


# ------------------------------------------------------------------------- arranging again (the manager's chat)

ARRANGE_NO_PERIOD = (
    "Grafik ułożę tylko na okres, o którego dyspozycje już poprosiłeś. Ułożysz go sam w zakładce „Grafik” lokalu."
)
ARRANGE_BUSY = "Grafik na ten okres właśnie się układa. Poczekaj na wynik i napisz polecenie jeszcze raz."
STALE_ARRANGE = "Grafiku z tego planu nie da się już ułożyć. Napisz polecenie jeszcze raz."


def _checked_arrange(location: Location, period: SchedulePeriod | None, *, different: bool):
    """(the plan's entry, its line, its note) when the period of the agreements can be arranged again, else
    (None, "", why not). Only a period that already has a schedule: the first arranging stays a button press."""
    from apps.scheduling.editing import latest_version, manual_changes
    from apps.scheduling.generation import ACTIVE

    if period is None:
        return None, "", ARRANGE_NO_PERIOD
    newest = latest_version(period)
    if newest is None:
        return (
            None,
            "",
            f"Grafik na okres {_period_label(period)} nie jest jeszcze ułożony. Ułóż go przyciskiem „Ułóż grafik” "
            "w zakładce „Grafik”, a potem napisz, co ma być inaczej.",
        )
    if location.archived_at is not None:
        return None, "", f"Lokal {location.name} jest w archiwum. Przywróć go, żeby ułożyć grafik."
    if period.generation_runs.filter(status__in=ACTIVE).exists():
        return None, "", ARRANGE_BUSY
    if different:
        line = f"Po zatwierdzeniu ułożę nowy grafik na okres {_period_label(period)}, wyraźnie inny niż obecny."
    else:
        line = f"Po zatwierdzeniu ułożę grafik na okres {_period_label(period)} od nowa."
    note = "Przypięte zmiany, osoby wpisane mimo przeszkód i minione dni zostają bez zmian."
    lost = manual_changes(newest)
    if lost:
        note += f" Stracisz ręczne poprawki bez przypięcia: {lost}."
    note += " Gdy nowy szkic będzie gorszy, usuń go koszem w „Grafik”, a wróci obecny."
    return {"period_id": str(period.pk), "different": different}, line, note


# ------------------------------------------------------------------------- other hours (the manager's chat)

MAX_LISTED_REPORTS = 20
HOURS_NOTE = (
    "Zmiany godzin zapiszę od razu po zatwierdzeniu, także w opublikowanym grafiku. Pracownik dostanie "
    "powiadomienie, a godziny policzą się w zestawieniu."
)
STALE_HOURS = "Grafik tej osoby zmienił się od przygotowania propozycji."


def pending_hours(location: Location) -> list[tuple[Any, Any]]:
    """(report, its published assignment) for reports of other hours waiting in the location, oldest first; only
    reports whose person still has the shift (the others end when the corrected schedule is published)."""
    from apps.worktime.models import HoursChange
    from apps.worktime.services import current_assignments

    rows = list(
        HoursChange.objects.for_company(location.company_id)
        .filter(location=location, status=HoursChange.Status.PENDING)
        .select_related("location", "employee__membership__user")
        .order_by("created_at", "pk")[: MAX_LISTED_REPORTS * 2]
    )
    current = current_assignments(rows)
    return [(row, current[row.pk]) for row in rows if row.pk in current][:MAX_LISTED_REPORTS]


def _report_words(change, assignment) -> str:
    """'Ania Nowak, pt. 20.11, 06:00–12:00 zamiast 06:00–14:00 (krócej o 2 h)'"""
    from apps.notifications.services import hours_words
    from apps.worktime.services import payload

    words = payload(change, assignment.shift)
    return f"{words['employee_name']}, {hours_words(words)}"


def _short_day(day: date) -> str:
    return f"{WEEKDAY_SHORT[day.weekday()]} {day:%d.%m}"


class _ManagerHours:
    """What the plan does with hours: checked decisions and changes, the plan's lines and notes about them."""

    def __init__(self) -> None:
        self.decisions: list[dict[str, Any]] = []
        self.changes: list[dict[str, Any]] = []
        self.lines: list[str] = []
        self.notes: list[str] = []
        self.already: list[str] = []
        self.rejected = False

    def refuse(self, note: str) -> None:
        self.notes.append(note)
        self.rejected = True


def _checked_manager_hours(
    location: Location, answer: llm.CommandPlan, reports: list[tuple[Any, Any]], people: dict[str, str]
) -> _ManagerHours:
    """The assistant's decisions on waiting reports and its changes of hours, checked as the endpoints check them.
    Nothing is saved: the manager accepts the whole plan or nothing."""
    from apps.notifications.services import hours_words
    from apps.scheduling.models import Assignment, ScheduleVersion
    from apps.worktime import services as worktime

    result = _ManagerHours()
    names = {pid: label for label, pid in people.items()}
    decided: dict[str, dict[str, Any]] = {}
    decision_lines: dict[str, str] = {}
    for decision in answer.hours_decisions[:MAX_ACTIONS]:
        if not 1 <= decision.report <= len(reports):
            result.refuse("Nie znalazłem zgłoszenia godzin o tym numerze. Czekające zgłoszenia są w „Godzinach”.")
            continue
        change, assignment = reports[decision.report - 1]
        key = str(change.pk)
        if key in decided and decided[key]["approve"] != decision.approve:
            result.refuse("To samo zgłoszenie godzin ma być i zatwierdzone, i odrzucone. Napisz, co z nim zrobić.")
            continue
        if decision.approve:
            try:
                worktime.check_approve(change, assignment)
            except HttpError as exc:
                result.refuse(f"Nie zatwierdzę zgłoszenia: {_report_words(change, assignment)}. {exc.message}")
                continue
        decided[key] = {"change_id": key, "approve": decision.approve, "assignment_id": str(assignment.pk)}
        verb = "Zatwierdzę" if decision.approve else "Odrzucę"
        decision_lines[key] = f"{verb} zgłoszenie: {_report_words(change, assignment)}."

    decided_shifts = {d["assignment_id"] for d in decided.values()}
    changed: dict[str, dict[str, Any]] = {}
    change_lines: dict[str, str] = {}
    for item in answer.hours_changes[:MAX_ACTIONS]:
        employee = readings._lookup(item.person, people)
        if employee is None:
            result.refuse(f"Nie znalazłem w tym lokalu osoby „{item.person}”.")
            continue
        name = names[employee]
        day = readings._parse_date(item.date)
        try:
            start, end = _clock(item.start_time), _clock(item.end_time)
        except HttpError:
            start = end = None
        if day is None or (start is None and end is None):
            result.refuse(f"Godziny osoby {name}: nie rozumiem dnia albo godzin. Podaj dzień i godziny od–do.")
            continue
        candidates = list(
            Assignment.objects.for_company(location.company_id)
            .filter(
                employee_id=employee,
                shift__location=location,
                shift__version__status=ScheduleVersion.Status.PUBLISHED,
                shift__date=day,
            )
            .select_related("shift__version", "shift__location", "shift__position", "employee__membership__user")
        )
        if not candidates:
            result.refuse(f"{name} nie ma zmiany w {_short_day(day)} w opublikowanym grafiku tego lokalu.")
            continue
        found = _given_hours(candidates, start, end)
        if len(found) != 1:
            result.refuse(f"{name} ma w {_short_day(day)} kilka zmian. Zmień godziny w zakładce „Grafik”.")
            continue
        assignment, start, end = found[0]
        key = str(assignment.pk)
        if key in decided_shifts:
            result.refuse(
                f"Dla zmiany osoby {name} w {_short_day(day)} jest decyzja o zgłoszeniu i nowe godziny naraz. "
                "Napisz jedno z nich."
            )
            continue
        try:
            start_at, end_at = worktime.check_set(assignment, start, end)
        except HttpError as exc:
            if exc.message == worktime.SAME_HOURS:
                result.already.append(f"godziny osoby {name} w {_short_day(day)}")
            else:
                result.refuse(f"Godziny osoby {name} w {_short_day(day)}: {exc.message}")
            continue
        shift = assignment.shift
        tz = ZoneInfo(shift.location.timezone)
        times = {
            "date": shift.date.isoformat(),
            "start_time": worktime.local_time(start_at, tz),
            "end_time": worktime.local_time(end_at, tz),
            "planned_start_time": worktime.local_time(shift.start_at, tz),
            "planned_end_time": worktime.local_time(shift.end_at, tz),
            "difference": round(((end_at - start_at) - (shift.end_at - shift.start_at)).total_seconds() / 60),
        }
        changed[key] = {
            "assignment_id": key,
            "employee": employee,
            "period_id": str(shift.version.period_id),
            "slot_key": shift.slot_key,
            "date": times["date"],
            "start_time": times["start_time"],
            "end_time": times["end_time"],
            "reason": item.reason.strip()[: worktime.REASON_MAX],
            # Applying checks that the hours and the waiting report are still what this plan was made for.
            "seen": worktime.Seen.of(assignment).as_dict(),
        }
        # The plan's lines name the person in full, as the lines about waiting reports do.
        full_name = assignment.employee.membership.user.full_name or name
        if (start_at, end_at) == (shift.start_at, shift.end_at):
            line = (
                f"Przywrócę godziny z grafiku: {full_name}, {_short_day(shift.date)}, "
                f"{times['planned_start_time']}–{times['planned_end_time']}."
            )
        else:
            line = f"Zmienię godziny: {full_name}, {hours_words(times)}."
        waiting = worktime.pending_reports([assignment]).get(assignment.pk)
        if waiting is not None and (waiting.start_at, waiting.end_at) == (start_at, end_at):
            line += " Takie samo zgłoszenie już czeka, więc zostanie zatwierdzone."
        elif waiting is not None:
            line += (
                f" Czekające zgłoszenie ({worktime.local_time(waiting.start_at, tz)}–"
                f"{worktime.local_time(waiting.end_at, tz)}) przestanie czekać."
            )
        change_lines[key] = line
    result.decisions = [{"change_id": d["change_id"], "approve": d["approve"]} for d in decided.values()]
    result.changes = list(changed.values())
    result.lines = [*decision_lines.values(), *change_lines.values()]
    return result


def check_plan(
    location: Location,
    sc,
    answer: llm.CommandPlan,
    text: str,
    instructions: list[ManagerInstruction],
    period: SchedulePeriod | None = None,
    today: date | None = None,
    reports: list | None = None,
) -> dict[str, Any]:
    """Turn the assistant's answer into a plan made only of things that exist in this location.

    `lines` say in plain Polish what accepting the plan will do; `notes` say what was left out and warn about
    side effects. An unusable part blocks the whole proposal, including paired removals in corrections.
    `period` is the period of the agreements (None: they wait for the next request for availability).
    `reports` are the waiting reports of other hours as numbered in the assistant's context.
    """
    from apps.rules.api import RulesIn, _clean_items, _location_preview

    if answer.topic == "unrelated":
        return _out_of_scope_plan()
    people = _people(location)
    names = {pid: label for label, pid in people.items()}
    shift_types = {s.name: str(s.pk) for s in _shift_types(location)}
    shift_names = {pid: name for name, pid in shift_types.items()}
    positions = {
        p.name: str(p.pk)
        for p in Position.objects.for_company(location.company_id).filter(location=location, removed_at__isnull=True)
    }
    lines: list[str] = []
    notes: list[str] = []
    already: list[str] = []
    rejected = False
    if any(
        len(items) > MAX_ACTIONS
        for items in (
            answer.rule_changes,
            answer.new_instructions,
            answer.remove_instructions,
            answer.hours_changes,
            answer.hours_decisions,
        )
    ):
        notes.append("Polecenie ma za dużo zmian. Podziel je na mniejsze części.")
        rejected = True
    today = today or timezone.localdate()
    periods = list(SchedulePeriod.objects.for_company(location.company_id).filter(location=location, end__gte=today))

    items = _rule_items(sc)
    by_code = {item.code: item for item in items}
    rule_changes = []
    for change in answer.rule_changes[:MAX_ACTIONS]:
        item = by_code.get(change.code)
        if item is None:
            notes.append("Pominąłem zmianę zasady, której nie ma na liście zasad.")
            rejected = True
            continue
        rule = RULES_BY_CODE[change.code]
        entry: dict[str, Any] = {"code": rule.code}
        said, same = [], []
        if change.enabled is not None:
            if change.enabled != item.enabled:
                entry["enabled"] = change.enabled
                said.append("włączę" if change.enabled else "wyłączę")
            else:
                same.append("włączona" if item.enabled else "wyłączona")
        enabled = entry.get("enabled", item.enabled)
        params = {}
        number = _number_param(rule.code)
        if (
            (change.number is not None and number is None)
            or (change.position and "position" not in rule.params)
            or (change.shift_type and "shift_type" not in rule.params)
        ):
            notes.append(f"„{rule.label}”: ta zasada nie obsługuje wszystkich podanych ustawień.")
            rejected = True
            continue
        if change.number is not None and number:
            if change.number != item.params.get(number):
                params[number] = change.number
                said.append(f"{NUMBER_PARAMS[number][2]}: {change.number}")
            else:
                same.append(f"{NUMBER_PARAMS[number][2]}: {change.number}")
        for name, given, known, what in (
            ("position", change.position, positions, "stanowisko"),
            ("shift_type", change.shift_type, shift_types, "zmiana"),
        ):
            if given and name in rule.params:
                found = readings._lookup(given, known)
                if found is None:
                    notes.append(f"„{rule.label}”: nie ma tu takiej pozycji jak „{given}” ({what}).")
                    rejected = True
                elif found != item.params.get(name):
                    params[name] = found
                    said.append(f"{what}: {given}")
                else:
                    same.append(f"{what}: {given}")
        if params:
            entry["params"] = params
        if change.no_exceptions is not None and enabled:
            if change.no_exceptions != item.is_hard:
                entry["is_hard"] = change.no_exceptions
                said.append("bez wyjątków" if change.no_exceptions else "z wyjątkami (już nie „bez wyjątków”)")
            else:
                same.append("bez wyjątków" if item.is_hard else "z wyjątkami")
        if change.place is not None and enabled:
            place = min(max(1, change.place), len(items))
            if place != items.index(item) + 1 or "enabled" in entry:
                entry["place"] = place
                said.append(f"miejsce {place} na liście zasad")
            else:
                same.append(f"miejsce {place} na liście zasad")
        if len(entry) > 1:
            rule_changes.append(entry)
            lines.append(f"Zasada „{rule.label}”: {', '.join(said)}.")
        elif same:
            already.append(f"„{rule.label}” ({', '.join(same)})")

    removed = []
    for number in dict.fromkeys(answer.remove_instructions[:MAX_ACTIONS]):
        if 1 <= number <= len(instructions):
            row = instructions[number - 1]
            removed.append(str(row.pk))
            lines.append(f"Usunę polecenie: {instruction_text(row, names, shift_names)}.")
        else:
            notes.append("Nie znalazłem polecenia, które ma zostać usunięte.")
            rejected = True
    new_instructions = []
    for new in answer.new_instructions[:MAX_ACTIONS]:
        employee = readings._lookup(new.person, people)
        if employee is None:
            notes.append(f"Nie znalazłem w tym lokalu osoby „{new.person}”.")
            rejected = True
            continue
        others = {label: pid for label, pid in people.items() if pid != employee}
        data = readings.clean(
            type=new.type,
            person=new.other_person,
            shift_type=new.shift_type,
            avoid=new.avoid_shift_type,
            max_hours=new.max_hours,
            max_shifts=new.max_shifts,
            hours_period=readings.hour_scope(
                new.hours_period, text if len(answer.new_instructions) == 1 else "", new.max_hours
            ),
            dates=new.dates,
            weekdays=new.weekdays,
            min_days=new.min_days,
            shifts_per_day=new.shifts_per_day,
            people=others,
            shift_types=shift_types,
        )
        if data is None:
            notes.append(
                f"Nie umiem zapisać całego polecenia o osobie „{new.person}”: sprawdź osobę, zmianę, godziny i dni."
            )
            rejected = True
            continue
        days = sorted(d for d in (readings._parse_date(v) for v in data["dates"]) if d is not None)
        if days and period is not None:
            # The agreements belong to one period: days outside it would change no schedule.
            outside = [d for d in days if not period.start <= d <= period.end]
            inside = [d for d in days if period.start <= d <= period.end]
            if outside and not inside and not data["weekdays"]:
                notes.append(
                    f"Polecenie o osobie „{new.person}” dotyczy dni spoza okresu ustaleń "
                    f"({_period_label(period)}): {_day_words(outside)}. Nie zmieniłoby żadnego grafiku. "
                    "Opublikowany grafik poprawisz w zakładce „Grafik” („Popraw grafik”), a ustalenia na inny "
                    "okres otworzysz w zakładce „Ustalenia”."
                )
                rejected = True
                continue
            if outside:
                data["dates"] = [d.isoformat() for d in inside]
                if data.get("min_days") is not None and inside and data["min_days"] >= len(inside):
                    data["min_days"] = None
                notes.append(
                    f"Polecenie o osobie „{new.person}”: pominąłem dni spoza okresu ustaleń "
                    f"({_period_label(period)}): {_day_words(outside)}."
                )
        elif days and not data["weekdays"]:
            if days[0] > today + timedelta(days=MAX_DAYS_AHEAD):
                notes.append(f"Pominąłem polecenie o osobie „{new.person}”: dotyczy dni ponad rok naprzód.")
                rejected = True
                continue
            if not any(p.start <= d <= p.end for p in periods for d in days):
                notes.append(
                    f"Polecenie o osobie „{new.person}” zadziała, gdy poprosisz o dyspozycje na te dni. "
                    "Do tego czasu nie zmienia żadnego grafiku."
                )
        new_instructions.append({"employee": employee, "data": data, "place": new.place})
        lines.append(f"Nowe polecenie: {readings.describe(data, names[employee], names, shift_names)}.")
        if data["type"] == "chce_pracowac":
            conflicts = list(
                AvailabilityDay.objects.for_company(location.company_id)
                .filter(
                    employee_id=employee,
                    state=AvailabilityState.CANNOT,
                    date__in=readings.dates_in(data, today, today + timedelta(days=MAX_DAYS_AHEAD)),
                )
                .order_by("date")
                .values_list("date", flat=True)[:6]
            )
            if conflicts:
                dates = ", ".join(d.isoformat() for d in conflicts)
                notes.append(f"{names[employee]} ma zapisane „nie mogę”: {dates}. Polecenie nie usuwa tej blokady.")

    hours = _checked_manager_hours(location, answer, reports or [], people)
    lines += hours.lines
    notes += hours.notes
    already += hours.already
    rejected = rejected or hours.rejected
    hours_changes, hours_decisions = hours.changes, hours.decisions

    effects: list[str] = []
    if rule_changes:
        try:
            proposed = _clean_items(sc, RulesIn(items=_changed_items(items, rule_changes)))
            effects, _ = _location_preview(sc, location, proposed, period)
        except HttpError as exc:
            notes.append(f"Tych zmian zasad nie da się zapisać: {exc.message}")
            rejected = True
            lines = [line for line in lines if not line.startswith("Zasada „")]
            rule_changes = []
    arrange = None
    arrange_note = ""
    if answer.arrange != "no" and not rejected:
        arrange, line, arrange_note = _checked_arrange(location, period, different=answer.arrange == "different")
        if arrange is None:
            notes.append(arrange_note)
            arrange_note = ""
            rejected = True
        else:
            lines.append(line)
    if answer.question and (rule_changes or new_instructions or removed or hours_changes or hours_decisions or arrange):
        rejected = True  # a clarification must not leave a partial plan available for acceptance
        notes.append("Najpierw odpowiedz na pytanie asystenta. Nie można jeszcze zatwierdzić tego planu.")
    if rejected:
        rule_changes, new_instructions, removed, lines, effects = [], [], [], [], []
        hours_changes, hours_decisions = [], []
        arrange, arrange_note = None, ""
    if new_instructions or removed:
        effects.extend(_personal_effects(sc, location, new_instructions, removed, names, shift_names, period))
    hard = sum(1 for item in _changed_items(items, rule_changes) if item.enabled and item.is_hard)
    if any(change.get("is_hard") for change in rule_changes) and hard >= 3:
        notes.append(
            f"Będziesz mieć {hard} zasady „bez wyjątków”. Im więcej takich zasad, tym częściej zostaną zmiany "
            "bez obsady, bo generator nie może ich złamać nawet wtedy, gdy brakuje ludzi."
        )
    if new_instructions and len(instructions) - len(removed) + len(new_instructions) > 1:
        notes.append(
            "Polecenia mają kolejność: to wyżej wygrywa, gdy nie da się spełnić wszystkich. "
            "Kolejność możesz zmienić na liście poleceń."
        )
    if arrange_note:
        notes.insert(0, arrange_note)
    if new_instructions:
        # First, so the assistant's own words above can never read as a promise of a shift.
        notes.insert(
            0,
            "Polecenia o osobach są preferencjami. Generator spróbuje je spełnić, ale nie gwarantują przydziału."
            + (
                " Zatwierdzenie nie zmienia dyspozycji."
                if arrange
                else " Zatwierdzenie nie zmienia dyspozycji ani gotowego grafiku i nie uruchamia układania."
            ),
        )
    if hours_changes or hours_decisions:
        notes.insert(0, HOURS_NOTE)
    if already and not rejected:
        notes.insert(0, f"To już jest ustawione: {'; '.join(already)}.")
    changes = bool(rule_changes or new_instructions or removed or hours_changes or hours_decisions or arrange)
    reply = answer.reply.strip()[:1500]
    if rejected:
        reply = BLOCKED_REPLY
    elif changes:
        reply = reply or CHANGES_REPLY
    elif not reply and not answer.question:
        reply = "Nic się nie zmieniło." if already else NO_CHANGES_REPLY
    return {
        "scope": "rules",
        "topic": answer.topic,
        "relative_append": True,
        "blocked": rejected,
        "informational": bool(answer.reply.strip()) and not (rejected or changes or answer.question),
        "reply": reply or None,
        "question": (answer.question or "").strip()[:300] or None,
        "rule_changes": rule_changes,
        "new_instructions": new_instructions,
        "remove_instructions": removed,
        "hours_changes": hours_changes,
        "hours_decisions": hours_decisions,
        "arrange": arrange,
        "lines": lines,
        "effects": effects,
        "notes": notes,
    }


def _period_label(period: SchedulePeriod) -> str:
    return f"{period.start:%d.%m}–{period.end:%d.%m.%Y}"


def _personal_effects(sc, location, additions, removed, names, shift_names, period=None) -> list[str]:
    from dataclasses import replace

    from apps.rules.api import _period_words, preview_version
    from apps.scheduling.problem_builder import build_problem_for_version, instruction_request
    from engine.validator import validate

    version = preview_version(sc, location, period)
    if version is None:
        return ["Ten lokal nie ma jeszcze grafiku do porównania."]
    built, schedule = build_problem_for_version(version)
    problem = built.problem
    start, end = problem.period_start, problem.period_end
    status = "opublikowany" if version.published_at else "szkic"
    when = f"{_period_words(start, end)} (wersja {version.number}, {status})"
    new_requests = []
    lines = []
    for i, entry in enumerate(additions):
        req = instruction_request(
            entry["data"], entry["employee"], f"preview-{i}", i + 1, start, end, names, shift_names
        )
        if (
            req is None
            or req.employee not in problem.employee_by_id
            or (req.subject_employee and req.subject_employee not in problem.employee_by_id)
        ):
            label = readings.describe(entry["data"], names[entry["employee"]], names, shift_names)
            lines.append(f"{label} — poza grafikiem {when}.")
        else:
            new_requests.append(req)
    removed_ids = {f"instruction:{pk}" for pk in removed}
    old_requests = [r for r in problem.requests if r.id in removed_ids]
    report = validate(replace(problem, requests=tuple([*old_requests, *new_requests])), schedule)
    degrees = {m.request_id: m.degree for m in report.requests}
    for req in [*old_requests, *new_requests]:
        label = "Usuwane polecenie" if req.id in removed_ids else "Nowe polecenie"
        worked = any(schedule.get(s.id) == req.employee and req.covers(s.date) for s in problem.slots)
        if not worked and req.type in ("prefer_person", "avoid_person", "shift_type"):
            outcome = "brak przydziałów tej osoby w podanych dniach"
        elif req.id in degrees:
            outcome = f"wykonanie {100 * (1 - degrees[req.id]):.0f}%"
        else:
            outcome = "brak danych do oceny"
        lines.append(f"{label} na grafiku {when}: {req.summary} — {outcome}.")
    if removed_ids - {r.id for r in old_requests}:
        lines.append(f"Usuwane polecenie nie dotyczy grafiku {when}.")
    return lines


def _changed_items(items: list, changes: list[dict[str, Any]]) -> list:
    """The rule list after the plan's changes (`items` is not modified)."""
    result = [item.model_copy(deep=True) for item in items]
    for change in changes:
        item = next((i for i in result if i.code == change["code"]), None)
        if item is None:
            continue
        was_enabled = item.enabled
        if "enabled" in change:
            item.enabled = change["enabled"]
            if not item.enabled:
                item.is_hard = False
        item.params = {**item.params, **change.get("params", {})}
        if "is_hard" in change:
            item.is_hard = bool(change["is_hard"]) and item.enabled
        if "place" in change:
            result.remove(item)
            result.insert(min(change["place"], len(result) + 1) - 1, item)
        elif item.enabled and not was_enabled:
            # Newly switched on with no place given: the least important of the rules that are on.
            result.remove(item)
            last_on = max((n for n, other in enumerate(result) if other.enabled), default=-1)
            result.insert(last_on + 1, item)
    return result


def has_changes(plan: dict[str, Any] | None) -> bool:
    return needs_rule_set(plan) or has_hours(plan) or arranges(plan)


def arranges(plan: dict[str, Any] | None) -> bool:
    """Accepting the plan arranges the schedule of the agreements' period again (docs/plan.md section 35)."""
    return bool((plan or {}).get("arrange"))


def needs_rule_set(plan: dict[str, Any] | None) -> bool:
    """The plan changes the agreements of a period (rules or instructions about people)."""
    plan = plan or {}
    return bool(plan.get("rule_changes") or plan.get("new_instructions") or plan.get("remove_instructions"))


def has_hours(plan: dict[str, Any] | None) -> bool:
    """The plan changes hours of published shifts (works after the period's schedule is published, too)."""
    plan = plan or {}
    return bool(plan.get("hours_changes") or plan.get("hours_decisions"))


def apply_command(ctx: TenantContext, command: AssistantCommand) -> None:
    """The manager accepted the plan: change the rule list, the instructions and the hours, and queue the arranging
    the plan asks for, in one transaction (when arranging cannot start, nothing is saved)."""
    with transaction.atomic():
        agreements.lock_location(command.location)
        locked = ctx.qs(AssistantCommand).select_for_update().get(pk=command.pk)
        plan = locked.plan or {}
        if locked.status != AssistantCommand.Status.READY or not has_changes(plan):
            raise HttpError(409, "Tego planu nie można już zastosować. Napisz polecenie jeszcze raz.")
        if timezone.now() >= locked.created_at + COMMAND_MAX_AGE:
            raise HttpError(409, "Propozycja wygasła po 24 godzinach. Wyślij polecenie ponownie, aby przygotować nową.")
        location = ctx.qs(Location).select_for_update().get(pk=command.location_id)
        if needs_rule_set(plan):
            _apply_agreements(ctx, command, locked, location, plan)
        _apply_hours(ctx, location, plan)
        if arranges(plan):
            locked.generation_run = _apply_arrange(ctx, locked, location, plan["arrange"])
        locked.status = AssistantCommand.Status.APPLIED
        locked.decided_at = timezone.now()
        locked.save(update_fields=["status", "decided_at", "generation_run"])
    command.status, command.decided_at = locked.status, locked.decided_at
    command.generation_run = locked.generation_run


def _apply_arrange(ctx: TenantContext, command: AssistantCommand, location: Location, entry: dict[str, Any]):
    """Queue the arranging of the plan (after its agreements, in the caller's transaction)."""
    from apps.scheduling.editing import latest_version
    from apps.scheduling.generation import request_generation

    rule_set = command.rule_set
    if rule_set is None or str(rule_set.period_id) != entry["period_id"]:
        raise HttpError(409, STALE_ARRANGE)
    agreements.require_open(rule_set)
    period = ctx.qs(SchedulePeriod).filter(pk=entry["period_id"], location=location).first()
    if period is None or latest_version(period) is None:
        raise HttpError(409, STALE_ARRANGE)
    try:
        [run] = request_generation(ctx, [period], different=bool(entry.get("different")))
    except HttpError as exc:
        raise HttpError(exc.status_code, f"{exc.message} Nic z tego planu nie zapisałem.") from exc
    return run


def _apply_agreements(
    ctx: TenantContext, command: AssistantCommand, locked: AssistantCommand, location: Location, plan: dict[str, Any]
) -> None:
    if locked.rule_set_id is None:
        raise HttpError(409, "Ten plan nie ma przypisanego zestawu zasad. Wyślij polecenie ponownie.")
    agreements.require_open(locked.rule_set)
    if locked.rule_set.rules is None:
        locked.rule_set.rules = agreements.base_items(location)
        locked.rule_set.save(update_fields=["rules"])
    removed = set(plan.get("remove_instructions") or [])
    existing = {
        str(pk)
        for pk in ctx.qs(ManagerInstruction)
        .filter(location=location, rule_set=locked.rule_set, pk__in=removed)
        .values_list("pk", flat=True)
    }
    if removed != existing:
        raise HttpError(409, "Polecenie poprawiane w tym planie już się zmieniło. Napisz polecenie jeszcze raz.")
    people = set(_people(location).values())
    shifts = {str(s.pk) for s in _shift_types(location)}
    for new in plan.get("new_instructions") or []:
        data = new["data"]
        if (
            new["employee"] not in people
            or (data.get("subject_employee") and data["subject_employee"] not in people)
            or (data.get("shift_type") and data["shift_type"] not in shifts)
        ):
            raise HttpError(409, "Osoby lub zmiany z tego planu już się zmieniły. Napisz polecenie jeszcze raz.")
    if plan.get("rule_changes"):
        sc = rules_scope(ctx, location, locked.rule_set)
        agreements.save_items(
            locked.rule_set,
            _changed_items(_rule_items(sc), plan["rule_changes"]),
            {change["code"] for change in plan["rule_changes"]},
        )
    ctx.qs(ManagerInstruction).filter(
        location=location, rule_set=locked.rule_set, pk__in=plan.get("remove_instructions") or []
    ).delete()
    rows = _instructions(location, locked.rule_set)
    for new in plan.get("new_instructions") or []:
        employee = ctx.qs(EmployeeProfile).filter(works_in_q(location), pk=new["employee"]).first()
        if employee is None:
            raise HttpError(409, "Osoba z tego planu nie pracuje już w tym lokalu. Napisz polecenie jeszcze raz.")
        row = ManagerInstruction(
            company=ctx.company,
            location=location,
            rule_set=locked.rule_set,
            employee=employee,
            data=new["data"],
            position=0,
            source_text=command.text,
            created_by=ctx.user,
        )
        place = new.get("place")
        # Pending plans from older workers expressed even "at the end" as an absolute number.
        if (
            "relative_append" not in plan
            and len(plan["new_instructions"]) == 1
            and any(word in plan.get("reply", "").lower() for word in ("na koniec", "na końcu"))
        ):
            place = None
        if place is None:
            rows.append(row)
        else:
            rows.insert(max(0, min(int(place) - 1, len(rows))), row)
    renumber(rows)


def _apply_hours(ctx: TenantContext, location: Location, plan: dict[str, Any]) -> None:
    """Decisions first, then the manager's own changes; any refusal undoes the whole plan (the caller's block)."""
    from apps.scheduling.models import Assignment, ScheduleVersion
    from apps.worktime import services as worktime
    from apps.worktime.models import HoursChange

    try:
        for decision in plan.get("hours_decisions") or []:
            change = ctx.qs(HoursChange).filter(pk=decision["change_id"], location=location).first()
            if change is None:
                raise HttpError(409, worktime.DECIDED)
            worktime.decide(change, ctx.user, approve=decision["approve"])
        for entry in plan.get("hours_changes") or []:
            # By the shift's key, so a correction published since with the same shift still finds it.
            assignment = (
                ctx.qs(Assignment)
                .filter(
                    employee_id=entry["employee"],
                    shift__location=location,
                    shift__slot_key=entry["slot_key"],
                    shift__version__period_id=entry["period_id"],
                    shift__version__status=ScheduleVersion.Status.PUBLISHED,
                )
                .first()
            )
            if assignment is None:
                raise HttpError(409, STALE_HOURS)
            worktime.set_hours(
                assignment,
                worktime.parse_time(entry["start_time"]),
                worktime.parse_time(entry["end_time"]),
                entry.get("reason") or "",
                ctx.user,
                employee_id=entry["employee"],
                seen=worktime.Seen.from_dict(entry.get("seen")),
            )
    except HttpError as exc:
        raise HttpError(409, f"{exc.message} Nic z tego planu nie zapisałem. Napisz polecenie jeszcze raz.") from exc


def renumber(rows: list[ManagerInstruction]) -> None:
    for position, row in enumerate(rows, start=1):
        if row.position != position or row._state.adding:
            row.position = position
            row.save()
