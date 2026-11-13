"""What happens around a call to the assistant: what is sent, how the answer is checked, what is saved.

Employee requests: `queue_request` (API, same transaction as saving the request) and `interpret_request`
(worker). Manager commands: `submit_command` (API), `run_command` (worker) and `apply_command` (API, after the
manager accepts the plan). The assistant's answer is only a proposal; every name and number in it is checked
against the location's own data, and the sentences the manager sees are built here, not by the model.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from ninja.errors import HttpError

from apps.assistant import llm, readings
from apps.assistant.models import AssistantCommand, ManagerInstruction
from apps.availability.models import TextRequest
from apps.rules.services import NUMBER_PARAMS
from apps.scheduling.models import SchedulePeriod
from apps.staffing.models import EmployeeProfile, Position, ShiftType
from apps.tenancy.context import TenantContext
from apps.tenancy.models import Location
from engine.rules_catalog import RULES_BY_CODE

logger = logging.getLogger(__name__)

WEEKDAY_NAMES = ("poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela")
MAX_ACTIONS = 12  # changes one command may propose


# --------------------------------------------------------------------------------------------- what is sent


def _people(location: Location, exclude_id=None) -> dict[str, str]:
    """label -> employee id for the active people of a location (first names; see `readings.labels`)."""
    profiles = (
        EmployeeProfile.objects.for_company(location.company_id)
        .filter(home_location=location, is_active=True)
        .select_related("membership__user")
    )
    return readings.labels(
        (str(p.pk), p.membership.user.first_name, p.membership.user.last_name) for p in profiles if p.pk != exclude_id
    )


def _shift_types(location: Location) -> list[ShiftType]:
    return list(ShiftType.objects.for_company(location.company_id).filter(location=location).order_by("start_time"))


def _shift_lines(shift_types: list[ShiftType]) -> str:
    return ", ".join(f"{s.name} ({s.start_time:%H:%M}–{s.end_time:%H:%M})" for s in shift_types) or "(brak)"


def _today_line(today: date) -> str:
    return f"Dzisiaj: {today.isoformat()} ({WEEKDAY_NAMES[today.weekday()]})."


def request_context(text_request: TextRequest, today: date) -> tuple[str, dict[str, str], dict[str, str]]:
    period = text_request.period
    location = period.location
    people = _people(location, exclude_id=text_request.employee_id)
    shift_types = _shift_types(location)
    context = "\n".join(
        [
            _today_line(today),
            f"Okres grafiku: od {period.start.isoformat()} do {period.end.isoformat()}.",
            f"Współpracownicy: {', '.join(people) or '(brak)'}.",
            f"Zmiany: {_shift_lines(shift_types)}.",
        ]
    )
    return context, people, {s.name: str(s.pk) for s in shift_types}


# --------------------------------------------------------------------------------------------- employee requests


def queue_request(text_request: TextRequest) -> None:
    """Call inside the transaction that saves the request. Without a key the manager reads it as written."""
    if not llm.is_enabled():
        text_request.status = TextRequest.Status.NEEDS_MANAGER
        text_request.interpretation = None
        text_request.save(update_fields=["status", "interpretation", "updated_at"])
        return
    from apps.assistant.tasks import interpret_text_request  # tasks import this module

    interpret_text_request.defer(request_id=str(text_request.pk), text=text_request.text)


def interpret_request(request_id: str, text: str | None = None, today: date | None = None) -> str:
    """Worker: read one request and save how it was understood. Returns the new status (or "skipped")."""
    row = TextRequest.objects.select_related("period__location").filter(pk=request_id).first()  # worker: by id
    if row is None or row.status != TextRequest.Status.NEW or (text is not None and row.text != text):
        return "skipped"  # deleted, already read, or edited since (the newer job reads it)
    today = today or timezone.localdate()
    status, interpretation = TextRequest.Status.NEEDS_MANAGER, None
    if llm.is_enabled():
        context, people, shift_types = request_context(row, today)
        try:
            reading = llm.read_request(row.text, context)
        except llm.AssistantError as exc:
            logger.warning("request %s left to the manager: %s", row.pk, exc)
        else:
            status, interpretation = _checked_request(reading, row.period, people, shift_types)
    updated = TextRequest.objects.for_company(row.company_id).filter(
        pk=row.pk, status=TextRequest.Status.NEW, text=row.text
    )
    updated.update(status=status, interpretation=interpretation, updated_at=timezone.now())
    return status


def _checked_request(
    reading: llm.RequestReading, period: SchedulePeriod, people: dict[str, str], shift_types: dict[str, str]
) -> tuple[str, dict[str, Any] | None]:
    confidence = min(1.0, max(0.0, float(reading.confidence)))
    data = readings.clean(
        type=reading.type,
        person=reading.person,
        shift_type=reading.shift_type,
        avoid=reading.avoid_shift_type,
        max_hours=reading.max_hours,
        dates=[d for d in reading.dates if period.start.isoformat() <= d <= period.end.isoformat()],
        weekdays=reading.weekdays,
        people=people,
        shift_types=shift_types,
    )
    if reading.dates and data is not None and not data["dates"] and not data["weekdays"]:
        data = None  # only days outside this period
    summary = reading.summary.strip()[:300]
    if data is None or confidence < settings.ASSISTANT_MIN_CONFIDENCE or not summary:
        # Not sure enough: the manager reads the request as written, with no interpretation.
        return TextRequest.Status.NEEDS_MANAGER, None
    data.update(level=reading.level, confidence=round(confidence, 2), summary=summary)
    return TextRequest.Status.INTERPRETED, data


# --------------------------------------------------------------------------------------------- manager commands


def _month_start():
    return timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def submit_command(ctx: TenantContext, location: Location, text: str) -> AssistantCommand:
    """Save the command and defer the assistant's job in one transaction (or mark it "assistant is off")."""
    text = text.strip()
    if not text:
        raise HttpError(400, "Napisz, co ma się zmienić.")
    used = ctx.qs(AssistantCommand).filter(created_at__gte=_month_start()).count()
    if used >= settings.ASSISTANT_COMMANDS_MONTHLY_LIMIT:
        raise HttpError(429, "Wykorzystano miesięczny limit poleceń dla asystenta. Zasady możesz zmienić ręcznie.")
    with transaction.atomic():
        command = AssistantCommand.objects.for_company(ctx.company).create(
            company=ctx.company, location=location, text=text, created_by=ctx.user
        )
        if llm.is_enabled():
            from apps.assistant.tasks import plan_assistant_command  # tasks import this module

            plan_assistant_command.defer(command_id=str(command.pk))
        else:
            command.status = AssistantCommand.Status.UNAVAILABLE
            command.save(update_fields=["status"])
    return command


