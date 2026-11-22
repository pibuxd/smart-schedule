"""What the assistant costs, per company, location and person (docs/plan.md section 38; superadmin only).

`record` saves one `AssistantUsage` row per message the language model read: the dollars OpenRouter reports, the
tokens, and who wrote it where. `summary` adds a month up, together with schedule arranging. Arranging runs on our
own server (CP-SAT, no API), so it has no price per use: it is counted as runs and solver minutes.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.accounts.models import User
from apps.assistant import llm
from apps.assistant.models import AssistantUsage
from apps.scheduling.models import GenerationRun
from apps.tenancy.models import Company, Location, Membership

logger = logging.getLogger(__name__)

By = Literal["company", "location", "person"]
BY_CHOICES: tuple[By, ...] = ("person", "location", "company")

NO_LOCATION = "(bez lokalu)"
NO_PERSON = "(konto usunięte)"


def record(
    usage: llm.Usage,
    *,
    kind: str,
    company_id: UUID,
    location_id: UUID | None,
    user_id: UUID | None,
    message_id: UUID,
) -> None:
    """Save what one message cost. Never raises: losing a cost row must not lose the person's answer."""
    if usage.calls == 0:
        return  # no response came back from the API, so nothing was paid for
    try:
        with transaction.atomic():
            AssistantUsage.objects.for_company(company_id).create(
                company_id=company_id,
                kind=kind,
                location_id=location_id,
                user_id=user_id,
                message_id=message_id,
                backend=usage.backend,
                model=usage.model[:120],
                providers=",".join(usage.providers)[:200],
                calls=usage.calls,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cost_usd=usage.cost,
                failed=usage.failed,
                duration_ms=round(usage.seconds * 1000),
            )
    except Exception:
        logger.exception("assistant: cost of message %s not saved", message_id)


@dataclass
class CostRow:
    """One line of a month's summary. Money in dollars; arranging as runs and solver time."""

    company: str
    location: str = ""
    person: str = ""
    role: str = ""
    employee_messages: int = 0
    employee_cost: Decimal = Decimal(0)
    manager_messages: int = 0
    manager_cost: Decimal = Decimal(0)
    failed: int = 0
    unpriced: int = 0  # messages answered by a service that gives no price (Claude)
    input_tokens: int = 0
    output_tokens: int = 0
    arrangings: int = 0
    solver_seconds: float = 0.0

    @property
    def messages(self) -> int:
        return self.employee_messages + self.manager_messages

    @property
    def cost(self) -> Decimal:
        return self.employee_cost + self.manager_cost

    @property
    def solver_minutes(self) -> float:
        return round(self.solver_seconds / 60, 1)

    def add(self, other: "CostRow") -> None:
        for name in (
            "employee_messages",
            "employee_cost",
            "manager_messages",
            "manager_cost",
            "failed",
            "unpriced",
            "input_tokens",
            "output_tokens",
            "arrangings",
            "solver_seconds",
        ):
            setattr(self, name, getattr(self, name) + getattr(other, name))


def month_range(month: date) -> tuple[datetime, datetime]:
    """The month as local time (Europe/Warsaw): from its first day to the first day of the next month."""
    year, month_no = month.year, month.month
    following = (year + 1, 1) if month_no == 12 else (year, month_no + 1)
    return timezone.make_aware(datetime(year, month_no, 1)), timezone.make_aware(datetime(*following, 1))


