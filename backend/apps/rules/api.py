"""The rules screen: one list in order of importance, switches, "bez wyjątków", parameters, and a preview of what
a change would mean on the last schedule.

A location list shows the group's rules too. A rule whose setting is the group's says so ("z grupy"); changing it
in the location stores the location's own setting, which the generator uses instead (`apps.rules.services.merge`).
"""

from dataclasses import replace
from datetime import date
from typing import Any, Literal
from uuid import UUID

from django.db import transaction
from ninja import Field, Router, Schema
from ninja.errors import HttpError

from apps.core.schemas import ErrorOut
from apps.rules.models import RuleSetting
from apps.rules.services import (
    LOCATION_ONLY_RULES,
    NUMBER_PARAMS,
    OPTIONAL_PARAMS,
    Row,
    merge,
    rule_configs,
    same_setting,
)
from apps.scheduling.models import ScheduleVersion
from apps.scheduling.problem_builder import build_problem_for_version
from apps.staffing.models import Position, ShiftType
from apps.tenancy.context import TenantContext, context_for
from apps.tenancy.models import Location, LocationGroup
from engine.rules_catalog import RULES, RULES_BY_CODE
from engine.scoring import score
from engine.validator import validate

router = Router(tags=["rules"])

ScopeType = Literal["location", "group"]
RuleSource = Literal["group", "location", "own", "off"]


class NamedOut(Schema):
    id: UUID
    name: str


class RuleValueOut(Schema):
    enabled: bool
    is_hard: bool
    params: dict[str, Any]


class RuleItemOut(Schema):
    code: str
    label: str
    description: str
    good_practice: bool
    enabled: bool
    is_hard: bool
    params: dict[str, Any]
    # Parameter names this rule takes, in order (hours, days, shifts, count, position, shift_type).
    param_names: list[str]
    # group: the group's setting is used; location: the location changed the group's setting;
    # own: only this location has the rule; off: not set anywhere (shown switched off).
    source: RuleSource
    # The group's setting of this rule (location lists only), for "Przywróć jak w grupie".
    group_value: RuleValueOut | None
    # Rules about a location's positions or shift types cannot be set for a whole group.
    location_only: bool


class RulesOut(Schema):
    scope: ScopeType
    scope_id: UUID
    name: str
    group: NamedOut | None
    # Lists for parameters of a location's rules (empty for a group).
    positions: list[NamedOut]
    shift_types: list[NamedOut]
    items: list[RuleItemOut]


class RuleItemIn(Schema):
    code: str = Field(max_length=64)
    enabled: bool
    is_hard: bool = False
    params: dict[str, Any] = Field(default_factory=dict)


class RulesIn(Schema):
    # The whole list, most important first.
    items: list[RuleItemIn] = Field(max_length=len(RULES))


class PreviewOut(Schema):
    # Plain sentences for the manager; empty when nothing would change.
    lines: list[str]
    # The schedule the preview was checked on, e.g. "1–30 listopada" (None: no schedule yet).
    period: str | None
    manager_rules_before: float | None
    manager_rules_after: float | None


# --------------------------------------------------------------------------------------------- scope


class _Scope:
    def __init__(self, ctx: TenantContext, scope: ScopeType, obj: Location | LocationGroup) -> None:
        self.ctx, self.scope, self.obj = ctx, scope, obj

    @property
    def location(self) -> Location | None:
        return self.obj if self.scope == "location" else None

    @property
    def group(self) -> LocationGroup | None:
        if self.scope == "group":
            return self.obj
        return self.obj.group

    def own_rows(self):
        field = "location" if self.scope == "location" else "group"
        return self.ctx.qs(RuleSetting).filter(**{field: self.obj})

    def group_rows(self):
        if self.scope == "group" or self.obj.group_id is None:
            return self.ctx.qs(RuleSetting).none()
        return self.ctx.qs(RuleSetting).filter(group_id=self.obj.group_id)

    def locations(self) -> list[Location]:
        if self.scope == "location":
            return [self.obj]
        return list(self.ctx.qs(Location).filter(group=self.obj, archived_at__isnull=True).order_by("name"))