def rules_scope(ctx: TenantContext, location: Location):
    from apps.rules.api import _Scope

    return _Scope(ctx, "location", location)


def _rule_items(sc) -> list:
    from apps.rules.api import RuleItemIn, _rules_out

    return [
        RuleItemIn(code=i.code, enabled=i.enabled, is_hard=i.is_hard, params=i.params) for i in _rules_out(sc).items
    ]


def _instructions(location: Location) -> list[ManagerInstruction]:
    rows = ManagerInstruction.objects.for_company(location.company_id).filter(location=location)
    return list(rows.select_related("employee__membership__user").order_by("position", "created_at"))


def instruction_text(row: ManagerInstruction, names: dict[str, str], shift_names: dict[str, str]) -> str:
    return readings.describe(row.data or {}, names.get(str(row.employee_id), "Osoba spoza lokalu"), names, shift_names)


def command_context(location: Location, sc, today: date) -> str:
    people = _people(location)
    names = {pid: label for label, pid in people.items()}
    shift_types = _shift_types(location)
    shift_names = {str(s.pk): s.name for s in shift_types}
    positions = Position.objects.for_company(location.company_id).filter(location=location).order_by("name")
    position_names = {str(p.pk): p.name for p in positions}
    period = (
        SchedulePeriod.objects.for_company(location.company_id)
        .filter(location=location, end__gte=today)
        .order_by("start")
        .first()
    )
    lines = [
        _today_line(today),
        f"Okres grafiku: od {period.start.isoformat()} do {period.end.isoformat()}." if period else "Okres: brak.",
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
    instructions = _instructions(location)
    for number, row in enumerate(instructions, start=1):
        lines.append(f"{number}. {instruction_text(row, names, shift_names)}")
    if not instructions:
        lines.append("(brak)")
    return "\n".join(lines)


def run_command(command_id: str, today: date | None = None) -> str:
    """Worker: ask the assistant, check its plan and save it for the manager to accept. Safe to run twice."""
    command = AssistantCommand.objects.select_related("location", "company").filter(pk=command_id).first()  # by id
    if command is None or command.status != AssistantCommand.Status.QUEUED:
        return "skipped"
    today = today or timezone.localdate()
    sc = rules_scope(_SystemContext(command.company), command.location)
    status, plan = AssistantCommand.Status.FAILED, None
    try:
        answer = llm.plan_command(command.text, command_context(command.location, sc, today))
    except llm.AssistantError as exc:
        logger.warning("assistant command %s failed: %s", command.pk, exc)
    else:
        status, plan = AssistantCommand.Status.READY, check_plan(command.location, sc, answer)
    AssistantCommand.objects.for_company(command.company_id).filter(
        pk=command.pk, status=AssistantCommand.Status.QUEUED
    ).update(status=status, plan=plan)
    return status


class _SystemContext:
    """Enough of a tenant context for reading one company's rules in the worker (no user, no permissions)."""

    def __init__(self, company) -> None:
        self.company = company

    def qs(self, model):
        return model.objects.for_company(self.company)


def _number_param(code: str) -> str | None:
    return next((name for name in RULES_BY_CODE[code].params if name in NUMBER_PARAMS), None)


def check_plan(location: Location, sc, answer: llm.CommandPlan) -> dict[str, Any]:
    """Turn the assistant's answer into a plan made only of things that exist in this location.

    `lines` say in plain Polish what accepting the plan will do; `notes` say what was left out and warn about
    side effects. Anything unknown is dropped with a note, never guessed.
    """
    from apps.rules.api import RulesIn, _clean_items, _location_preview

    people = _people(location)
    names = {pid: label for label, pid in people.items()}
    shift_types = {s.name: str(s.pk) for s in _shift_types(location)}
    shift_names = {pid: name for name, pid in shift_types.items()}
    positions = {p.name: str(p.pk) for p in Position.objects.for_company(location.company_id).filter(location=location)}
    lines: list[str] = []
    notes: list[str] = []

    items = _rule_items(sc)
    by_code = {item.code: item for item in items}
    rule_changes = []
    for change in answer.rule_changes[:MAX_ACTIONS]:
        item = by_code.get(change.code)
        if item is None:
            notes.append("Pominąłem zmianę zasady, której nie ma na liście zasad.")
            continue
        rule = RULES_BY_CODE[change.code]
        entry: dict[str, Any] = {"code": rule.code}
        said = []
        if change.enabled is not None and change.enabled != item.enabled:
            entry["enabled"] = change.enabled
            said.append("włączę" if change.enabled else "wyłączę")
        enabled = entry.get("enabled", item.enabled)
        params = {}
        number = _number_param(rule.code)
        if change.number is not None and number and change.number != item.params.get(number):
            params[number] = change.number
            said.append(f"{NUMBER_PARAMS[number][2]}: {change.number}")
        for name, given, known, what in (
            ("position", change.position, positions, "stanowisko"),
            ("shift_type", change.shift_type, shift_types, "zmiana"),
        ):
            if given and name in rule.params:
                found = readings._lookup(given, known)
                if found is None:
                    notes.append(f"„{rule.label}”: nie ma tu takiej pozycji jak „{given}” ({what}).")
                elif found != item.params.get(name):
                    params[name] = found
                    said.append(f"{what}: {given}")
        if params:
            entry["params"] = params
        if change.no_exceptions is not None and enabled and change.no_exceptions != item.is_hard:
            entry["is_hard"] = change.no_exceptions
            said.append("bez wyjątków" if change.no_exceptions else "z wyjątkami (już nie „bez wyjątków”)")
        if change.place is not None and enabled:
            place = min(max(1, change.place), len(items))
            if place != items.index(item) + 1 or "enabled" in entry:
                entry["place"] = place
                said.append(f"miejsce {place} na liście zasad")
        if len(entry) > 1:
            rule_changes.append(entry)
            lines.append(f"Zasada „{rule.label}”: {', '.join(said)}.")

    instructions = _instructions(location)
    removed = []
    for number in dict.fromkeys(answer.remove_instructions[:MAX_ACTIONS]):
        if 1 <= number <= len(instructions):
            row = instructions[number - 1]
            removed.append(str(row.pk))
            lines.append(f"Usunę polecenie: {instruction_text(row, names, shift_names)}.")
    new_instructions = []
    for new in answer.new_instructions[:MAX_ACTIONS]:
        employee = readings._lookup(new.person, people)
        if employee is None:
            notes.append(f"Nie znalazłem w tym lokalu osoby „{new.person}”.")
            continue
        others = {label: pid for label, pid in people.items() if pid != employee}
        data = readings.clean(
            type=new.type,
            person=new.other_person,
            shift_type=new.shift_type,
            avoid=new.avoid_shift_type,
            max_hours=new.max_hours,
            dates=new.dates,
            weekdays=new.weekdays,
            people=others,
            shift_types=shift_types,
        )
        if data is None:
            notes.append(f"Nie umiem zapisać polecenia o osobie „{new.person}”: brakuje osoby, zmiany, godzin lub dni.")
            continue
        place = max(1, new.place)
        new_instructions.append({"employee": employee, "data": data, "place": place})
        lines.append(f"Nowe polecenie: {readings.describe(data, names[employee], names, shift_names)}.")

    effects: list[str] = []
    if rule_changes:
        try:
            proposed = _clean_items(sc, RulesIn(items=_changed_items(items, rule_changes)))
            effects, _ = _location_preview(sc, location, proposed)
        except HttpError as exc:
            notes.append(f"Tych zmian zasad nie da się zapisać: {exc.message}")
            lines = [line for line in lines if not line.startswith("Zasada „")]
            rule_changes = []
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
    return {
        "reply": answer.reply.strip()[:600],
        "question": (answer.question or "").strip()[:300] or None,
        "rule_changes": rule_changes,
        "new_instructions": new_instructions,
        "remove_instructions": removed,
        "lines": lines,
        "effects": effects[:8],
        "notes": notes,
    }


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
    plan = plan or {}
    return bool(plan.get("rule_changes") or plan.get("new_instructions") or plan.get("remove_instructions"))


def apply_command(ctx: TenantContext, command: AssistantCommand) -> None:
    """The manager accepted the plan: change the rule list and the instructions in one transaction."""
    from apps.rules.api import RulesIn, save_rules

    plan = command.plan or {}
    with transaction.atomic():
        locked = ctx.qs(AssistantCommand).select_for_update().get(pk=command.pk)
        if locked.status != AssistantCommand.Status.READY or not has_changes(plan):
            raise HttpError(409, "Tego planu nie można już zastosować. Napisz polecenie jeszcze raz.")
        location = command.location
        if plan.get("rule_changes"):
            sc = rules_scope(ctx, location)
            save_rules(sc, RulesIn(items=_changed_items(_rule_items(sc), plan["rule_changes"])))
        ctx.qs(ManagerInstruction).filter(location=location, pk__in=plan.get("remove_instructions") or []).delete()
        rows = _instructions(location)
        for new in plan.get("new_instructions") or []:
            employee = ctx.qs(EmployeeProfile).filter(pk=new["employee"], home_location=location).first()
            if employee is None:
                raise HttpError(409, "Osoba z tego planu nie pracuje już w tym lokalu. Napisz polecenie jeszcze raz.")
            row = ManagerInstruction(
                company=ctx.company,
                location=location,
                employee=employee,
                data=new["data"],
                position=0,
                source_text=command.text,
                created_by=ctx.user,
            )
            rows.insert(min(int(new.get("place") or len(rows) + 1), len(rows) + 1) - 1, row)
        renumber(rows)
        locked.status = AssistantCommand.Status.APPLIED
        locked.decided_at = timezone.now()
        locked.save(update_fields=["status", "decided_at"])
    command.status, command.decided_at = locked.status, locked.decided_at


def renumber(rows: list[ManagerInstruction]) -> None:
    for position, row in enumerate(rows, start=1):
        if row.position != position or row._state.adding:
            row.position = position
            row.save()
