import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from .analytics import (
    assignment_overview,
    as_plaintext,
    build_do_now,
    build_exit_tickets,
    build_game_seed,
    build_sentence_builders,
    heatmap_data,
    mode_breakdown,
    pick_hinge_question,
    student_mastery,
    word_stats,
)
from .models import Assignment


def _teacher_can_view(user, assignment: Assignment) -> bool:
    if not user.is_authenticated or not getattr(user, "is_teacher", False):
        return False
    if assignment.teacher_id == user.id:
        return True
    if assignment.class_assigned_id is None:
        return False
    return assignment.class_assigned.teachers.filter(id=user.id).exists()


@login_required
@require_GET
def api_word_stats(request, assignment_id):
    assignment = get_object_or_404(Assignment, id=assignment_id)
    if not _teacher_can_view(request.user, assignment):
        return HttpResponseForbidden()
    return JsonResponse({"results": word_stats(assignment_id)})


@login_required
@require_GET
def api_mode_breakdown(request, assignment_id):
    assignment = get_object_or_404(Assignment, id=assignment_id)
    if not _teacher_can_view(request.user, assignment):
        return HttpResponseForbidden()
    return JsonResponse({"results": mode_breakdown(assignment_id)})


@login_required
@require_GET
def api_student_mastery(request, assignment_id):
    assignment = get_object_or_404(Assignment, id=assignment_id)
    if not _teacher_can_view(request.user, assignment):
        return HttpResponseForbidden()
    return JsonResponse({"results": student_mastery(assignment_id)})


@login_required
@require_GET
def api_heatmap(request, assignment_id):
    assignment = get_object_or_404(Assignment, id=assignment_id)
    if not _teacher_can_view(request.user, assignment):
        return HttpResponseForbidden()
    return JsonResponse(heatmap_data(assignment_id))


@login_required
@require_GET
def api_overview(request, assignment_id):
    assignment = get_object_or_404(Assignment, id=assignment_id)
    if not _teacher_can_view(request.user, assignment):
        return HttpResponseForbidden()
    return JsonResponse({"results": assignment_overview(assignment_id)})


@login_required
@require_POST
def api_generate_activity(request):
    try:
        payload = json.loads(request.body.decode())
        assignment_id = payload["assignment_id"]
        activity_type = payload["activity_type"]
    except Exception:
        return HttpResponseBadRequest("Invalid JSON body")

    assignment = get_object_or_404(Assignment.objects.select_related("class_assigned"), id=assignment_id)
    if not _teacher_can_view(request.user, assignment):
        return HttpResponseForbidden()

    if activity_type == "do_now":
        data = build_do_now(assignment_id)
    elif activity_type == "exit_tickets":
        data = build_exit_tickets(assignment_id)
    elif activity_type == "hinge":
        data = pick_hinge_question(assignment_id)
    elif activity_type == "sentences":
        data = build_sentence_builders(assignment_id)
    elif activity_type == "game_seed":
        data = build_game_seed(assignment_id)
    else:
        return HttpResponseBadRequest("Unknown activity_type")

    return JsonResponse({"activity": data, "clipboard": as_plaintext(data)})