def _scope(request, scope: ScopeType, scope_id: UUID) -> _Scope:
    if scope == "location":
        ctx, location = context_for(request, Location, scope_id)
        ctx.require_manager_of(location)
        return _Scope(ctx, scope, location)
    ctx, group = context_for(request, LocationGroup, scope_id)
    locations = ctx.qs(Location).filter(group=group, archived_at__isnull=True)
    if not locations.exists():
        ctx.require_manager()
    for location in locations:
        ctx.require_manager_of(location)
    return _Scope(ctx, scope, group)


def _params_of(code: str, params: dict | None) -> dict[str, Any]:
    return {**RULES_BY_CODE[code].params, **(params or {})}


def _rules_out(sc: _Scope) -> RulesOut:
    group_rows = {row.rule_code: row for row in sc.group_rows()}
    own_rows = {row.rule_code: row for row in sc.own_rows()}
    ordered = merge(group_rows.values(), own_rows.values())
    listed = {row.rule_code for row in ordered}
    items = []
    for row in ordered + [Row(rule.code, False, False, 0) for rule in RULES if rule.code not in listed]:
        rule = RULES_BY_CODE[row.rule_code]
        group_row = group_rows.get(row.rule_code)
        if sc.scope == "group":
            source = "group" if row.rule_code in own_rows else "off"
        elif row.rule_code not in own_rows:
            source = "group" if group_row else "off"
        elif group_row is None:
            source = "own"
        else:
            source = "group" if same_setting(group_row, row) else "location"
        items.append(
            RuleItemOut(
                code=rule.code,
                label=rule.label,
                description=rule.description,
                good_practice=rule.good_practice,
                enabled=row.enabled,
                is_hard=row.is_hard,
                params=_params_of(rule.code, row.params),
                param_names=list(rule.params),
                source=source,
                group_value=RuleValueOut(
                    enabled=group_row.enabled, is_hard=group_row.is_hard, params=_params_of(rule.code, group_row.params)
                )
                if group_row is not None
                else None,
                location_only=rule.code in LOCATION_ONLY_RULES,
            )
        )
    location = sc.location
    group = sc.group
    return RulesOut(
        scope=sc.scope,
        scope_id=sc.obj.pk,
        name=sc.obj.name,
        group=NamedOut(id=group.pk, name=group.name) if location is not None and group is not None else None,
        positions=[NamedOut(id=p.pk, name=p.name) for p in sc.ctx.qs(Position).filter(location=location)]
        if location
        else [],
        shift_types=[NamedOut(id=s.pk, name=s.name) for s in sc.ctx.qs(ShiftType).filter(location=location)]
        if location
        else [],
        items=items,
    )


# --------------------------------------------------------------------------------------------- checking input


def _clean_items(sc: _Scope, payload: RulesIn) -> list[Row]:
    seen: set[str] = set()
    rows = []
    for place, item in enumerate(payload.items, start=1):
        rule = RULES_BY_CODE.get(item.code)
        if rule is None:
            raise HttpError(400, "Tej zasady nie ma na liście zasad.")
        if item.code in seen:
            raise HttpError(400, f"Zasada „{rule.label}” jest na liście dwa razy.")
        seen.add(item.code)
        params = _clean_params(sc, rule.code, item.params, item.enabled)
        if item.enabled and sc.scope == "group" and rule.code in LOCATION_ONLY_RULES:
            raise HttpError(400, f"Zasadę „{rule.label}” ustawia się w lokalu, bo dotyczy jego stanowisk i zmian.")
        rows.append(Row(rule.code, item.enabled, item.is_hard and item.enabled, place, params))
    return rows


