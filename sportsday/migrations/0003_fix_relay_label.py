from django.db import migrations


def fix_label(apps, schema_editor):
    SportType = apps.get_model("sportsday", "SportType")
    updates = {
        "100m": "100m",
        "200m": "200m",
        "4x100m-relay": "4x100m Relay",
    }
    for key, label in updates.items():
        SportType.objects.filter(key=key).update(label=label)


def revert_label(apps, schema_editor):
    SportType = apps.get_model("sportsday", "SportType")
    reversions = {
        "100m": "100m Sprint",
        "200m": "200m Sprint",
        "4x100m-relay": "4×100m Relay",
    }
    for key, label in reversions.items():
        SportType.objects.filter(key=key).update(label=label)


class Migration(migrations.Migration):

    dependencies = [
        ("sportsday", "0002_seed_sport_types"),
    ]

    operations = [
        migrations.RunPython(fix_label, reverse_code=revert_label),
    ]
