"""REST API views for live practice sessions."""

from __future__ import annotations

import random
import string
from datetime import timedelta
from typing import Any, Dict, Optional

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from learning.models import Student
from learning.services.question_flow import QuestionFlowEngine

from .models import (
    LiveGameAnswer,
    LiveGameParticipant,
    LiveGameQuestion,
    LiveGameSession,
)
from .scoring import calculate_score
from .serializers import (
    LiveGameCreateSerializer,
    LiveGameSessionSerializer,
    LiveGameStateSerializer,
)


ANNOUNCE_GROUP_PREFIX = "announce_class_"
GAME_GROUP_PREFIX = "live_game_"


class LiveGameSessionViewSet(viewsets.GenericViewSet):
    queryset = LiveGameSession.objects.all().select_related("clazz", "host")
    serializer_class = LiveGameSessionSerializer
    question_engine = QuestionFlowEngine()

    def get_serializer_class(self):  # type: ignore[override]
        if self.action == "create":
            return LiveGameCreateSerializer
        return super().get_serializer_class()

    def create(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not getattr(request.user, "is_teacher", False):
            return Response({"detail": "Authentication required."}, status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        pin = self._generate_pin()
        with transaction.atomic():
            session = LiveGameSession.objects.create(
                host=request.user,
                clazz=data["clazz"],
                pin=pin,
                total_questions=data["total_questions"],
                question_time_sec=data["question_time_sec"],
                scoring_mode=data["scoring_mode"],
            )
            session.vocab_lists.set(data["vocab_lists"])

        self._broadcast_class_announcement(session)
        response_serializer = LiveGameSessionSerializer(session)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        session = self.get_object()
        if session.host != request.user:
            return Response(status=status.HTTP_403_FORBIDDEN)
        if session.status != "LOBBY":
            return Response({"detail": "Session already started."}, status=status.HTTP_400_BAD_REQUEST)

        vocab_lists = list(session.vocab_lists.all())
        payloads = self.question_engine.build_question_payloads(vocab_lists, session.total_questions)

        with transaction.atomic():
            session.questions.all().delete()
            for idx, payload in enumerate(payloads, start=1):
                LiveGameQuestion.objects.create(session=session, index=idx, payload=payload)
            session.status = "RUNNING"
            session.started_at = timezone.now()
            session.current_question_idx = 0
            session.current_question_started_at = None
            session.current_question_deadline = None
            session.save(update_fields=[
                "status",
                "started_at",
                "current_question_idx",
                "current_question_started_at",
                "current_question_deadline",
                "updated_at",
            ])

        self._broadcast_to_game(session, {
            "type": "GAME_STARTED",
            "sessionId": str(session.id),
            "totalQuestions": session.total_questions,
            "questionTime": session.question_time_sec,
        })
        return Response(LiveGameSessionSerializer(session).data)

    @action(detail=True, methods=["post"], url_path="next")
    def next_question(self, request, pk=None):
        session = self.get_object()
        if session.host != request.user:
            return Response(status=status.HTTP_403_FORBIDDEN)
        if session.status != "RUNNING":
            return Response({"detail": "Session is not running."}, status=status.HTTP_400_BAD_REQUEST)

        total_questions = session.questions.count()
        if session.current_question_idx >= total_questions:
            return Response({"detail": "No more questions."}, status=status.HTTP_400_BAD_REQUEST)

        next_index = session.current_question_idx + 1
        question = session.questions.get(index=next_index)
        started_at = timezone.now()
        deadline = started_at + timedelta(seconds=session.question_time_sec)

        session.current_question_idx = next_index
        session.current_question_started_at = started_at
        session.current_question_deadline = deadline
        session.save(update_fields=[
            "current_question_idx",
            "current_question_started_at",
            "current_question_deadline",
            "updated_at",
        ])

        payload = dict(question.payload)

        self._broadcast_to_game(
            session,
            {
                "type": "QUESTION",
                "index": next_index,
                "payload": payload,
                "startedAt": started_at.isoformat(),
                "deadlineAt": deadline.isoformat(),
            },
        )
        return Response({"index": next_index})

    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        session = self.get_object()
        if session.host != request.user:
            return Response(status=status.HTTP_403_FORBIDDEN)

        session.status = "ENDED"
        session.ended_at = timezone.now()
        session.save(update_fields=["status", "ended_at", "updated_at"])

        leaderboard = self._build_leaderboard(session)
        self._broadcast_to_game(session, {
            "type": "GAME_ENDED",
            "finalTop": leaderboard,
        })
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def join(self, request, pk=None):
        session = self.get_object()
        student = self._resolve_student(request)
        if student is None:
            return Response({"detail": "Student authentication required."}, status=status.HTTP_403_FORBIDDEN)
        if not session.clazz.students.filter(id=student.id).exists():
            return Response({"detail": "Student not in this class."}, status=status.HTTP_403_FORBIDDEN)

        if session.participants.count() >= settings.GAME_MAX_CLASS_SIZE:
            return Response({"detail": "Session is full."}, status=status.HTTP_400_BAD_REQUEST)

        display_name = self._generate_display_name(student, session)
        participant = self._get_participant_from_session(session, request)
        if participant is None:
            display_name = self._generate_display_name(student, session)
            participant, _ = LiveGameParticipant.objects.get_or_create(
                session=session,
                display_name=display_name,
                defaults={"user": None},
            )
        request.session[f"live_participant_{session.id}"] = str(participant.id)
        request.session.modified = True

        state = LiveGameStateSerializer.from_session(session, you=participant)
        self._broadcast_to_game(session, {
            "type": "LOBBY_UPDATE",
            "participants": [p.display_name for p in session.participants.all()],
            "pin": session.pin,
        })
        return Response(state.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def answer(self, request, pk=None):
        session = self.get_object()
        student = self._resolve_student(request)
        if student is None:
            return Response({"detail": "Student authentication required."}, status=status.HTTP_403_FORBIDDEN)

        participant = self._get_participant_from_session(session, request)
        if not participant:
            return Response({"detail": "Join the session first."}, status=status.HTTP_400_BAD_REQUEST)

        question_index = request.data.get("questionIndex")
        answer_payload = request.data.get("answerPayload")
        if not isinstance(question_index, int):
            return Response({"detail": "Invalid question index."}, status=status.HTTP_400_BAD_REQUEST)

        if session.current_question_idx != question_index:
            return Response({"detail": "Question mismatch."}, status=status.HTTP_409_CONFLICT)

        try:
            question = session.questions.get(index=question_index)
        except LiveGameQuestion.DoesNotExist:
            return Response({"detail": "Question not found."}, status=status.HTTP_404_NOT_FOUND)

        if LiveGameAnswer.objects.filter(participant=participant, question=question).exists():
            return Response({"detail": "Answer already submitted."}, status=status.HTTP_409_CONFLICT)

        if session.current_question_deadline and timezone.now() > session.current_question_deadline:
            return Response({"detail": "Too late."}, status=status.HTTP_400_BAD_REQUEST)

        if session.current_question_started_at:
            latency_ms = int((timezone.now() - session.current_question_started_at).total_seconds() * 1000)
        else:
            latency_ms = 0

        normalize_result = self.question_engine.normalize_and_score(question.payload, answer_payload)
        score_result = calculate_score(normalize_result.is_correct, latency_ms, participant.streak)

        with transaction.atomic():
            LiveGameAnswer.objects.create(
                participant=participant,
                question=question,
                is_correct=normalize_result.is_correct,
                latency_ms=latency_ms,
            )
            participant.score += score_result.score_delta
            participant.streak = score_result.new_streak
            participant.total_latency_ms += latency_ms
            participant.save(update_fields=["score", "streak", "total_latency_ms"])

        leaderboard = self._build_leaderboard(session)
        you_snapshot = {
            "rank": self._participant_rank(session, participant),
            "score": participant.score,
            "streak": participant.streak,
        }
        self._broadcast_to_game(
            session,
            {"type": "LEADERBOARD", "top": leaderboard, "you": you_snapshot},
        )

        return Response({
            "accepted": True,
            "isCorrect": normalize_result.is_correct,
            "scoreDelta": score_result.score_delta,
        })

    @action(detail=True, methods=["get"])
    def state(self, request, pk=None):
        session = self.get_object()
        participant = self._get_participant_from_session(session, request)
        serializer = LiveGameStateSerializer.from_session(session, you=participant)
        return Response(serializer.data)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _generate_pin(self) -> str:
        length = getattr(settings, "GAME_PIN_LENGTH", 6)
        while True:
            pin = "".join(random.choices(string.digits, k=length))
            if not LiveGameSession.objects.filter(pin=pin).exists():
                return pin

    def _broadcast_class_announcement(self, session: LiveGameSession) -> None:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            return
        async_to_sync(channel_layer.group_send)(
            f"{ANNOUNCE_GROUP_PREFIX}{session.clazz_id}",
            {
                "type": "broadcast",
                "event": {
                    "type": "GAME_ANNOUNCED",
                    "sessionId": str(session.id),
                    "pin": session.pin,
                    "hostName": session.host.get_full_name() or session.host.username,
                    "classId": str(session.clazz_id),
                    "questionTime": session.question_time_sec,
                },
            },
        )

    def _broadcast_to_game(self, session: LiveGameSession, payload: Dict[str, Any]) -> None:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            return
        async_to_sync(channel_layer.group_send)(
            f"{GAME_GROUP_PREFIX}{session.id}",
            {"type": "broadcast", "event": payload},
        )

    def _resolve_student(self, request) -> Optional[Student]:
        student_id = request.session.get("student_id")
        if not student_id:
            return None
        try:
            return Student.objects.get(id=student_id)
        except Student.DoesNotExist:  # pragma: no cover
            return None

    def _get_participant_from_session(
        self, session: LiveGameSession, request
    ) -> Optional[LiveGameParticipant]:
        participant_id = request.session.get(f"live_participant_{session.id}")
        if participant_id:
            return session.participants.filter(id=participant_id).first()
        student = self._resolve_student(request)
        if not student:
            return None
        return session.participants.filter(display_name__startswith=student.first_name).first()

    def _generate_display_name(self, student: Student, session: LiveGameSession) -> str:
        base = f"{student.first_name} {student.last_name[:1].upper()}."
        candidate = base
        suffix = 2
        while session.participants.filter(display_name=candidate).exists():
            candidate = f"{base}{suffix}"
            suffix += 1
        return candidate

    def _build_leaderboard(self, session: LiveGameSession, limit: int = 20) -> Any:
        participants = (
            session.participants.all()
            .order_by("-score", "total_latency_ms", "joined_at")[:limit]
        )
        return [
            {
                "rank": idx + 1,
                "name": participant.display_name,
                "score": participant.score,
                "streak": participant.streak,
            }
            for idx, participant in enumerate(participants)
        ]

    def _participant_rank(self, session: LiveGameSession, participant: LiveGameParticipant) -> int:
        return (
            session.participants.filter(score__gt=participant.score).count()
            + 1
        )
