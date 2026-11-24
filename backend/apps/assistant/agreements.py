"""Period-scoped assistant settings and their availability/publication lifecycle."""

from django.utils import timezone
from ninja.errors import HttpError

from apps.assistant.models import AssistantCommand, AssistantRuleSet, ManagerInstruction
from apps.rules.services import Row, merge
from apps.scheduling.models import SchedulePeriod
from apps.staffing.models import Position
from apps.tenancy.models import Company, Location
from engine.rules_catalog import RULES_BY_CODE


class ReadContext:
    def __init__(self, company):
        self.company = company

    def qs(self, model):
        return model.objects.for_company(self.company)


def lock_location(location):
    # Same order as generation/publication; callers must already be inside atomic().
    Company.objects.select_for_update().get(pk=location.company_id)
    Location.objects.for_company(location.company_id).select_for_update().get(pk=location.pk)


def target_period(location, period_id=None):
    rows = SchedulePeriod.objects.for_company(location.company_id).filter(location=location)
    if period_id is not None:
        period = rows.filter(pk=period_id).first()
        if period is None:
            raise HttpError(404, "Nie znaleziono okresu tego lokalu.")
        return period
    return (
        rows.filter(availability_requested_at__isnull=False, end__gte=timezone.localdate())
        .exclude(status=SchedulePeriod.Status.PUBLISHED)
        .exclude(assistantruleset__consumed_at__isnull=False)
        .order_by("-availability_requested_at", "-start", "-pk")
        .first()
    )


def current(location, period_id=None):
    period = target_period(location, period_id)
    if period and period.availability_requested_at is None:
        period = None
    return AssistantRuleSet.objects.for_company(location.company_id).filter(location=location, period=period).first()


def label(rule_set):
    if rule_set is None or rule_set.period_id is None:
        return "Czekają na prośbę o dyspozycje"
    period = rule_set.period
    return f"{period.start:%d.%m.%Y}–{period.end:%d.%m.%Y}"


def base_items(location):
    from apps.rules.api import _rules_out, _Scope

    data = _rules_out(_Scope(ReadContext(location.company), "location", location))
    return [{"code": i.code, "enabled": i.enabled, "is_hard": i.is_hard, "params": i.params} for i in data.items]


def rule_rows(rule_set):
    if rule_set is None or rule_set.rules is None:
        return None
    return [Row(i["code"], i["enabled"], i["is_hard"], n, i["params"]) for n, i in enumerate(rule_set.rules, 1)]


def scope(ctx, location, rule_set):
    from apps.rules.api import _Scope

    class AgreementScope(_Scope):
        def own_rows(self):
            return rule_rows(rule_set) if rule_set.rules is not None else super().own_rows()

        def group_rows(self):
            return [] if rule_set.rules is not None else super().group_rows()

    return AgreementScope(ctx, "location", location) if rule_set is not None else _Scope(ctx, "location", location)


def require_open(rule_set):
    if rule_set.consumed_at is not None or (
        rule_set.period_id and rule_set.period.status == SchedulePeriod.Status.PUBLISHED
    ):
        raise HttpError(409, "Te ustalenia wykorzystano w opublikowanym grafiku. Ustal zasady na nowy okres.")


def for_command(location, period_id=None):
    """Caller holds the company and location locks. Reads never create a set."""
    period = target_period(location, period_id)
    if period and period.availability_requested_at is None:
        if period.status == SchedulePeriod.Status.PUBLISHED:
            raise HttpError(409, "Ten okres jest już opublikowany. Ustal zasady na nowy okres.")
        period = None
    rule_set, _ = AssistantRuleSet.objects.for_company(location.company_id).get_or_create(
        location=location, period=period, defaults={"company_id": location.company_id}
    )
    require_open(rule_set)
    return rule_set


def save_items(rule_set, items, changed_codes):
    from apps.rules.api import RulesIn, _clean_items

    rows = _clean_items(scope(ReadContext(rule_set.company), rule_set.location, rule_set), RulesIn(items=items))
    rule_set.rules = [
        {"code": r.rule_code, "enabled": r.enabled, "is_hard": r.is_hard, "params": r.params} for r in rows
    ]
    rule_set.changed_codes = sorted(set(rule_set.changed_codes) | set(changed_codes))
    rule_set.save(update_fields=["rules", "changed_codes"])


def revert_rule(rule_set, code):
    """Put one rule agreed in the chat back to the location's own setting. Caller holds the location lock."""
    default = next((i for i in base_items(rule_set.location) if i["code"] == code), None)
    rules = [default if i["code"] == code else i for i in rule_set.rules or []]
    rule_set.rules = [i for i in rules if i is not None]
    rule_set.changed_codes = sorted(set(rule_set.changed_codes) - {code})
    rule_set.save(update_fields=["rules", "changed_codes"])


def merge_rules(target, source, codes):
    """Put the chosen settings of `source` into `target`, on top of the target's (or the location's) list."""
    baseline = rule_rows(target)
    if baseline is None:
        baseline = [
            Row(i["code"], i["enabled"], i["is_hard"], n, i["params"])
            for n, i in enumerate(base_items(target.location), 1)
        ]
    combined = merge(baseline, [r for r in rule_rows(source) or [] if r.rule_code in codes])
    target.rules = [
        {"code": r.rule_code, "enabled": r.enabled, "is_hard": r.is_hard, "params": r.params} for r in combined
    ]
    target.changed_codes = sorted(set(target.changed_codes) | set(codes))
    target.save(update_fields=["rules", "changed_codes"])


