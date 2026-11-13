from django.db import migrations
from django.db.models import Max, Q

CODES = ("max_hours_per_day", "min_weekly_rest")


def switch_on(apps, schema_editor):
    """Piotr's decision (13.11.2026): the work-time rules that replaced the built-in labour law start switched on as
    soft rules. Every group, and every location outside a group, that already has rules gets them last on its list
    (a location in a group inherits them); the manager can switch them off or mark them "no exceptions"."""
    RuleSetting = apps.get_model("rules", "RuleSetting")
    scopes = list(
        RuleSetting.objects.filter(Q(group__isnull=False) | Q(location__group__isnull=True))
        .values("company_id", "group_id", "location_id")
        .annotate(last=Max("position"))
        .order_by()
    )
    new = []
    for scope in scopes:
        place = scope["last"]
        for code in CODES:
            if RuleSetting.objects.filter(
                group_id=scope["group_id"], location_id=scope["location_id"], rule_code=code
            ).exists():
                continue
            place += 1
            new.append(
                RuleSetting(
                    company_id=scope["company_id"],
                    group_id=scope["group_id"],
                    location_id=scope["location_id"],
                    rule_code=code,
                    position=place,
                )
            )
    RuleSetting.objects.bulk_create(new)


def switch_off(apps, schema_editor):
    apps.get_model("rules", "RuleSetting").objects.filter(rule_code__in=CODES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("rules", "0003_labour_rules"),
    ]

    operations = [
        migrations.RunPython(switch_on, switch_off),
    ]
