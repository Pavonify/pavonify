"""Utilities for computing vocabulary memory strength metrics."""
from __future__ import annotations

from math import log1p
from typing import Tuple

from django.utils import timezone

from .models import Progress

# Weighting factors for the composite memory score. These values were tuned to
# reward a healthy mix of accuracy, repeated exposure, and staying on schedule.
_SUCCESS_WEIGHT = 0.45
_STABILITY_WEIGHT = 0.35
_RECENCY_WEIGHT = 0.20


def _success_component(progress: Progress) -> float:
    """Return a success component between 0 and 1 based on accuracy.

    The denominator discounts past mistakes so that a learner can recover from
    early errors as they build a larger bank of correct attempts.
    """

    correct = progress.correct_attempts or 0
    incorrect = progress.incorrect_attempts or 0
    total = correct + incorrect
    if total == 0:
        return 0.0
    denominator = correct + 0.7 * incorrect
    if denominator == 0:
        return 0.0
    return min(1.0, correct / denominator)


def _stability_component(progress: Progress) -> float:
    """Return a stability component between 0 and 1 based on repetition count."""

    reviews = progress.review_count or 0
    if reviews <= 0:
        return 0.0
    # ``log1p`` dampens the contribution from very high review counts while still
    # rewarding the learner for revisiting a word multiple times.
    return min(1.0, log1p(reviews) / log1p(15))


def _recency_component(progress: Progress, *, now=None) -> float:
    """Return a recency component between 0 and 1 based on scheduling."""

    if now is None:
        now = timezone.now()

    interval_days = max(progress.interval or 1, 1)
    due = progress.next_due
    if due:
        if now <= due:
            return 1.0
        overdue_days = (now - due).total_seconds() / 86400
    elif progress.last_seen:
        overdue_days = (now - progress.last_seen).total_seconds() / 86400
    else:
        return 0.0

    overdue_ratio = max(0.0, overdue_days / interval_days)
    # Allow a little grace for slight overdue reviews, but drop sharply if a
    # word has been ignored for multiple intervals.
    return max(0.0, 1.0 - min(overdue_ratio, 2.0) * 0.5)


def calculate_memory_strength(progress: Progress, *, now=None) -> float:
    """Return a composite memory strength score between 0 and 1."""

    success = _success_component(progress)
    stability = _stability_component(progress)
    recency = _recency_component(progress, now=now)

    score = (
        _SUCCESS_WEIGHT * success
        + _STABILITY_WEIGHT * stability
        + _RECENCY_WEIGHT * recency
    )
    # Clamp the score to the [0, 1] interval.
    return max(0.0, min(1.0, score))


def memory_meter(progress: Progress, *, now=None) -> Tuple[int, str]:
    """Return (percent, label) representing the learner's memory strength."""

    strength = calculate_memory_strength(progress, now=now)
    percent = int(round(strength * 100))
    if percent >= 75:
        label = "high"
    elif percent >= 45:
        label = "medium"
    else:
        label = "low"
    return percent, label