def previous(location, period_id=None):
    """The newest earlier period's set that holds any agreement: the only source the manager can copy from."""
    period = target_period(location, period_id)
    rows = AssistantRuleSet.objects.for_company(location.company_id).filter(location=location, period__isnull=False)
    if period is not None:
        rows = rows.filter(period__start__lt=period.start)
    for rule_set in rows.select_related("period").order_by("-period__start", "-pk")[:12]:
        if rule_set.changed_codes or rule_set.instructions.exists():
            return rule_set
    return None


def copyable(location, source, target):
    """(rule settings, instructions) of `source` that still fit the location and are not in `target` yet."""
    if source is None:
        return [], []
    from apps.assistant import readings
    from apps.staffing.models import EmployeeProfile, ShiftType, works_in_q

    mine = {i["code"]: i for i in (target.rules or [])} if target else {}
    changed = set(target.changed_codes) if target else set()
    rules = [
        i
        for i in source.rules or []
        if i["code"] in source.changed_codes
        and i["code"] in RULES_BY_CODE
        and not (i["code"] in changed and mine.get(i["code"]) == i)
    ]
    people = {
        str(pk)
        for pk in EmployeeProfile.objects.for_company(location.company_id)
        .filter(works_in_q(location), is_active=True)
        .values_list("pk", flat=True)
    }
    shifts = {
        str(pk)
        for pk in ShiftType.objects.for_company(location.company_id)
        .filter(location=location)
        .values_list("pk", flat=True)
    }
    have = (
        {
            (row.employee_id, repr(row.data))
            for row in ManagerInstruction.objects.for_company(location.company_id).filter(rule_set=target)
        }
        if target
        else set()
    )
    today = timezone.localdate()
    instructions = [
        row
        for row in ManagerInstruction.objects.for_company(location.company_id)
        .filter(rule_set=source)
        .order_by("position", "created_at")
        if str(row.employee_id) in people
        and not readings.is_over(row.data or {}, today)
        and (not (row.data or {}).get("subject_employee") or str(row.data["subject_employee"]) in people)
        and (not (row.data or {}).get("shift_type") or str(row.data["shift_type"]) in shifts)
        and positions_held(location, row.employee_id, row.data or {})
        and (row.employee_id, repr(row.data)) not in have
    ]
    return rules, instructions


def positions_held(location, employee_id, data: dict) -> bool:
    """A position instruction still makes sense: the person still holds that live position in the location."""
    wanted = {str(pk) for pk in data.get("positions") or []}
    if data.get("type") != "stanowisko":
        return True
    held = (
        Position.objects.for_company(location.company_id)
        .filter(location=location, removed_at__isnull=True, employees__pk=employee_id, pk__in=wanted)
        .exists()
    )
    return bool(wanted) and held


def copy_from_previous(location, period_id, rule_codes, instruction_ids, user):
    """Caller holds the company and location locks. Copies only what the manager ticked; nothing by default."""
    source = previous(location, period_id)
    target = for_command(location, period_id)
    rules, instructions = copyable(location, source, target)
    codes, ids = set(rule_codes), set(instruction_ids)
    chosen = [row for row in instructions if row.pk in ids]
    if not codes <= {i["code"] for i in rules} or len(chosen) != len(ids):
        raise HttpError(409, "Lista ustaleń zmieniła się w międzyczasie. Odśwież stronę i wybierz jeszcze raz.")
    if codes:
        merge_rules(target, source, codes)
    last = ManagerInstruction.objects.for_company(location.company_id).filter(rule_set=target).count()
    for n, row in enumerate(chosen, last + 1):
        ManagerInstruction.objects.for_company(location.company_id).create(
            company_id=location.company_id,
            location=location,
            rule_set=target,
            employee=row.employee,
            data=row.data,
            position=n,
            source_text=row.source_text,
            created_by=user,
        )
    return target


def bind_pending(period):
    """Adopt once when availability is requested. Never move another period's agreements."""
    rows = AssistantRuleSet.objects.for_company(period.company_id)
    pending = rows.filter(location=period.location, period__isnull=True).first()
    if pending is None:
        return
    target = rows.filter(period=period).first()
    if target is None:
        pending.period = period
        pending.save(update_fields=["period"])
        return
    require_open(target)
    if pending.rules is not None:
        merge_rules(target, pending, pending.changed_codes)
    instructions = list(
        ManagerInstruction.objects.for_company(period.company_id)
        .filter(rule_set=target)
        .order_by("position", "created_at")
    )
    incoming = list(
        ManagerInstruction.objects.for_company(period.company_id)
        .filter(rule_set=pending)
        .order_by("position", "created_at")
    )
    for n, instruction in enumerate(incoming, len(instructions) + 1):
        instruction.rule_set, instruction.position = target, n
        instruction.save(update_fields=["rule_set", "position"])
    AssistantCommand.objects.for_company(period.company_id).filter(rule_set=pending).update(rule_set=target)
    pending.delete()


def consume(period, when):
    # Publication holds the company and period locks, so no acceptance can race this update.
    AssistantRuleSet.objects.for_company(period.company_id).filter(period=period, consumed_at__isnull=True).update(
        consumed_at=when
    )
