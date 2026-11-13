from django.contrib import admin

from apps.staffing.models import EmployeeProfile, Position, ShiftType, StaffingException, StaffingRule
from apps.tenancy.admin_base import CompanyOwnedAdmin


@admin.register(Position)
class PositionAdmin(CompanyOwnedAdmin):
    list_display = ("name", "location", "company")
    list_filter = ("company", "location")
    list_select_related = ("company", "location")


@admin.register(ShiftType)
class ShiftTypeAdmin(CompanyOwnedAdmin):
    list_display = ("name", "location", "kind", "start_time", "end_time", "is_closing")
    list_filter = ("company", "location", "kind")
    list_select_related = ("company", "location")


@admin.register(StaffingRule)
class StaffingRuleAdmin(CompanyOwnedAdmin):
    list_display = ("location", "weekday", "shift_type", "position", "count")
    list_filter = ("company", "location", "weekday")
    list_select_related = ("company", "location", "shift_type", "position")


@admin.register(StaffingException)
class StaffingExceptionAdmin(CompanyOwnedAdmin):
    list_display = ("location", "date", "shift_type", "position", "count", "note")
    list_filter = ("company", "location")
    list_select_related = ("company", "location", "shift_type", "position")
    date_hierarchy = "date"


@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(CompanyOwnedAdmin):
    list_display = ("__str__", "home_location", "max_hours_month", "target_hours_month", "is_active")
    list_filter = ("company", "home_location", "is_active")
    list_select_related = ("company", "home_location", "membership__user")
    search_fields = ("membership__user__first_name", "membership__user__last_name", "membership__user__phone_e164")
    raw_id_fields = ("membership",)
    filter_horizontal = ("positions",)
