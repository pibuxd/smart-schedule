"""Everything the assistant could not turn into settings, as CSV: to see which kinds of requests and commands
are missing from the closed lists (and to improve the prompts).

    python manage.py assistant_misses [--days 30] > misses.csv

Rows: employee requests left to the manager (assistant off, unsure, failed, or "not what I meant") and manager
commands that failed, asked a question, dropped something (notes) or proposed nothing. The text is what people
wrote, so the file is for the superadmin only.
"""

import csv
import json
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.assistant.models import AssistantCommand
from apps.availability.models import TextRequest

COLUMNS = ("created_at", "kind", "company", "location", "text", "reason", "assistant_answer")


class Command(BaseCommand):
    help = "CSV of employee requests and manager commands the assistant could not turn into settings."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30, help="How many days back (default 30).")

    def handle(self, *args, days: int, **options):
        since = timezone.now() - timedelta(days=days)
        out = csv.writer(self.stdout)
        out.writerow(COLUMNS)
        for row in misses(since):
            out.writerow(row)


def misses(since):
    rows = []
    requests = (
        TextRequest.objects.filter(created_at__gte=since, status=TextRequest.Status.NEEDS_MANAGER)  # superadmin
        .select_related("company", "period__location", "employee__home_location")
        .order_by("created_at")
    )
    for r in requests:
        reason = "employee_said_wrong" if r.employee_corrected and not r.unread_reason else r.unread_reason
        rows.append(
            (
                r.created_at.isoformat(timespec="seconds"),
                "request",
                r.company.name,
                r.location.name,
                r.text,
                reason,
                _json(r.assistant_answer),
            )
        )
    commands = (
        AssistantCommand.objects.filter(created_at__gte=since)  # superadmin: all companies
        .exclude(status=AssistantCommand.Status.QUEUED)
        .select_related("company", "location")
        .order_by("created_at")
    )
    for c in commands:
        reason = _command_reason(c)
        if reason:
            rows.append(
                (
                    c.created_at.isoformat(timespec="seconds"),
                    "command",
                    c.company.name,
                    c.location.name,
                    c.text,
                    reason,
                    _json(c.assistant_answer),
                )
            )
    return sorted(rows)


def _command_reason(command: AssistantCommand) -> str:
    if command.status == AssistantCommand.Status.UNAVAILABLE:
        return "off"
    if command.status == AssistantCommand.Status.FAILED:
        return "failed"
    plan = command.plan or {}
    if plan.get("blocked"):
        return "rejected_plan: " + " | ".join(str(n) for n in plan.get("notes", []))
    if plan.get("informational") and not plan.get("question"):
        return ""
    if plan.get("question"):
        return "question"
    if plan.get("notes"):
        return "notes: " + " | ".join(str(n) for n in plan["notes"])
    if not plan.get("lines"):
        return "no_changes"
    return ""


def _json(value) -> str:
    return "" if value is None else json.dumps(value, ensure_ascii=False)
