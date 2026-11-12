from django.contrib import admin

from apps.availability.models import AvailabilityDay, AvailabilityPattern, AvailabilitySubmission, TextRequest
from apps.tenancy.admin_base import CompanyOwnedAdmin

EMPLOYEE_SEARCH = ("employee__membership__user__first_name", "employee__membership__user__last_name")


@admin.register(AvailabilityDay)
class AvailabilityDayAdmin(CompanyOwnedAdmin):
    list_display = ("employee", "date", "state", "from_time", "to_time", "source")
    list_filter = ("company", "state", "source")
    list_select_related = ("company", "employee__membership__user")
    search_fields = EMPLOYEE_SEARCH
    raw_id_fields = ("employee",)
    date_hierarchy = "date"


@admin.register(AvailabilityPattern)
class AvailabilityPatternAdmin(CompanyOwnedAdmin):
    list_display = ("employee", "weekday", "state", "from_time", "to_time", "repeat_until")
    list_select_related = ("company", "employee__membership__user")
    search_fields = EMPLOYEE_SEARCH
    raw_id_fields = ("employee",)


@admin.register(AvailabilitySubmission)
class AvailabilitySubmissionAdmin(CompanyOwnedAdmin):
    list_display = ("employee", "period", "submitted_at")
    list_select_related = ("company", "employee__membership__user", "period__location")
    raw_id_fields = ("employee", "period")


@admin.register(TextRequest)
class TextRequestAdmin(CompanyOwnedAdmin):
    list_display = ("employee", "text", "status", "manager_priority", "manager_rejected", "created_at")
    list_filter = ("company", "status", "manager_priority")
    list_select_related = ("company", "employee__membership__user")
    search_fields = ("text", *EMPLOYEE_SEARCH)
    raw_id_fields = ("employee", "period")
