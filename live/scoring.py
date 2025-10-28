"""Scoring helpers for live practice sessions."""

from dataclasses import dataclass


BASE_POINTS = 100
SPEED_BONUS_CEILING = 50
LATENCY_BUCKET_MS = 400
STREAK_BONUS_MULTIPLIER = 10


@dataclass
class ScoreResult:
    is_correct: bool
    score_delta: int
    new_streak: int
    latency_ms: int


def calculate_score(is_correct: bool, latency_ms: int, current_streak: int) -> ScoreResult:
    """Calculate score delta given correctness, latency, and streak."""

    if not is_correct:
        return ScoreResult(
            is_correct=False,
            score_delta=0,
            new_streak=0,
            latency_ms=latency_ms,
        )

    speed_bonus = max(0, SPEED_BONUS_CEILING - (latency_ms // LATENCY_BUCKET_MS))
    new_streak = current_streak + 1
    streak_bonus = STREAK_BONUS_MULTIPLIER * new_streak

    total = BASE_POINTS + speed_bonus + streak_bonus
    return ScoreResult(
        is_correct=True,
        score_delta=total,
        new_streak=new_streak,
        latency_ms=latency_ms,
    )
