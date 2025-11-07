import json
from typing import Any, Dict

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import (
    HttpResponseBadRequest,
    HttpResponseForbidden,
    JsonResponse,
)
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from learning.models import School, User
from learning.services.schools import build_school_leaderboard, school_teachers


def _json_body(request) -> Dict[str, Any]:
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body.decode() or "{}")
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise ValueError("Invalid JSON payload") from exc
        return payload
    return request.POST.dict()


@login_required
@require_POST
def create_school(request):
    if not getattr(request.user, "is_teacher", False):
        return HttpResponseForbidden("Only teachers can create schools.")

    try:
        payload = _json_body(request)
    except ValueError:
        return HttpResponseBadRequest("Invalid request body.")

    name = (payload.get("name") or "").strip()
    desired_code = (payload.get("school_code") or "").strip().upper() or None

    if not name:
        return JsonResponse({"error": "School name is required."}, status=400)

    with transaction.atomic():
        if request.user.school and not request.user.is_school_lead:
            return JsonResponse({"error": "You already belong to a school."}, status=400)

        if request.user.school and request.user.is_school_lead:
            school = request.user.school
            school.name = name
            update_fields = ["name"]
            if desired_code:
                if School.objects.exclude(pk=school.pk).filter(school_code=desired_code).exists():
                    return JsonResponse({"error": "That school code is already in use."}, status=400)
                school.school_code = desired_code
                update_fields.append("school_code")
            school.save(update_fields=update_fields)
        else:
            school = School.objects.create(name=name)
            if desired_code:
                if School.objects.filter(school_code=desired_code).exists():
                    return JsonResponse({"error": "That school code is already in use."}, status=400)
                school.school_code = desired_code
                school.save(update_fields=["school_code"])

            request.user.school = school
            request.user.is_school_lead = True
            request.user.save(update_fields=["school", "is_school_lead"])

    return JsonResponse(
        {
            "id": school.id,
            "name": school.name,
            "school_code": school.school_code,
            "is_school_lead": request.user.is_school_lead,
        },
        status=201 if request.user.is_school_lead else 200,
    )


@login_required
@require_POST
def join_school(request):
    if not getattr(request.user, "is_teacher", False):
        return HttpResponseForbidden("Only teachers can join schools.")

    try:
        payload = _json_body(request)
    except ValueError:
        return HttpResponseBadRequest("Invalid request body.")

    code = (payload.get("school_code") or "").strip().upper()
    if not code:
        return JsonResponse({"error": "A school code is required."}, status=400)

    school = get_object_or_404(School, school_code__iexact=code)

    if request.user.school_id == school.id:
        return JsonResponse(
            {
                "id": school.id,
                "name": school.name,
                "school_code": school.school_code,
                "message": "You are already part of this school.",
            }
        )

    if request.user.is_school_lead and request.user.school and request.user.school != school:
        return JsonResponse(
            {"error": "Leave your current school before joining another."},
            status=400,
        )

    request.user.school = school
    request.user.is_school_lead = False
    request.user.save(update_fields=["school", "is_school_lead"])

    return JsonResponse(
        {"id": school.id, "name": school.name, "school_code": school.school_code},
        status=200,
    )


@login_required
@require_GET
def list_teachers(request):
    school = getattr(request.user, "school", None)
    if not school:
        return JsonResponse({"error": "You are not linked to a school."}, status=404)

    teachers = [
        {
            "id": teacher.id,
            "name": teacher.get_full_name() or teacher.username,
            "email": teacher.email,
            "is_school_lead": teacher.is_school_lead,
        }
        for teacher in school_teachers(school)
    ]

    return JsonResponse(
        {
            "school": {
                "id": school.id,
                "name": school.name,
                "school_code": school.school_code,
            },
            "teachers": teachers,
        }
    )


@login_required
@require_GET
def school_leaderboard(request):
    school = getattr(request.user, "school", None)
    if not school:
        return JsonResponse({"error": "You are not linked to a school."}, status=404)

    leaderboard = build_school_leaderboard(school)

    return JsonResponse(
        {
            "school": {
                "id": school.id,
                "name": school.name,
                "school_code": school.school_code,
            },
            "top_students": leaderboard.top_students,
            "grade_totals": leaderboard.grade_totals,
            "language_totals": leaderboard.language_totals,
        }
    )
