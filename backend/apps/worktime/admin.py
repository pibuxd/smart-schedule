from django.contrib import admin

from apps.tenancy.admin_base import CompanyOwnedAdmin
from apps.worktime.models import HoursChange


@admin.register(HoursChange)
class HoursChangeAdmin(CompanyOwnedAdmin):
    list_display = ("employee", "date", "start_at", "end_at", "status", "by_manager", "created_at")
    list_filter = ("company", "status", "by_manager")
    raw_id_fields = ("location", "period", "employee", "requested_by", "decided_by", "source_request")
