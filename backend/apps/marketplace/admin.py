from django.contrib import admin

from apps.marketplace.models import ShiftClaim, ShiftOffer
from apps.tenancy.admin_base import CompanyOwnedAdmin


@admin.register(ShiftOffer)
class ShiftOfferAdmin(CompanyOwnedAdmin):
    list_display = ("assignment", "offered_by", "status", "created_at")
    list_filter = ("company", "status")
    raw_id_fields = ("assignment", "offered_by")


@admin.register(ShiftClaim)
class ShiftClaimAdmin(CompanyOwnedAdmin):
    list_display = ("offer", "employee", "status", "created_at")
    list_filter = ("company", "status")
    raw_id_fields = ("offer", "employee", "decided_by")
