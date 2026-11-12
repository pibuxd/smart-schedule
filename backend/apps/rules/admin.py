from django.contrib import admin

from apps.rules.models import RuleSetting, WeightProfile
from apps.tenancy.admin_base import CompanyOwnedAdmin


@admin.register(RuleSetting)
class RuleSettingAdmin(CompanyOwnedAdmin):
    list_display = ("position", "rule_code", "group", "location", "enabled", "is_hard", "params")
    list_filter = ("company", "rule_code", "enabled", "is_hard")
    list_select_related = ("company", "group", "location")


@admin.register(WeightProfile)
class WeightProfileAdmin(CompanyOwnedAdmin):
    """The only place where weights can be changed; the app itself never shows them."""

    list_display = ("__str__", "company", "manager_share", "rank_decay", "stability_penalty")
    list_select_related = ("company", "group", "location")