def _clean_params(sc: _Scope, code: str, given: dict[str, Any], enabled: bool) -> dict[str, Any]:
    rule = RULES_BY_CODE[code]
    params: dict[str, Any] = {}
    for name in given:
        if name not in rule.params:
            raise HttpError(400, f"Zasada „{rule.label}” nie ma takiego ustawienia.")
    for name, default in rule.params.items():
        value = given.get(name, default)
        if name in NUMBER_PARAMS:
            low, high, what = NUMBER_PARAMS[name]
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise HttpError(400, f"„{rule.label}”: {what} musi być od {low} do {high}.")
        elif value in (None, ""):
            if enabled and (code, name) not in OPTIONAL_PARAMS:
                what = "stanowisko" if name == "position" else "zmianę"
                raise HttpError(400, f"„{rule.label}”: wybierz {what}.")
            value = None
        else:
            model = Position if name == "position" else ShiftType
            location = sc.location
            if location is None or not sc.ctx.qs(model).filter(pk=str(value), location=location).exists():
                raise HttpError(400, f"„{rule.label}”: wybierz z listy tego lokalu.")
            value = str(value)
        params[name] = value
    return params


def _stored_params(code: str, params: dict[str, Any]) -> dict[str, Any]:
    """Only values that differ from the catalog default are stored (so later default changes still apply)."""
    defaults = RULES_BY_CODE[code].params
    return {k: v for k, v in params.items() if v != defaults.get(k)}


# --------------------------------------------------------------------------------------------- endpoints


@router.get("/scopes/{scope}/{scope_id}/rules", response={200: RulesOut, 403: ErrorOut, 404: ErrorOut})
def scope_rules(request, scope: ScopeType, scope_id: UUID):
    return _rules_out(_scope(request, scope, scope_id))


@router.put(
    "/scopes/{scope}/{scope_id}/rules",
    response={200: RulesOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut},
)
def save_scope_rules(request, scope: ScopeType, scope_id: UUID, payload: RulesIn):
    """Save the whole list. In a location, a rule set exactly like in the group (also its place) keeps following
    the group; anything else becomes the location's own setting."""
    sc = _scope(request, scope, scope_id)
    sc.ctx.require_writable()
    save_rules(sc, payload)
    return _rules_out(sc)


def save_rules(sc: _Scope, payload: RulesIn) -> None:
    """Check and store the whole list of one scope (also used when the manager accepts the assistant's plan)."""
    scope = sc.scope
    rows = _clean_items(sc, payload)
    group_rows = {row.rule_code: row for row in sc.group_rows()}
    field = "location" if scope == "location" else "group"
    with transaction.atomic():
        existing = {row.rule_code: row for row in sc.own_rows().order_by("pk").select_for_update()}
        keep = set()
        for row in rows:
            group_row = group_rows.get(row.rule_code)
            stored = Row(
                row.rule_code, row.enabled, row.is_hard, row.position, _stored_params(row.rule_code, row.params)
            )
            if scope == "location":
                if group_row is not None and same_setting(group_row, stored) and group_row.position == row.position:
                    continue  # follows the group
                if group_row is None and not row.enabled:
                    continue  # nothing to remember: off, like a rule nobody set
            keep.add(row.rule_code)
            setting = existing.get(row.rule_code) or RuleSetting(
                company=sc.ctx.company, rule_code=row.rule_code, **{field: sc.obj}
            )
            setting.enabled, setting.is_hard = stored.enabled, stored.is_hard
            setting.position, setting.params = stored.position, stored.params
            setting.save()
        sc.own_rows().exclude(rule_code__in=keep).delete()


def _times(n: int) -> str:
    return "1 raz" if n == 1 else f"{n} razy"


def _period_words(start: date, end: date) -> str:
    return f"{start:%d.%m}–{end:%d.%m.%Y}"


