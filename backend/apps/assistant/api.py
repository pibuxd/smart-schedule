"""The manager talks to the assistant: a command in words becomes a plan, and nothing changes until the manager
accepts it. Accepted instructions about people form an ordered list (higher = more important)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from ninja import Field, Router, Schema
from ninja.errors import HttpError
from ninja.responses import Status

from apps.assistant import agreements, llm, services
from apps.assistant.models import AssistantCommand, ManagerInstruction
from apps.core.schemas import ErrorOut
from apps.staffing.models import EmployeeProfile, ShiftType
from apps.tenancy.context import TenantContext, context_for
from apps.tenancy.models import Location

router = Router(tags=["assistant"])

CommandStatusName = Literal["queued", "ready", "unavailable", "failed", "applied", "dismissed"]


class CommandIn(Schema):
    text: str = Field(min_length=1, max_length=1000)
    period_id: UUID | None = None


class AssistantCommandOut(Schema):
    id: UUID
    text: str
    status: CommandStatusName
    # The assistant's short answer and, when it could not act, its question.
    reply: str | None
    question: str | None
    # What accepting the plan will do, what it would mean on the last schedule, and warnings.
    lines: list[str]
    effects: list[str]
    notes: list[str]
    can_apply: bool
    created_at: datetime
    expires_at: datetime
    rule_set_id: UUID | None
    period_label: str
    consumed_at: datetime | None


class InstructionOut(Schema):
    id: UUID
    text: str
    # False when the instruction names only days that have passed (kept on the list until removed).
    active: bool


class AgreedRuleOut(Schema):
    code: str
    label: str
    enabled: bool
    is_hard: bool
    details: str
    changed: bool


class InstructionsOut(Schema):
    # False when no API key is set: commands are not read, rules are set by hand.
    assistant_enabled: bool
    items: list[InstructionOut]
    rule_set_id: UUID | None
    period_id: UUID | None
    period_label: str
    period_requested: bool
    consumed_at: datetime | None
    closed: bool
    rules: list[AgreedRuleOut]


class PreviousAgreementsOut(Schema):
    # The newest earlier period with agreements; None when there is nothing to copy from.
    period_label: str | None
    rules: list[AgreedRuleOut]
    items: list[InstructionOut]


class CopyAgreementsIn(Schema):
    # Only what the manager ticked is copied; an empty choice copies nothing.
    period_id: UUID | None = None
    rule_codes: list[str] = Field(default_factory=list, max_length=100)
    instruction_ids: list[UUID] = Field(default_factory=list, max_length=200)


class InstructionOrderIn(Schema):
    # Every instruction of the location, most important first.
    ids: list[UUID] = Field(max_length=200)
    period_id: UUID | None = None


def _command_out(command: AssistantCommand) -> AssistantCommandOut:
    plan = command.plan or {}
    expires_at = command.created_at + services.COMMAND_MAX_AGE
    consumed_at = command.rule_set.consumed_at if command.rule_set_id else None
    return AssistantCommandOut(
        id=command.pk,
        text=command.text,
        status=command.status,
        reply=plan.get("reply"),
        question=plan.get("question"),
        lines=plan.get("lines") or [],
        effects=plan.get("effects") or [],
        notes=plan.get("notes") or [],
        can_apply=(
            command.status == AssistantCommand.Status.READY
            and command.rule_set_id is not None
            and services.has_changes(plan)
            and timezone.now() < expires_at
            and consumed_at is None
        ),
        created_at=command.created_at,
        expires_at=expires_at,
        rule_set_id=command.rule_set_id,
        period_label=agreements.label(command.rule_set),
        consumed_at=consumed_at,
    )


def _managed_location(request, location_id: UUID) -> tuple[TenantContext, Location]:
    ctx, location = context_for(request, Location, location_id)
    ctx.require_manager_of(location)
    return ctx, location


def _managed_command(request, command_id: UUID) -> tuple[TenantContext, AssistantCommand]:
    ctx, command = context_for(request, AssistantCommand, command_id)
    ctx.require_manager_of(command.location)
    return ctx, command


def _agreed_rules(ctx: TenantContext, location: Location, rule_set) -> list[AgreedRuleOut]:
    from apps.rules.api import _rules_out
    from apps.rules.services import NUMBER_PARAMS

    rule_data = _rules_out(agreements.scope(ctx, location, rule_set))
    positions = {str(p.id): p.name for p in rule_data.positions}
    shifts = {str(s.id): s.name for s in rule_data.shift_types}
    changed = set(rule_set.changed_codes) if rule_set else set()

    def details(item):
        return "; ".join(
            f"{NUMBER_PARAMS[key][2]}: {value}"
            if key in NUMBER_PARAMS
            else positions.get(str(value), shifts.get(str(value), str(value)))
            for key, value in item.params.items()
            if value is not None
        )

    return [
        AgreedRuleOut(
            code=i.code,
            label=i.label,
            enabled=i.enabled,
            is_hard=i.is_hard,
            details=details(i),
            changed=i.code in changed,
        )
        for i in rule_data.items
    ]


def _names(ctx: TenantContext, location: Location) -> tuple[dict[str, str], dict[str, str]]:
    people = ctx.qs(EmployeeProfile).filter(home_location=location).select_related("membership__user")
    names = {str(p.pk): p.membership.user.full_name or "Bez imienia" for p in people}
    return names, {str(s.pk): s.name for s in ctx.qs(ShiftType).filter(location=location)}


def _previous_out(ctx: TenantContext, location: Location, period_id=None) -> PreviousAgreementsOut:
    source = agreements.previous(location, period_id)
    rules, rows = agreements.copyable(location, source, agreements.current(location, period_id))
    codes = {i["code"] for i in rules}
    names, shift_names = _names(ctx, location)
    return PreviousAgreementsOut(
        period_label=agreements.label(source) if source and (rules or rows) else None,
        rules=[i for i in _agreed_rules(ctx, location, source) if i.code in codes] if codes else [],
        items=[
            InstructionOut(id=row.pk, text=services.instruction_text(row, names, shift_names), active=True)
            for row in rows
        ],
    )


def _instructions_out(ctx: TenantContext, location: Location, period_id=None) -> InstructionsOut:
    from apps.scheduling.models import SchedulePeriod

    rule_set = agreements.current(location, period_id)
    period = agreements.target_period(location, period_id)
    rules = [i for i in _agreed_rules(ctx, location, rule_set) if i.enabled or i.changed]
    names, shift_names = _names(ctx, location)
    today = timezone.localdate()
    rows = ctx.qs(ManagerInstruction).filter(location=location, rule_set=rule_set).order_by("position", "created_at")
    return InstructionsOut(
        assistant_enabled=llm.is_enabled(),
        rule_set_id=rule_set.pk if rule_set else None,
        period_id=period.pk if period else None,
        period_label=(
            f"{period.start:%d.%m.%Y}–{period.end:%d.%m.%Y}"
            if period and period.availability_requested_at
            else agreements.label(rule_set)
        ),
        consumed_at=rule_set.consumed_at if rule_set else None,
        period_requested=bool(period and period.availability_requested_at),
        closed=bool(
            (rule_set and rule_set.consumed_at) or (period and period.status == SchedulePeriod.Status.PUBLISHED)
        ),
        rules=rules,
        items=[
            InstructionOut(
                id=row.pk,
                text=services.instruction_text(row, names, shift_names),
                active=not services.readings.is_over(row.data or {}, today),
            )
            for row in rows
        ],
    )


@router.get(
    "/locations/{location_id}/assistant-commands",
    response={200: list[AssistantCommandOut], 403: ErrorOut, 404: ErrorOut},
)
def assistant_history(request, location_id: UUID):
    """The current manager's latest 50 messages in this location, oldest first."""
    ctx, location = _managed_location(request, location_id)
    rows = list(
        ctx.qs(AssistantCommand)
        .select_related("rule_set__period")
        .filter(location=location, created_by=ctx.user)
        .order_by("-created_at", "-pk")[:50]
    )
    return [_command_out(row) for row in reversed(rows)]


