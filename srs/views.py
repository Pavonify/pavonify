from datetime import timedelta
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from django.db import transaction
import json

from learning.models import Word, Student
from .models import StudentWordProgress, ActivityAttempt
from .scheduler import (
    compute_strength,
    MAX_ACTIVE_LEARNING_WORDS,
    ROTATION,
)


def get_student(request):
    return getattr(request.user, 'student', None) or Student.objects.first()


@require_http_methods(["GET"])
def lesson_seed(request):
    """Return an initial cohort of words for a lesson.

    Prefers brand new words, but if fewer than the requested limit exist,
    fills the remainder with due learning words.
    """
    student = get_student(request)
    limit = int(request.GET.get("limit", MAX_ACTIVE_LEARNING_WORDS))

    progresses = list(
        StudentWordProgress.objects.filter(student=student, status="new")[:limit]
    )
    if len(progresses) < limit:
        remaining = limit - len(progresses)
        due_learning = StudentWordProgress.objects.filter(
            student=student, status="learning", next_due_at__lte=timezone.now()
        )[:remaining]
        progresses.extend(list(due_learning))

    data = [
        {
            "word_id": p.word_id,
            "status": p.status,
            "suggested_next_activity": p.suggested_next_activity
            or ROTATION[0],
        }
        for p in progresses
    ]
    return JsonResponse(data, safe=False)


@require_http_methods(["GET"])
def queue(request):
    student = get_student(request)
    limit = int(request.GET.get("limit", 30))
    difficult_only = request.GET.get("difficult_only") == "true"
    now = timezone.now()
    qs = StudentWordProgress.objects.filter(student=student, next_due_at__lte=now)
    if difficult_only:
        qs = qs.filter(is_difficult=True)
    qs = qs.order_by("next_due_at")[:limit]
    data = [
        {
            "word_id": p.word_id,
            "strength": compute_strength(p),
            "next_due_at": p.next_due_at,
            "status": p.status,
            "suggested_next_activity": p.suggested_next_activity,
        }
        for p in qs
    ]
    return JsonResponse(data, safe=False)


@csrf_exempt
@require_http_methods(["POST"])
def attempt(request):
    student = get_student(request)
    payload = json.loads(request.body)
    word_id = payload.get("word_id")
    activity_type = payload.get("activity_type")
    is_correct = payload.get("is_correct")
    time_taken_ms = payload.get("time_taken_ms")
    hints_used = payload.get("hints_used", 0)

    word = get_object_or_404(Word, id=word_id)
    with transaction.atomic():
        progress, _ = StudentWordProgress.objects.select_for_update().get_or_create(
            student=student, word=word
        )
        ActivityAttempt.objects.create(
            student=student,
            word=word,
            activity_type=activity_type,
            is_correct=is_correct,
            time_taken_ms=time_taken_ms,
            hints_used=hints_used,
        )

        graduated_this_lesson = False

        if is_correct:
            progress.times_correct += 1
            progress.streak += 1
            if activity_type in ROTATION:
                expected = ROTATION[progress.lesson_path_index]
                if activity_type == expected:
                    progress.lesson_path_index += 1
                else:
                    progress.lesson_path_index = ROTATION.index(activity_type) + 1
            next_activity = (
                ROTATION[progress.lesson_path_index]
                if progress.lesson_path_index < len(ROTATION)
                else ROTATION[-1]
            )
        else:
            progress.times_incorrect += 1
            progress.streak = 0
            progress.lesson_errors += 1
            if activity_type == "typing":
                next_activity = "mcq"
            elif activity_type == "mcq":
                next_activity = "tapping"
            elif activity_type == "listening":
                next_activity = (
                    "mcq" if progress.last_activity_type == "listening" else "listening"
                )
            else:
                next_activity = activity_type
            progress.lesson_path_index = ROTATION.index(next_activity)

        # Graduation check: exposure->tapping->mcq->typing completed with ≤1 error
        if (
            is_correct
            and progress.lesson_path_index >= 4
            and progress.lesson_errors <= 1
            and progress.streak >= 2
        ):
            progress.status = "learning"
            progress.box_index = max(progress.box_index, 2)
            progress.next_due_at = timezone.now() + timedelta(hours=12)
            progress.lesson_path_index = 0
            progress.lesson_errors = 0
            graduated_this_lesson = True
            next_activity = ROTATION[0]

        progress.last_activity_type = activity_type
        progress.suggested_next_activity = next_activity
        progress.save()

    resp = {
        "word_id": word_id,
        "box_index": progress.box_index,
        "status": progress.status,
        "strength": progress.strength,
        "next_due_at": progress.next_due_at,
        "suggested_next_activity": progress.suggested_next_activity,
        "graduated_this_lesson": graduated_this_lesson,
    }
    return JsonResponse(resp)


@require_http_methods(["GET"])
def my_words(request):
    student = get_student(request)
    flt = request.GET.get("filter", "all")
    now = timezone.now()
    qs = StudentWordProgress.objects.filter(student=student)
    if flt == "learning":
        qs = qs.filter(status="learning")
    elif flt == "reviewing":
        qs = qs.filter(status="reviewing")
    elif flt == "mastered":
        qs = qs.filter(status="mastered")
    elif flt == "difficult":
        qs = qs.filter(is_difficult=True)
    elif flt == "overdue":
        qs = qs.filter(next_due_at__lt=now)
    qs = qs.order_by("next_due_at")
    data = [
        {
            "word_id": p.word_id,
            "strength": compute_strength(p),
            "first_seen_at": p.first_seen_at,
            "last_seen_at": p.last_seen_at,
            "next_due_at": p.next_due_at,
            "box_index": p.box_index,
            "status": p.status,
        }
        for p in qs
    ]
    return JsonResponse(data, safe=False)


@csrf_exempt
@require_http_methods(["PATCH"])
def toggle_difficult(request, word_id):
    student = get_student(request)
    progress = get_object_or_404(StudentWordProgress, student=student, word_id=word_id)
    progress.is_difficult = not progress.is_difficult
    progress.save()
    return JsonResponse({"word_id": word_id, "is_difficult": progress.is_difficult})


@require_http_methods(["GET"])
def stats_summary(request):
    student = get_student(request)
    now = timezone.now()
    qs = StudentWordProgress.objects.filter(student=student)
    data = {
        "due_today": qs.filter(next_due_at__date=now.date()).count(),
        "overdue": qs.filter(next_due_at__lt=now).count(),
        "learning": qs.filter(status="learning").count(),
        "mastered": qs.filter(status="mastered").count(),
        "difficult": qs.filter(is_difficult=True).count(),
    }
    return JsonResponse(data)
