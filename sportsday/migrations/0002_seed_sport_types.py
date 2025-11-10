from django.db import migrations


TRACK_EVENTS = ["100m", "200m", "400m", "800m", "1500m", "4x100m Relay"]
FIELD_DISTANCE_EVENTS = ["Shot Put", "Javelin", "Discus", "Long Jump", "Triple Jump", "High Jump"]
FIELD_COUNT_EVENTS = ["Pull-ups", "Sit-ups"]
RANK_ONLY_EVENTS = ["Cross Country"]


def seed_sport_types(apps, schema_editor):
    SportType = apps.get_model("sportsday", "SportType")

    for label in TRACK_EVENTS:
        SportType.objects.update_or_create(
            key=label.lower().replace(" ", "-"),
            defaults={
                "label": label,
                "archetype": "TRACK_TIME",
                "default_unit": "sec",
                "default_attempts": 1,
                "default_capacity": 8,
                "supports_heats": True,
                "supports_finals": True,
                "requires_time_for_first_place": True,
                "notes": "",
            },
        )

    for label in FIELD_DISTANCE_EVENTS:
        SportType.objects.update_or_create(
            key=label.lower().replace(" ", "-"),
            defaults={
                "label": label,
                "archetype": "FIELD_DISTANCE",
                "default_unit": "m",
                "default_attempts": 6,
                "default_capacity": 8,
                "supports_heats": False,
                "supports_finals": True,
                "requires_time_for_first_place": False,
                "notes": "",
            },
        )

    for label in FIELD_COUNT_EVENTS:
        SportType.objects.update_or_create(
            key=label.lower().replace(" ", "-"),
            defaults={
                "label": label,
                "archetype": "FIELD_COUNT",
                "default_unit": "count",
                "default_attempts": 6,
                "default_capacity": 8,
                "supports_heats": False,
                "supports_finals": True,
                "requires_time_for_first_place": False,
                "notes": "",
            },
        )

    for label in RANK_ONLY_EVENTS:
        SportType.objects.update_or_create(
            key=label.lower().replace(" ", "-"),
            defaults={
                "label": label,
                "archetype": "RANK_ONLY",
                "default_unit": "sec",
                "default_attempts": 1,
                "default_capacity": 8,
                "supports_heats": False,
                "supports_finals": False,
                "requires_time_for_first_place": True,
                "notes": "",
            },
        )


def unseed_sport_types(apps, schema_editor):
    SportType = apps.get_model("sportsday", "SportType")
    keys = [
        label.lower().replace(" ", "-")
        for label in TRACK_EVENTS + FIELD_DISTANCE_EVENTS + FIELD_COUNT_EVENTS + RANK_ONLY_EVENTS
    ]
    SportType.objects.filter(key__in=keys).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("sportsday", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_sport_types, unseed_sport_types),
    ]
