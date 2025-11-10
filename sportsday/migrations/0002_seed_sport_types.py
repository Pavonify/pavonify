from django.db import migrations


def seed_sport_types(apps, schema_editor):
    SportType = apps.get_model('sportsday', 'SportType')  # historical model, not direct import

    catalog = [
        # archetype, key, label, unit, capacity, attempts, supports_heats, supports_finals, requires_time_for_first_place
        ("TRACK_TIME", "100m", "100m Sprint", "sec", 8, 1, True, True, True),
        ("TRACK_TIME", "200m", "200m Sprint", "sec", 8, 1, True, True, True),
        ("TRACK_TIME", "400m", "400m", "sec", 8, 1, True, True, True),
        ("TRACK_TIME", "800m", "800m", "sec", 8, 1, True, True, True),
        ("TRACK_TIME", "1500m", "1500m", "sec", 8, 1, True, True, True),
        ("TRACK_TIME", "4x100m-relay", "4×100m Relay", "sec", 8, 1, True, True, True),

        ("FIELD_DISTANCE", "shot-put", "Shot Put", "m", 8, 6, False, True, False),
        ("FIELD_DISTANCE", "javelin", "Javelin", "m", 8, 6, False, True, False),
        ("FIELD_DISTANCE", "discus", "Discus", "m", 8, 6, False, True, False),
        ("FIELD_DISTANCE", "long-jump", "Long Jump", "m", 8, 6, False, True, False),
        ("FIELD_DISTANCE", "triple-jump", "Triple Jump", "m", 8, 6, False, True, False),
        ("FIELD_DISTANCE", "high-jump", "High Jump", "m", 8, 8, False, True, False),

        ("FIELD_COUNT", "pull-ups", "Pull-ups", "count", 20, 1, False, True, False),
        ("FIELD_COUNT", "sit-ups", "Sit-ups", "count", 20, 1, False, True, False),

        ("RANK_ONLY", "cross-country", "Cross Country", "sec", 50, 1, False, True, False),
    ]

    for archetype, key, label, unit, capacity, attempts, heats, finals, req_time in catalog:
        SportType.objects.update_or_create(
            key=key,
            defaults=dict(
                label=label,
                archetype=archetype,
                default_unit=unit,
                default_capacity=capacity,
                default_attempts=attempts,
                supports_heats=heats,
                supports_finals=finals,
                requires_time_for_first_place=req_time,
            ),
        )


def unseed_sport_types(apps, schema_editor):
    SportType = apps.get_model('sportsday', 'SportType')
    SportType.objects.filter(key__in=[
        "100m","200m","400m","800m","1500m","4x100m-relay",
        "shot-put","javelin","discus","long-jump","triple-jump","high-jump",
        "pull-ups","sit-ups","cross-country",
    ]).delete()


class Migration(migrations.Migration):

    # ✅ Ensure we run after tables are created
    dependencies = [
        ('sportsday', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_sport_types, reverse_code=unseed_sport_types),
    ]
