from django.contrib import admin

from apps.assistant.models import AssistantCommand, ManagerInstruction


@admin.register(ManagerInstruction)
class ManagerInstructionAdmin(admin.ModelAdmin):
    list_display = ("location", "position", "employee", "created_at")
    list_filter = ("company",)
    raw_id_fields = ("location", "employee", "created_by")


@admin.register(AssistantCommand)
class AssistantCommandAdmin(admin.ModelAdmin):
    list_display = ("location", "status", "text", "reply", "created_at")
    list_filter = ("status", "company")
    raw_id_fields = ("location", "created_by")
    readonly_fields = ("assistant_answer",)

    @admin.display(description="odpowiedź asystenta")
    def reply(self, command: AssistantCommand) -> str:
        """The assistant's own words to the manager, to sample real answers (wrong data, promised shifts)."""
        return (command.plan or {}).get("reply") or ""
