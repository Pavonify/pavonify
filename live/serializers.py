"""Serializers for live game REST endpoints."""

from __future__ import annotations

from typing import Any, Dict, Optional

from django.conf import settings
from rest_framework import serializers

from learning.models import Class, VocabularyList

from .models import LiveGameParticipant, LiveGameSession


class LiveGameCreateSerializer(serializers.Serializer):
    class_id = serializers.UUIDField()
    vocab_list_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False
    )
    total_questions = serializers.IntegerField(min_value=1)
    question_time_sec = serializers.IntegerField(required=False, min_value=5)
    scoring_mode = serializers.ChoiceField(
        choices=[choice for choice, _ in LiveGameSession._meta.get_field("scoring_mode").choices],
        default="STANDARD",
    )

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        teacher = self.context["request"].user
        try:
            clazz = Class.objects.get(id=attrs["class_id"])
        except Class.DoesNotExist as exc:  # pragma: no cover - defensive
            raise serializers.ValidationError({"class_id": "Class not found."}) from exc

        if not teacher.is_teacher:
            raise serializers.ValidationError("Only teachers can create live games.")

        if not clazz.teachers.filter(id=teacher.id).exists():
            raise serializers.ValidationError("Teacher does not own this class.")

        vocab_lists = list(
            VocabularyList.objects.filter(id__in=attrs["vocab_list_ids"])
        )
        if len(vocab_lists) != len(set(attrs["vocab_list_ids"])):
            raise serializers.ValidationError("One or more vocab lists not found.")

        attrs.setdefault("question_time_sec", settings.QUESTION_TIME_DEFAULT)
        attrs["clazz"] = clazz
        attrs["vocab_lists"] = vocab_lists
        return attrs


class LiveGameSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LiveGameSession
        fields = [
            "id",
            "pin",
            "status",
            "total_questions",
            "question_time_sec",
            "scoring_mode",
            "clazz",
        ]
        read_only_fields = fields


class ParticipantSerializer(serializers.ModelSerializer):
    class Meta:
        model = LiveGameParticipant
        fields = ["display_name", "score", "streak", "joined_at"]


class LiveGameStateSerializer(serializers.Serializer):
    session_id = serializers.UUIDField()
    status = serializers.CharField()
    current_question_idx = serializers.IntegerField()
    total_questions = serializers.IntegerField()
    question_time_sec = serializers.IntegerField()
    started_at = serializers.DateTimeField(allow_null=True)
    deadline_at = serializers.DateTimeField(allow_null=True)
    leaderboard = serializers.ListField(child=serializers.DictField())
    you = serializers.DictField(allow_null=True)

    @classmethod
    def from_session(
        cls,
        session: LiveGameSession,
        *,
        you: Optional[LiveGameParticipant] = None,
        limit: int = 5,
    ) -> "LiveGameStateSerializer":
        top_participants = (
            session.participants.all()
            .order_by("-score", "total_latency_ms", "joined_at")[:limit]
        )
        leaderboard = [
            {
                "rank": idx + 1,
                "name": participant.display_name,
                "score": participant.score,
                "streak": participant.streak,
            }
            for idx, participant in enumerate(top_participants)
        ]

        you_payload = None
        if you:
            rank = (
                session.participants.filter(
                    score__gt=you.score
                ).count()
                + 1
            )
            you_payload = {
                "rank": rank,
                "score": you.score,
                "streak": you.streak,
            }

        serializer = cls(
            data={
                "session_id": session.id,
                "status": session.status,
                "current_question_idx": session.current_question_idx,
                "total_questions": session.total_questions,
                "question_time_sec": session.question_time_sec,
                "started_at": session.current_question_started_at,
                "deadline_at": session.current_question_deadline,
                "leaderboard": leaderboard,
                "you": you_payload,
            }
        )
        serializer.is_valid(raise_exception=True)
        return serializer
