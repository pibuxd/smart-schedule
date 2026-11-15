from django.contrib import admin

from apps.assistant.models import AssistantCommand, ManagerInstruction


@admin.register(ManagerInstruction)
class ManagerInstructionAdmin(admin.ModelAdmin):
    list_display = ("location", "position", "employee", "created_at")
    list_filter = ("company",)
    raw_id_fields = ("location", "employee", "created_by")


@admin.register(AssistantCommand)
class AssistantCommandAdmin(admin.ModelAdmin):
    list_display = ("location", "status", "text", "created_at")
    list_filter = ("status", "company")
    raw_id_fields = ("location", "created_by")
