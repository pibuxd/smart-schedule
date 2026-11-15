from django.db import migrations
from django.db.models import Max, Q

CODE = "personal_max_hours"
TOLERANCE = {"tolerance_pct": 10}


def keep_within_tolerance(apps, schema_editor):
    """Piotr's decision (15.11.2026): a person's own maximum of hours is kept "no exceptions", with 10 % to spare.
    Existing settings of the rule become hard with that tolerance; every group, and every location outside a group,
    that already has rules but not this one gets it last on its list (a location in a group inherits it)."""
    RuleSetting = apps.get_model("rules", "RuleSetting")
    for row in RuleSetting.objects.filter(rule_code=CODE):
        row.is_hard = row.enabled
        row.params = {**TOLERANCE, **(row.params or {})}
        row.save(update_fields=["is_hard", "params"])
    scopes = (
        RuleSetting.objects.filter(Q(group__isnull=False) | Q(location__group__isnull=True))
        .values("company_id", "group_id", "location_id")
        .annotate(last=Max("position"))
        .order_by()
    )
    new = [
        RuleSetting(
            company_id=scope["company_id"],
            group_id=scope["group_id"],
            location_id=scope["location_id"],
            rule_code=CODE,
            position=scope["last"] + 1,
            is_hard=True,
            params=TOLERANCE,
        )
        for scope in scopes
        if not RuleSetting.objects.filter(
            group_id=scope["group_id"], location_id=scope["location_id"], rule_code=CODE
        ).exists()
    ]
    RuleSetting.objects.bulk_create(new)


class Migration(migrations.Migration):
    dependencies = [
        ("rules", "0004_switch_on_work_time_rules"),
    ]

    operations = [
        migrations.RunPython(keep_within_tolerance, migrations.RunPython.noop),
    ]
