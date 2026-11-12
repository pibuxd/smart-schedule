from django.contrib import admin

from apps.billing.models import AccessCode, CodeAttempt, CodeRedemption, GenerationUsage, Subscription
from apps.tenancy.admin_base import CompanyOwnedAdmin


@admin.register(AccessCode)
class AccessCodeAdmin(admin.ModelAdmin):
    # Generating codes in batches (with the plain code shown once) arrives in stage 3.
    list_display = ("prefix", "days", "uses", "max_uses", "valid_until", "note", "created_at")
    search_fields = ("prefix", "note")
    readonly_fields = ("prefix", "uses", "created_by", "created_at")

    def has_add_permission(self, request):
        return False


@admin.register(CodeRedemption)
class CodeRedemptionAdmin(CompanyOwnedAdmin):
    list_display = ("code", "company", "user", "days_added", "redeemed_at")
    list_select_related = ("company", "code", "user")
    raw_id_fields = ("user",)


@admin.register(CodeAttempt)
class CodeAttemptAdmin(admin.ModelAdmin):
    list_display = ("user", "ip", "at", "success")
    list_filter = ("success",)
    raw_id_fields = ("user",)


@admin.register(Subscription)
class SubscriptionAdmin(CompanyOwnedAdmin):
    list_display = ("company", "ends_at", "source", "status_label")


@admin.register(GenerationUsage)
class GenerationUsageAdmin(CompanyOwnedAdmin):
    list_display = ("company", "month", "count")
