"""Database models supporting live practice competitions."""

import uuid

from django.conf import settings
from django.db import models


User = settings.AUTH_USER_MODEL


class LiveGameSession(models.Model):
    """Represents a single teacher-hosted live practice game."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    host = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={"is_teacher": True},
        related_name="hosted_live_games",
    )
    clazz = models.ForeignKey(
        "learning.Class",
        on_delete=models.CASCADE,
        related_name="live_game_sessions",
    )
    vocab_lists = models.ManyToManyField(
        "learning.VocabularyList",
        related_name="live_game_sessions",
    )
    pin = models.CharField(max_length=6, unique=True, db_index=True)
    status = models.CharField(
        max_length=8,
        choices=[
            ("LOBBY", "Lobby"),
            ("RUNNING", "Running"),
            ("ENDED", "Ended"),
        ],
        default="LOBBY",
    )
    total_questions = models.PositiveIntegerField()
    question_time_sec = models.PositiveIntegerField(default=20)
    scoring_mode = models.CharField(
        max_length=12,
        choices=[
            ("STANDARD", "Standard"),
            ("FAST", "Fast"),
            ("STREAKY", "Streaky"),
        ],
        default="STANDARD",
    )
    current_question_idx = models.IntegerField(default=0)
    current_question_started_at = models.DateTimeField(null=True, blank=True)
    current_question_deadline = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:  # pragma: no cover - for admin/debugging
        return f"LiveGameSession({self.id}, class={self.clazz_id})"


class LiveGameParticipant(models.Model):
    """Represents a single student participating in a live game."""

    session = models.ForeignKey(
        LiveGameSession,
        related_name="participants",
        on_delete=models.CASCADE,
    )
    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="live_game_participations",
    )
    display_name = models.CharField(max_length=64)
    joined_at = models.DateTimeField(auto_now_add=True)
    is_connected = models.BooleanField(default=True)
    score = models.IntegerField(default=0)
    streak = models.IntegerField(default=0)
    total_latency_ms = models.IntegerField(default=0)

    class Meta:
        unique_together = (("session", "user"), ("session", "display_name"))
        ordering = ("-score", "total_latency_ms", "joined_at")

    def __str__(self) -> str:  # pragma: no cover
        return f"Participant({self.display_name})"


class LiveGameQuestion(models.Model):
    """Stores the question payload delivered to clients during the game."""

    session = models.ForeignKey(
        LiveGameSession,
        related_name="questions",
        on_delete=models.CASCADE,
    )
    index = models.PositiveIntegerField()
    payload = models.JSONField()

    class Meta:
        unique_together = ("session", "index")
        ordering = ("index",)

    def __str__(self) -> str:  # pragma: no cover
        return f"LiveGameQuestion(session={self.session_id}, index={self.index})"


class LiveGameAnswer(models.Model):
    """Stores answers submitted by participants."""

    participant = models.ForeignKey(
        LiveGameParticipant,
        related_name="answers",
        on_delete=models.CASCADE,
    )
    question = models.ForeignKey(
        LiveGameQuestion,
        related_name="answers",
        on_delete=models.CASCADE,
    )
    is_correct = models.BooleanField()
    latency_ms = models.IntegerField()
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("participant", "question")
        ordering = ("submitted_at",)

    def __str__(self) -> str:  # pragma: no cover
        return f"LiveGameAnswer(p={self.participant_id}, q={self.question_id})"
