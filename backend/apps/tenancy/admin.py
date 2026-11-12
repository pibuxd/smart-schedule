from django.contrib import admin

from apps.tenancy.admin_base import CompanyOwnedAdmin
from apps.tenancy.models import Company, Invitation, Location, LocationGroup, Membership


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "created_by", "created_at")
    search_fields = ("name",)
    raw_id_fields = ("created_by",)


@admin.register(LocationGroup)
class LocationGroupAdmin(CompanyOwnedAdmin):
    list_display = ("name", "company")
    search_fields = ("name",)


@admin.register(Location)
class LocationAdmin(CompanyOwnedAdmin):
    list_display = ("name", "company", "group", "schedule_period", "availability_deadline_days")
    list_select_related = ("company", "group")
    search_fields = ("name", "address")


@admin.register(Membership)
class MembershipAdmin(CompanyOwnedAdmin):
    list_display = ("user", "company", "role", "created_at")
    list_filter = ("company", "role")
    list_select_related = ("company", "user")
    search_fields = ("user__phone_e164", "user__first_name", "user__last_name")
    raw_id_fields = ("user",)
    filter_horizontal = ("locations",)


@admin.register(Invitation)
class InvitationAdmin(CompanyOwnedAdmin):
    list_display = ("phone_e164", "location", "role", "status", "created_at", "decided_at")
    list_filter = ("company", "status", "role")
    list_select_related = ("company", "location")
    search_fields = ("phone_e164",)
    raw_id_fields = ("invited_by",)
