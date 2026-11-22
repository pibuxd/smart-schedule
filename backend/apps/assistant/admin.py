import csv

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import path
from django.utils import timezone
from django.utils.formats import date_format

from apps.assistant import costs
from apps.assistant.models import AssistantCommand, AssistantUsage, ManagerInstruction
from apps.tenancy.admin_base import CompanyOwnedAdmin


@admin.register(ManagerInstruction)
class ManagerInstructionAdmin(admin.ModelAdmin):
    list_display = ("location", "position", "employee", "created_at")
    list_filter = ("company",)
    raw_id_fields = ("location", "employee", "created_by")


@admin.register(AssistantCommand)
class AssistantCommandAdmin(admin.ModelAdmin):
    list_display = ("location", "status", "text", "reply", "created_at")
    list_filter = ("status", "company")
    raw_id_fields = ("location", "created_by")
    readonly_fields = ("assistant_answer",)

    @admin.display(description="odpowiedź asystenta")
    def reply(self, command: AssistantCommand) -> str:
        """The assistant's own words to the manager, to sample real answers (wrong data, promised shifts)."""
        return (command.plan or {}).get("reply") or ""


@admin.register(AssistantUsage)
class AssistantUsageAdmin(CompanyOwnedAdmin):
    """What each message cost (read only), and the month's summary per company, location and person."""

    list_display = ("created_at", "company", "location", "user", "kind", "cost", "calls", "output_tokens", "failed")
    list_filter = ("kind", "failed", "backend", "company")
    list_select_related = ("company", "location", "user")
    date_hierarchy = "created_at"

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    @admin.display(description="koszt (USD)", ordering="cost_usd")
    def cost(self, usage: AssistantUsage) -> str:
        return "bez ceny" if usage.cost_usd is None else f"{usage.cost_usd:.5f}"

    def get_urls(self):
        summary = path(
            "summary/", self.admin_site.admin_view(self.summary_view), name="assistant_assistantusage_summary"
        )
        return [summary, *super().get_urls()]

    def summary_view(self, request):
        if not self.has_view_permission(request):
            raise PermissionDenied
        try:
            month = costs.parse_month(request.GET["month"])
        except (KeyError, ValueError):
            month = timezone.localdate().replace(day=1)
        by = request.GET.get("csv")
        if by in costs.BY_CHOICES:
            response = HttpResponse(content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = f'attachment; filename="koszty-asystenta-{month:%Y-%m}-{by}.csv"'
            writer = csv.writer(response)
            for line in costs.csv_rows(month, by):
                writer.writerow(line)
            return response
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": f"Koszty asystenta: {date_format(month, 'F Y').lower()}",
            "month_value": f"{month:%Y-%m}",
            "total": costs.total(month),
            "tables": [
                {"by": "company", "title": "Firmy", "rows": costs.summary(month, "company")},
                {"by": "location", "title": "Lokale", "rows": costs.summary(month, "location")},
                {"by": "person", "title": "Osoby", "rows": costs.summary(month, "person")},
            ],
        }
        return render(request, "admin/assistant/assistantusage/summary.html", context)
