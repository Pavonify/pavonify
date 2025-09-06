from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from django.db import transaction
import json

from learning.models import Word, Student
from .models import StudentWordProgress, ActivityAttempt
from .scheduler import update_progress, suggest_activity, compute_strength


def get_student(request):
    return getattr(request.user, 'student', None) or Student.objects.first()


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
    progress, _ = StudentWordProgress.objects.get_or_create(student=student, word=word)
    with transaction.atomic():
        ActivityAttempt.objects.create(
            student=student,
            word=word,
            activity_type=activity_type,
            is_correct=is_correct,
            time_taken_ms=time_taken_ms,
            hints_used=hints_used,
        )
        update_progress(progress, is_correct)
        progress.last_activity_type = activity_type
        progress.suggested_next_activity = suggest_activity(activity_type, is_correct)
        progress.save()
    resp = {
        "word_id": word_id,
        "box_index": progress.box_index,
        "status": progress.status,
        "strength": progress.strength,
        "next_due_at": progress.next_due_at,
        "suggested_next_activity": progress.suggested_next_activity,
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