def _location_preview(sc: _Scope, location: Location, proposed: list[Row]) -> tuple[list[str], tuple | None]:
    """Check the latest schedule of a location against its rules now and with the proposed change."""
    version = (
        sc.ctx.qs(ScheduleVersion)
        .filter(period__location=location)
        .select_related("period")
        .order_by("-period__start", "-number")
        .first()
    )
    if version is None:
        return [], None
    published = (
        sc.ctx.qs(ScheduleVersion).filter(period=version.period, status=ScheduleVersion.Status.PUBLISHED).first()
    )
    version = published or version
    built, schedule = build_problem_for_version(version)
    location_id = str(location.pk)
    # A location's screen sends its whole list (group rules included); a group's list merges with each location.
    own = sc.ctx.qs(RuleSetting).filter(location=location)
    new_rows = proposed if sc.scope == "location" else merge(proposed, own)
    before_problem = built.problem
    after_problem = replace(
        before_problem,
        rules=tuple(r for r in before_problem.rules if r.location != location_id)
        + tuple(rule_configs(location_id, new_rows)),
    )
    before = validate(before_problem, schedule)
    after = validate(after_problem, schedule)
    when = _period_words(version.period.start, version.period.end)
    lines = _differences(before, after, location_id, when)
    scores = (
        round(score(before_problem, before, location_id).manager_rules, 1),
        round(score(after_problem, after, location_id).manager_rules, 1),
    )
    return lines, (when, *scores)


def _differences(before, after, location_id: str, when: str) -> list[str]:
    old = {m.code: m for m in before.rules if m.location == location_id}
    new = {m.code: m for m in after.rules if m.location == location_id}
    lines = []
    for code in [rule.code for rule in RULES]:
        label = RULES_BY_CODE[code].label
        a, b = old.get(code), new.get(code)
        if a is None and b is None:
            continue
        if b is None:
            broken = len(a.violations)
            lines.append(f"„{label}” przestanie się liczyć (w grafiku {when} była złamana {_times(broken)}).")
            continue
        changed = a is None or a.hard != b.hard or len(a.violations) != len(b.violations)
        if not changed:
            continue
        broken = len(b.violations)
        if b.hard:
            if broken:
                lines.append(
                    f"„{label}” bez wyjątków: grafik {when} łamie ją {_times(broken)}. Przy następnym układaniu "
                    "generator musi to zmienić, nawet jeśli zostaną nieobsadzone zmiany."
                )
            else:
                lines.append(f"„{label}” bez wyjątków: grafik {when} już ją spełnia.")
        elif broken:
            lines.append(f"„{label}”: w grafiku {when} byłaby złamana {_times(broken)}.")
        else:
            lines.append(f"„{label}”: grafik {when} już ją spełnia.")
    if [m.code for m in before.rules if m.location == location_id and not m.hard] != [
        m.code for m in after.rules if m.location == location_id and not m.hard
    ] and not lines:
        lines.append("Zmieni się kolejność: zasady wyżej na liście będą ważniejsze przy układaniu grafiku.")
    return lines


@router.post(
    "/scopes/{scope}/{scope_id}/rules/preview",
    response={200: PreviewOut, 400: ErrorOut, 403: ErrorOut, 404: ErrorOut},
)
def preview_scope_rules(request, scope: ScopeType, scope_id: UUID, payload: RulesIn):
    """What the change would mean on the last schedule of each location, checked without arranging it again
    (the generator runs only in the background)."""
    sc = _scope(request, scope, scope_id)
    proposed = _clean_items(sc, payload)
    lines: list[str] = []
    found = []
    for location in sc.locations():
        location_lines, result = _location_preview(sc, location, proposed)
        if result is None:
            continue
        found.append(result)
        prefix = f"{location.name}: " if scope == "group" else ""
        lines += [prefix + line for line in location_lines]
    if not found:
        return PreviewOut(lines=[], period=None, manager_rules_before=None, manager_rules_after=None)
    if scope == "group":
        return PreviewOut(lines=lines, period=found[0][0], manager_rules_before=None, manager_rules_after=None)
    when, before, after = found[0]
    return PreviewOut(lines=lines, period=when, manager_rules_before=before, manager_rules_after=after)
