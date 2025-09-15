from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List

from django.db import transaction
from django.utils import timezone

from achievements.models import Trophy, TrophyUnlock


# Placeholder metric reader. Real implementation would query existing models
# for the given metric and window.
def read_metric(user, metric: str, window: str, context: Dict[str, Any]) -> Any:
    return 0


def compare(value: Any, comparator: str, threshold: Any) -> bool:
    if comparator == "gte":
        return value >= threshold
    if comparator == "lte":
        return value <= threshold
    if comparator == "eq":
        return value == threshold
    return False


def enforce_repeatable_and_cooldown(user, trophy: Trophy) -> bool:
    if not trophy.repeatable:
        return not TrophyUnlock.objects.filter(user=user, trophy=trophy).exists()
    if trophy.cooldown == "none":
        return True
    try:
        amount = int(trophy.cooldown[:-1])
        unit = trophy.cooldown[-1]
    except Exception:  # pragma: no cover - defensive
        return True
    delta = timedelta(days=amount) if unit == "d" else timedelta(hours=amount)
    latest = (
        TrophyUnlock.objects.filter(user=user, trophy=trophy)
        .order_by("-earned_at")
        .first()
    )
    if not latest:
        return True
    return timezone.now() - latest.earned_at >= delta


@transaction.atomic
def grant(user, trophy: Trophy, context: Dict[str, Any]) -> TrophyUnlock:
    unlock, _ = TrophyUnlock.objects.get_or_create(
        user=user, trophy=trophy, defaults={"context": context}
    )
    return unlock


def evaluate_user_trophies(user, context: Dict[str, Any] | None = None) -> List[TrophyUnlock]:
    context = context or {}
    unlocks: List[TrophyUnlock] = []
    for trophy in Trophy.objects.all():
        value = read_metric(user, trophy.metric, trophy.window, context)
        if compare(value, trophy.comparator, trophy.threshold):
            if enforce_repeatable_and_cooldown(user, trophy):
                unlocks.append(grant(user, trophy, context))
    return unlocks
