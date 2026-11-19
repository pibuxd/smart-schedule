from django.db import migrations, models


def mark_from_staffing(apps, schema_editor):
    """Shifts of drafts and published versions from today on get the flag the staffing gives them now
    (older versions were saved without it, so their experienced quota was never checked)."""
    from datetime import date

    Shift = apps.get_model("scheduling", "Shift")
    StaffingRule = apps.get_model("staffing", "StaffingRule")
    StaffingException = apps.get_model("staffing", "StaffingException")
    usual = {
        (r.location_id, r.weekday, r.shift_type_id, r.position_id): r.experienced
        for r in StaffingRule.objects.filter(experienced__gt=0)
    }
    special = {
        (e.location_id, e.date, e.shift_type_id, e.position_id): e.experienced for e in StaffingException.objects.all()
    }
    if not usual and not any(special.values()):
        return
    rows = Shift.objects.filter(
        date__gte=date.today(), version__status__in=["draft", "published"], shift_type__isnull=False
    )
    marked = []
    for shift in rows.only("pk", "location_id", "date", "shift_type_id", "position_id", "slot_key"):
        key = (shift.location_id, shift.date, shift.shift_type_id, shift.position_id)
        need = special.get(key, usual.get((shift.location_id, shift.date.weekday(), *key[2:]), 0))
        if need and int(shift.slot_key.rsplit("/", 1)[1]) <= need:
            marked.append(shift.pk)
    Shift.objects.filter(pk__in=marked).update(needs_experienced=True)


class Migration(migrations.Migration):
    dependencies = [
        ("scheduling", "0008_deadline_set_at"),
        ("staffing", "0006_location_closure"),
    ]

    operations = [
        migrations.AddField(
            model_name="shift",
            name="needs_experienced",
            field=models.BooleanField(default=False, verbose_name="dla doświadczonej osoby"),
        ),
        migrations.RunPython(mark_from_staffing, migrations.RunPython.noop),
    ]
