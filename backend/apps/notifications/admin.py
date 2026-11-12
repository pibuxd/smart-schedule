from django.contrib import admin

from apps.notifications.models import Notification
from apps.tenancy.admin_base import CompanyOwnedAdmin


@admin.register(Notification)
class NotificationAdmin(CompanyOwnedAdmin):
    list_display = ("user", "kind", "company", "created_at", "read_at")
    list_select_related = ("company", "user")
    raw_id_fields = ("user",)
