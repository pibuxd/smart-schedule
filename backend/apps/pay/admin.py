from django.contrib import admin

from apps.pay.models import PaySupplement, PersonalRate, PositionRate
from apps.tenancy.admin_base import CompanyOwnedAdmin


@admin.register(PositionRate)
class PositionRateAdmin(CompanyOwnedAdmin):
    list_display = ("position", "valid_from", "hourly_rate", "company")
    raw_id_fields = ("position",)


@admin.register(PersonalRate)
class PersonalRateAdmin(CompanyOwnedAdmin):
    list_display = ("employee", "position", "valid_from", "hourly_rate", "company")
    raw_id_fields = ("employee", "position")


@admin.register(PaySupplement)
class PaySupplementAdmin(CompanyOwnedAdmin):
    list_display = ("name", "location", "start_time", "end_time", "kind", "value", "valid_from", "valid_until")
    raw_id_fields = ("location",)
    filter_horizontal = ("positions",)
