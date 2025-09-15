from rest_framework import serializers
from .models import Trophy, TrophyUnlock


class TrophySerializer(serializers.ModelSerializer):
    class Meta:
        model = Trophy
        fields = [
            "id",
            "name",
            "category",
            "trigger_type",
            "metric",
            "comparator",
            "threshold",
            "window",
            "subject_scope",
            "repeatable",
            "cooldown",
            "points",
            "icon",
            "rarity",
            "description",
            "constraints",
        ]


class TrophyUnlockSerializer(serializers.ModelSerializer):
    trophy = TrophySerializer(read_only=True)

    class Meta:
        model = TrophyUnlock
        fields = ["id", "trophy", "earned_at", "context"]
