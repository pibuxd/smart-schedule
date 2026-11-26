from django.contrib import admin

from apps.notifications.models import Notification, PushDevice
from apps.tenancy.admin_base import CompanyOwnedAdmin


@admin.register(Notification)
class NotificationAdmin(CompanyOwnedAdmin):
    list_display = ("user", "kind", "company", "created_at", "read_at")
    list_select_related = ("company", "user")
    raw_id_fields = ("user",)


@admin.register(PushDevice)
class PushDeviceAdmin(admin.ModelAdmin):
    """Phones that get push notifications. Read only; deleting one unpins it until the app registers again."""

    list_display = ("__str__", "user", "platform", "created_at", "seen_at")
    list_filter = ("platform",)
    list_select_related = ("user",)
    search_fields = ("user__phone_e164", "user__last_name")
    fields = ("user", "platform", "sandbox", "created_at", "seen_at")
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