@router.post(
    "/locations/{location_id}/assistant-commands",
    response={
        201: AssistantCommandOut,
        400: ErrorOut,
        402: ErrorOut,
        403: ErrorOut,
        404: ErrorOut,
        409: ErrorOut,
        429: ErrorOut,
    },
)
def send_assistant_command(request, location_id: UUID, payload: CommandIn):
    """Tell the assistant in words what to change in how this location's schedule is arranged."""
    ctx, location = _managed_location(request, location_id)
    ctx.require_writable()
    return Status(201, _command_out(services.submit_command(ctx, location, payload.text, payload.period_id)))


@router.get("/assistant-commands/{command_id}", response={200: AssistantCommandOut, 403: ErrorOut, 404: ErrorOut})
def assistant_command(request, command_id: UUID):
    """Poll this until the status is no longer "queued"."""
    _, command = _managed_command(request, command_id)
    return _command_out(command)


@router.post(
    "/assistant-commands/{command_id}/apply",
    response={200: AssistantCommandOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def apply_assistant_command(request, command_id: UUID):
    """Accept the plan: the rule list and the instructions change as the plan's lines say."""
    ctx, command = _managed_command(request, command_id)
    ctx.require_writable()
    services.apply_command(ctx, command)
    return _command_out(command)


@router.post(
    "/assistant-commands/{command_id}/dismiss",
    response={200: AssistantCommandOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut},
)
def dismiss_assistant_command(request, command_id: UUID):
    """Throw the plan away; nothing changes."""
    ctx, command = _managed_command(request, command_id)
    ctx.require_writable()
    if command.status in (AssistantCommand.Status.READY, AssistantCommand.Status.QUEUED):
        ctx.qs(AssistantCommand).filter(
            pk=command.pk, status__in=[AssistantCommand.Status.READY, AssistantCommand.Status.QUEUED]
        ).update(status=AssistantCommand.Status.DISMISSED, decided_at=timezone.now())
        command.refresh_from_db()
    return _command_out(command)


@router.get("/locations/{location_id}/instructions", response={200: InstructionsOut, 403: ErrorOut, 404: ErrorOut})
def location_instructions(request, location_id: UUID, period_id: UUID | None = None):
    """The manager's instructions about people, most important first."""
    ctx, location = _managed_location(request, location_id)
    return _instructions_out(ctx, location, period_id)


@router.delete(
    "/locations/{location_id}/agreed-rules/{code}",
    response={200: InstructionsOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def revert_agreed_rule(request, location_id: UUID, code: str, period_id: UUID | None = None):
    """Undo one rule agreed in the chat: the period uses the location's own setting for it again."""
    ctx, location = _managed_location(request, location_id)
    ctx.require_writable()
    with transaction.atomic():
        agreements.lock_location(location)
        rule_set = agreements.current(location, period_id)
        if rule_set is None or code not in rule_set.changed_codes:
            raise HttpError(404, "Tej zasady nie ma wśród ustaleń tego okresu.")
        agreements.require_open(rule_set)
        agreements.revert_rule(rule_set, code)
    return _instructions_out(ctx, location, period_id)


@router.get(
    "/locations/{location_id}/agreements/previous",
    response={200: PreviousAgreementsOut, 403: ErrorOut, 404: ErrorOut},
)
def previous_agreements(request, location_id: UUID, period_id: UUID | None = None):
    """What the manager may copy from the previous period into this one. Nothing is copied by itself."""
    ctx, location = _managed_location(request, location_id)
    return _previous_out(ctx, location, period_id)


@router.post(
    "/locations/{location_id}/agreements/copy",
    response={200: InstructionsOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def copy_previous_agreements(request, location_id: UUID, payload: CopyAgreementsIn):
    """Copy the ticked agreements of the previous period into this one (or into the waiting list)."""
    ctx, location = _managed_location(request, location_id)
    ctx.require_writable()
    if payload.rule_codes or payload.instruction_ids:
        with transaction.atomic():
            agreements.lock_location(location)
            agreements.copy_from_previous(
                location, payload.period_id, payload.rule_codes, payload.instruction_ids, ctx.user
            )
    return _instructions_out(ctx, location, payload.period_id)


@router.put(
    "/locations/{location_id}/instructions/order",
    response={200: InstructionsOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def order_location_instructions(request, location_id: UUID, payload: InstructionOrderIn):
    """Change the order (importance) of the instructions; the list must name each of them once."""
    ctx, location = _managed_location(request, location_id)
    ctx.require_writable()
    with transaction.atomic():
        agreements.lock_location(location)
        rule_set = agreements.current(location, payload.period_id)
        if rule_set:
            agreements.require_open(rule_set)
        rows = {
            row.pk: row
            for row in ctx.qs(ManagerInstruction).filter(location=location, rule_set=rule_set).select_for_update()
        }
        if len(payload.ids) != len(rows) or set(payload.ids) != set(rows):
            raise HttpError(400, "Lista poleceń zmieniła się w międzyczasie. Odśwież stronę i spróbuj jeszcze raz.")
        services.renumber([rows[pk] for pk in payload.ids])
    return _instructions_out(ctx, location, payload.period_id)


@router.delete(
    "/instructions/{instruction_id}", response={204: None, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut}
)
def delete_instruction(request, instruction_id: UUID):
    ctx, row = context_for(request, ManagerInstruction, instruction_id)
    ctx.require_manager_of(row.location)
    ctx.require_writable()
    location = row.location
    with transaction.atomic():
        agreements.lock_location(location)
        row = ctx.get(ManagerInstruction, pk=row.pk)
        if row.rule_set_id:
            agreements.require_open(row.rule_set)
        rule_set = row.rule_set
        row.delete()
        services.renumber(
            list(ctx.qs(ManagerInstruction).filter(location=location, rule_set=rule_set).order_by("position"))
        )
    return Status(204, None)
