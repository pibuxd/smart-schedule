from django.contrib import admin

from apps.scheduling.models import (
    Assignment,
    AssignmentEvent,
    GenerationRun,
    SchedulePeriod,
    ScheduleVersion,
    Shift,
)
from apps.tenancy.admin_base import CompanyOwnedAdmin


@admin.register(SchedulePeriod)
class SchedulePeriodAdmin(CompanyOwnedAdmin):
    list_display = ("location", "start", "end", "status")
    list_filter = ("company", "status", "location")
    list_select_related = ("company", "location")


@admin.register(ScheduleVersion)
class ScheduleVersionAdmin(CompanyOwnedAdmin):
    list_display = ("period", "number", "status", "is_complete", "created_at", "published_at")
    list_filter = ("company", "status")
    list_select_related = ("company", "period__location")
    raw_id_fields = ("period", "from_run", "created_by")


@admin.register(Shift)
class ShiftAdmin(CompanyOwnedAdmin):
    list_display = ("date", "location", "shift_type", "position", "start_at", "end_at")
    list_select_related = ("company", "location", "shift_type", "position")
    raw_id_fields = ("version",)
    date_hierarchy = "date"


@admin.register(Assignment)
class AssignmentAdmin(CompanyOwnedAdmin):
    list_display = ("shift", "employee", "pinned", "borrowed")
    list_select_related = ("company", "shift__position", "employee__membership__user")
    raw_id_fields = ("shift", "employee")


@admin.register(AssignmentEvent)
class AssignmentEventAdmin(CompanyOwnedAdmin):
    list_display = ("slot_key", "location", "from_employee", "to_employee", "reason", "at")
    list_select_related = ("company", "location")
    raw_id_fields = ("period", "from_employee", "to_employee", "by")


@admin.register(GenerationRun)
class GenerationRunAdmin(CompanyOwnedAdmin):
    list_display = ("created_at", "location", "group", "status", "solver_status", "time_ms")
    list_filter = ("company", "status", "solver_status")
    list_select_related = ("company", "location", "group")
    raw_id_fields = ("requested_by",)