def summary(month: date, by: By) -> list[CostRow]:
    """A month's costs of every company (`company`), location (`location`) or person in a company (`person`)."""
    start, end = month_range(month)
    rows: dict[tuple, CostRow] = {}
    key_field = {"company": None, "location": "location_id", "person": "user_id"}[by]

    def row(company_id, second=None) -> CostRow:
        key = (company_id, second)
        if key not in rows:
            rows[key] = CostRow(company="")
        return rows[key]

    usage = (
        AssistantUsage.objects.filter(created_at__gte=start, created_at__lt=end)  # superadmin: all companies
        .values("company_id", *([key_field] if key_field else []), "kind")
        .annotate(
            n=Count("id"),
            cost=Sum("cost_usd"),
            failed_n=Count("id", filter=Q(failed=True)),
            unpriced_n=Count("id", filter=Q(cost_usd__isnull=True)),
            input_n=Sum("input_tokens"),
            output_n=Sum("output_tokens"),
        )
    )
    for item in usage:
        line = row(item["company_id"], item[key_field] if key_field else None)
        if item["kind"] == AssistantUsage.Kind.MANAGER:
            line.manager_messages += item["n"]
            line.manager_cost += item["cost"] or Decimal(0)
        else:
            line.employee_messages += item["n"]
            line.employee_cost += item["cost"] or Decimal(0)
        line.failed += item["failed_n"]
        line.unpriced += item["unpriced_n"]
        line.input_tokens += item["input_n"] or 0
        line.output_tokens += item["output_n"] or 0

    runs = (
        GenerationRun.objects.filter(  # superadmin: all companies
            created_at__gte=start, created_at__lt=end, started_at__isnull=False
        )
        .only("company", "location", "requested_by", "time_ms")
        .prefetch_related("periods")
    )
    for run in runs:
        seconds = (run.time_ms or 0) / 1000
        if by == "location":
            # A group run arranges several locations at once: each of them counts it, the time is shared.
            locations = sorted({period.location_id for period in run.periods.all()}, key=str) or [run.location_id]
            for location_id in locations:
                line = row(run.company_id, location_id)
                line.arrangings += 1
                line.solver_seconds += seconds / len(locations)
        else:
            line = row(run.company_id, run.requested_by_id if by == "person" else None)
            line.arrangings += 1
            line.solver_seconds += seconds

    _label(rows, by)
    # Company by company; inside a company the costliest first.
    return sorted(
        rows.values(),
        key=lambda line: (line.company.lower(), -line.cost, -line.messages, line.location or line.person),
    )


def _label(rows: dict[tuple, CostRow], by: By) -> None:
    company_ids = {company_id for company_id, _ in rows}
    companies = dict(Company.objects.filter(pk__in=company_ids).values_list("pk", "name"))
    seconds = {second for _, second in rows if second is not None}
    if by == "location":
        names = dict(Location.objects.filter(pk__in=seconds).values_list("pk", "name"))  # superadmin
    elif by == "person":
        names = {user.pk: str(user) for user in User.objects.filter(pk__in=seconds)}
        roles = {
            (m.company_id, m.user_id): m.get_role_display()
            for m in Membership.objects.filter(company_id__in=company_ids, user_id__in=seconds)  # superadmin
        }
    for (company_id, second), line in rows.items():
        line.company = companies.get(company_id, "?")
        if by == "location":
            line.location = names.get(second, NO_LOCATION)
        elif by == "person":
            line.person = names.get(second, NO_PERSON)
            line.role = roles.get((company_id, second), "")


def total(month: date) -> CostRow:
    """The whole month, every company (from the company lines, so a group run counts once)."""
    whole = CostRow(company="Razem")
    for line in summary(month, "company"):
        whole.add(line)
    return whole


def columns(by: By) -> list[tuple[str, str]]:
    """CSV columns of a summary: (header, CostRow attribute)."""
    first = {
        "company": [("company", "company")],
        "location": [("company", "company"), ("location", "location")],
        "person": [("company", "company"), ("person", "person"), ("role", "role")],
    }[by]
    return [
        *first,
        ("employee_messages", "employee_messages"),
        ("employee_cost_usd", "employee_cost"),
        ("manager_messages", "manager_messages"),
        ("manager_cost_usd", "manager_cost"),
        ("total_cost_usd", "cost"),
        ("failed_messages", "failed"),
        ("unpriced_messages", "unpriced"),
        ("input_tokens", "input_tokens"),
        ("output_tokens", "output_tokens"),
        ("arrangings", "arrangings"),
        ("solver_minutes", "solver_minutes"),
    ]


def csv_rows(month: date, by: By) -> list[list]:
    """Header, one line per company/location/person and a total line, ready for `csv.writer`."""
    cols = columns(by)

    def cells(line: CostRow) -> list:
        values = []
        for _, attr in cols:
            value = getattr(line, attr)
            values.append(f"{value:.6f}" if isinstance(value, Decimal) else value)
        return values

    whole = total(month)
    return [[header for header, _ in cols], *(cells(line) for line in summary(month, by)), cells(whole)]


def parse_month(text: str) -> date:
    """ "2026-11" → 1 Nov 2026. Raises ValueError for anything else."""
    year, _, month = text.strip().partition("-")
    return date(int(year), int(month), 1)
