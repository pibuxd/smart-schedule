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

from apps.assistant import llm, services
from apps.assistant.models import AssistantCommand, ManagerInstruction
from apps.core.schemas import ErrorOut
from apps.staffing.models import EmployeeProfile, ShiftType
from apps.tenancy.context import TenantContext, context_for
from apps.tenancy.models import Location

router = Router(tags=["assistant"])

CommandStatusName = Literal["queued", "ready", "unavailable", "failed", "applied", "dismissed"]


class CommandIn(Schema):
    text: str = Field(min_length=1, max_length=1000)


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


class InstructionOut(Schema):
    id: UUID
    text: str
    # False when the instruction names only days that have passed (kept on the list until removed).
    active: bool


class InstructionsOut(Schema):
    # False when no API key is set: commands are not read, rules are set by hand.
    assistant_enabled: bool
    items: list[InstructionOut]


class InstructionOrderIn(Schema):
    # Every instruction of the location, most important first.
    ids: list[UUID] = Field(max_length=200)


def _command_out(command: AssistantCommand) -> AssistantCommandOut:
    plan = command.plan or {}
    return AssistantCommandOut(
        id=command.pk,
        text=command.text,
        status=command.status,
        reply=plan.get("reply"),
        question=plan.get("question"),
        lines=plan.get("lines") or [],
        effects=plan.get("effects") or [],
        notes=plan.get("notes") or [],
        can_apply=command.status == AssistantCommand.Status.READY and services.has_changes(plan),
        created_at=command.created_at,
    )


def _managed_location(request, location_id: UUID) -> tuple[TenantContext, Location]:
    ctx, location = context_for(request, Location, location_id)
    ctx.require_manager_of(location)
    return ctx, location


def _managed_command(request, command_id: UUID) -> tuple[TenantContext, AssistantCommand]:
    ctx, command = context_for(request, AssistantCommand, command_id)
    ctx.require_manager_of(command.location)
    return ctx, command


def _instructions_out(ctx: TenantContext, location: Location) -> InstructionsOut:
    people = ctx.qs(EmployeeProfile).filter(home_location=location).select_related("membership__user")
    names = {str(p.pk): p.membership.user.full_name or "Bez imienia" for p in people}
    shift_names = {str(s.pk): s.name for s in ctx.qs(ShiftType).filter(location=location)}
    today = timezone.localdate()
    rows = ctx.qs(ManagerInstruction).filter(location=location).order_by("position", "created_at")
    return InstructionsOut(
        assistant_enabled=llm.is_enabled(),
        items=[
            InstructionOut(
                id=row.pk,
                text=services.instruction_text(row, names, shift_names),
                active=not services.readings.is_over(row.data or {}, today),
            )
            for row in rows
        ],
    )


@router.post(
    "/locations/{location_id}/assistant-commands",
    response={201: AssistantCommandOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 429: ErrorOut},
)
def send_assistant_command(request, location_id: UUID, payload: CommandIn):
    """Tell the assistant in words what to change in how this location's schedule is arranged."""
    ctx, location = _managed_location(request, location_id)
    ctx.require_writable()
    return Status(201, _command_out(services.submit_command(ctx, location, payload.text)))


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
        command.status = AssistantCommand.Status.DISMISSED
        command.decided_at = timezone.now()
        command.save(update_fields=["status", "decided_at"])
    return _command_out(command)


@router.get("/locations/{location_id}/instructions", response={200: InstructionsOut, 403: ErrorOut, 404: ErrorOut})
def location_instructions(request, location_id: UUID):
    """The manager's instructions about people, most important first."""
    ctx, location = _managed_location(request, location_id)
    return _instructions_out(ctx, location)


@router.put(
    "/locations/{location_id}/instructions/order",
    response={200: InstructionsOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut},
)
def order_location_instructions(request, location_id: UUID, payload: InstructionOrderIn):
    """Change the order (importance) of the instructions; the list must name each of them once."""
    ctx, location = _managed_location(request, location_id)
    ctx.require_writable()
    with transaction.atomic():
        rows = {row.pk: row for row in ctx.qs(ManagerInstruction).filter(location=location).select_for_update()}
        if len(payload.ids) != len(rows) or set(payload.ids) != set(rows):
            raise HttpError(400, "Lista poleceń zmieniła się w międzyczasie. Odśwież stronę i spróbuj jeszcze raz.")
        services.renumber([rows[pk] for pk in payload.ids])
    return _instructions_out(ctx, location)


@router.delete("/instructions/{instruction_id}", response={204: None, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut})
def delete_instruction(request, instruction_id: UUID):
    ctx, row = context_for(request, ManagerInstruction, instruction_id)
    ctx.require_manager_of(row.location)
    ctx.require_writable()
    location = row.location
    with transaction.atomic():
        row.delete()
        services.renumber(list(ctx.qs(ManagerInstruction).filter(location=location).order_by("position")))
    return Status(204, None)
