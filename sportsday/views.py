"""HTMX-friendly views for the sportsday application."""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Iterable
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Max, Min, Prefetch, Q
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from . import forms, models, qr, services


WIZARD_SESSION_KEY = "sportsday_meet_wizard"
LOCKED_STATUS_CODE = 423


def _get_wizard_state(request: HttpRequest) -> dict[str, object]:
    """Return the wizard state stored in the session."""

    return request.session.get(WIZARD_SESSION_KEY, {}).copy()


def _event_lock_reason(event: models.Event) -> str | None:
    """Return a reason if the event cannot be modified."""

    if event.meet.is_locked:
        return "This meet is locked. Unlock it to continue editing."
    if event.is_locked:
        return "This event has been locked."
    return None


def _format_decimal(value: Decimal | None) -> str:
    if value is None:
        return "0"
    if value == value.quantize(Decimal("1")):
        return f"{value.quantize(Decimal('1'))}"
    return f"{value.quantize(Decimal('0.01'))}"


def _grade_sort_key(grade: str) -> tuple[int, str]:
    stripped = (grade or "").strip()
    if stripped.isdigit():
        return int(stripped), stripped
    return (999, stripped or "—")


def _gender_label(code: str) -> str:
    mapping = {
        models.Event.GenderLimit.MALE: "Boys",
        models.Event.GenderLimit.FEMALE: "Girls",
        models.Event.GenderLimit.MIXED: "Mixed",
    }
    return mapping.get(code, code)


def _teacher_for_user(user) -> models.Teacher | None:
    if not getattr(user, "is_authenticated", False):
        return None
    email = getattr(user, "email", "") or ""
    if not email:
        return None
    return models.Teacher.objects.filter(email__iexact=email).first()


def _student_filters(request: HttpRequest) -> dict[str, str | None]:
    """Extract student table filters from GET or POST data."""

    data = request.GET if request.method == "GET" else request.POST
    meet = (data.get("meet") or "").strip() or None
    house = (data.get("house") or "").strip() or None
    query = (data.get("q") or "").strip() or None
    return {"meet": meet, "house": house, "query": query}


def _student_filter_query(filters: dict[str, str | None]) -> str:
    params: dict[str, str] = {}
    meet = filters.get("meet")
    if meet:
        params["meet"] = meet
    house = filters.get("house")
    if house:
        params["house"] = house
    query = filters.get("query")
    if query:
        params["q"] = query
    return urlencode(params)


def _students_queryset(filters: dict[str, str | None]):
    students = models.Student.objects.all()
    tally_filter = Q()
    meet_slug = filters.get("meet")
    if meet_slug:
        tally_filter = Q(entries__event__meet__slug=meet_slug)
        students = students.filter(entries__event__meet__slug=meet_slug)
    house = filters.get("house")
    if house:
        students = students.filter(house__iexact=house)
    query = filters.get("query")
    if query:
        students = students.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(grade__icontains=query)
        )
    return (
        students.annotate(events_tally=Count("entries", filter=tally_filter, distinct=True))
        .order_by("last_name", "first_name")
        .distinct()
    )


def _students_redirect_url(filters: dict[str, str | None]) -> str:
    query_string = _student_filter_query(filters)
    destination = reverse("sportsday:students")
    if query_string:
        return f"{destination}?{query_string}"
    return destination


def _build_leaderboard_summaries(records: list[services.ScoringRecord]):
    overall: dict[str, dict[str, object]] = defaultdict(lambda: {"points": Decimal("0"), "athletes": set()})
    grade_totals: dict[str, dict[str, dict[str, object]]] = defaultdict(
        lambda: defaultdict(lambda: {"points": Decimal("0"), "athletes": set()})
    )
    event_totals: dict[models.Event, dict[str, object]] = defaultdict(
        lambda: {"house_points": defaultdict(lambda: Decimal("0")), "entries": 0}
    )
    participation: dict[str, dict[str, object]] = defaultdict(
        lambda: {"points": Decimal("0"), "entries": 0, "athletes": set(), "events": set()}
    )

    for record in records:
        house = record.house
        overall_entry = overall[house]
        overall_entry["points"] += record.total
        overall_entry["athletes"].add(record.student.pk)

        grade_entry = grade_totals[record.grade][house]
        grade_entry["points"] += record.total
        grade_entry["athletes"].add(record.student.pk)

        event_entry = event_totals[record.event]
        event_entry["house_points"][house] += record.total
        event_entry["entries"] += 1

        participation_entry = participation[house]
        participation_entry["points"] += record.participation
        participation_entry["entries"] += 1
        participation_entry["athletes"].add(record.student.pk)
        participation_entry["events"].add(record.event.pk)

    overall_rows = [
        {
            "house": house,
            "points": data["points"],
            "athletes": len(data["athletes"]),
        }
        for house, data in overall.items()
    ]
    overall_rows.sort(key=lambda item: (-item["points"], item["house"]))

    grade_rows = []
    for grade, houses in grade_totals.items():
        for house, data in houses.items():
            grade_rows.append(
                {
                    "grade": grade,
                    "house": house,
                    "points": data["points"],
                    "athletes": len(data["athletes"]),
                }
            )
    grade_rows.sort(key=lambda item: (_grade_sort_key(item["grade"]), -item["points"], item["house"]))

    event_rows = []
    for event, data in event_totals.items():
        house_points = data["house_points"]
        if not house_points:
            continue
        winner, top_points = max(
            house_points.items(), key=lambda item: (item[1], item[0])
        )
        event_rows.append(
            {
                "event": event,
                "house": winner,
                "points": top_points,
                "entries": data["entries"],
            }
        )
    event_rows.sort(key=lambda item: (-item["points"], item["event"].name))

    participation_rows = [
        {
            "house": house,
            "points": data["points"],
            "entries": data["entries"],
            "athletes": len(data["athletes"]),
            "events": len(data["events"]),
        }
        for house, data in participation.items()
    ]
    participation_rows.sort(key=lambda item: (-item["points"], item["house"]))

    return {
        "overall": overall_rows,
        "grade": grade_rows,
        "event": event_rows,
        "participation": participation_rows,
    }


def _set_wizard_state(request: HttpRequest, state: dict[str, object]) -> None:
    """Persist wizard state to the session."""

    request.session[WIZARD_SESSION_KEY] = state
    request.session.modified = True


def _clear_wizard_state(request: HttpRequest) -> None:
    """Remove wizard state from the session."""

    if WIZARD_SESSION_KEY in request.session:
        del request.session[WIZARD_SESSION_KEY]
        request.session.modified = True


def _get_wizard_meet(request: HttpRequest) -> models.Meet | None:
    """Return the meet currently being configured."""

    state = request.session.get(WIZARD_SESSION_KEY) or {}
    meet_id = state.get("meet_id")
    if not meet_id:
        return None
    return models.Meet.objects.filter(pk=meet_id).first()


def _build_meet_mobile_nav(meet: models.Meet, active: str = "start") -> tuple[list[dict[str, str]], str]:
    """Return the mobile nav definition for meet-scoped pages."""

    links = [
        {"label": "Start", "url": reverse("sportsday:meet-detail", kwargs={"slug": meet.slug})},
        {"label": "Results", "url": f"{reverse('sportsday:events')}?meet={meet.slug}"},
        {"label": "Leaders", "url": f"{reverse('sportsday:leaderboards')}?meet={meet.slug}"},
        {"label": "Students", "url": f"{reverse('sportsday:students')}?meet={meet.slug}"},
    ]
    return links, active


def _build_event_mobile_nav(event: models.Event, active: str = "start") -> tuple[list[dict[str, str]], str]:
    """Return the mobile nav definition for event scoped pages."""

    links = [
        {"label": "Start", "url": f"{reverse('sportsday:event-detail', kwargs={'pk': event.pk})}#event-start"},
        {"label": "Results", "url": f"{reverse('sportsday:event-detail', kwargs={'pk': event.pk})}#event-results"},
        {"label": "Leaders", "url": f"{reverse('sportsday:leaderboards')}?meet={event.meet.slug}"},
        {"label": "Students", "url": f"{reverse('sportsday:students')}?meet={event.meet.slug}"},
    ]
    return links, active


def dashboard(request: HttpRequest) -> HttpResponse:
    """Landing page with quick links and overview tiles."""

    meet_count = models.Meet.objects.count()
    event_count = models.Event.objects.count()
    student_count = models.Student.objects.count()
    teacher_count = models.Teacher.objects.count()
    upcoming_meet = models.Meet.objects.order_by("date").first()

    tiles = [
        {
            "overline": "Schedule",
            "title": "Meets",
            "description": "Plan fixtures, lock schedules, and coordinate logistics.",
            "badge": f"{meet_count:02}",
            "url": reverse("sportsday:meet-list"),
            "stats": [
                {"label": "Total meets", "value": meet_count},
                {"label": "Events", "value": event_count},
            ],
        },
        {
            "overline": "Athletes",
            "title": "Students",
            "description": "Track participation limits and build balanced teams.",
            "badge": f"{student_count:02}",
            "url": f"{reverse('sportsday:students')}{f'?meet={upcoming_meet.slug}' if upcoming_meet else ''}",
            "stats": [
                {"label": "Rostered", "value": student_count},
                {"label": "Avg events", "value": models.Entry.objects.count()},
            ],
        },
        {
            "overline": "Crew",
            "title": "Teachers",
            "description": "Assign officials to track, field, and support roles.",
            "badge": f"{teacher_count:02}",
            "url": reverse("sportsday:teachers"),
            "stats": [
                {"label": "Active staff", "value": teacher_count},
                {"label": "Assignments", "value": models.Event.objects.filter(assigned_teachers__isnull=False).count()},
            ],
        },
        {
            "overline": "Competition",
            "title": "Events",
            "description": "Manage heats, flights, and live scoring.",
            "badge": f"{event_count:02}",
            "url": f"{reverse('sportsday:events')}{f'?meet={upcoming_meet.slug}' if upcoming_meet else ''}",
            "stats": [
                {"label": "Scheduled", "value": event_count},
                {"label": "Results", "value": models.Result.objects.count()},
            ],
        },
        {
            "overline": "Scoring",
            "title": "Leaderboards",
            "description": "House points, grade champions, and participation insights.",
            "badge": "∞",
            "url": f"{reverse('sportsday:leaderboards')}{f'?meet={upcoming_meet.slug}' if upcoming_meet else ''}",
            "stats": [
                {"label": "Scoring rules", "value": models.ScoringRule.objects.count()},
                {"label": "Audit logs", "value": models.AuditLog.objects.count()},
            ],
        },
        {
            "overline": "Quick start",
            "title": "New Meet",
            "description": "Launch the guided wizard to spin up a fresh carnival.",
            "badge": "+",
            "url": reverse("sportsday:meet-create"),
            "stats": [
                {"label": "Templates", "value": models.SportType.objects.count()},
                {"label": "Locked meets", "value": models.Meet.objects.filter(is_locked=True).count()},
            ],
        },
    ]

    context = {
        "tiles": tiles,
        "active_meet": upcoming_meet,
    }
    return render(request, "sportsday/dashboard.html", context)


def meet_list(request: HttpRequest) -> HttpResponse:
    """List available meets with quick actions."""

    meets_qs = (
        models.Meet.objects.annotate(
            events_count=Count("events", distinct=True),
            entries_count=Count("events__entries", distinct=True),
            student_count=Count("events__entries__student", distinct=True),
            scheduled_events=Count(
                "events",
                filter=Q(events__schedule_dt__isnull=False),
                distinct=True,
            ),
        )
        .order_by("date", "name")
        .prefetch_related("events")
    )

    query = request.GET.get("q")
    if query:
        meets_qs = meets_qs.filter(Q(name__icontains=query) | Q(location__icontains=query))

    cards: list[dict[str, object]] = []
    for meet in meets_qs:
        events_total = meet.events_count or 0
        scheduled = getattr(meet, "scheduled_events", 0) or 0
        completion = round((scheduled / events_total) * 100) if events_total else 0
        if meet.is_locked:
            status = "Locked"
        elif events_total == 0:
            status = "Draft"
        elif meet.entries_count:
            status = "Active"
        else:
            status = "Scheduling"
        cards.append(
            {
                "meet": meet,
                "completion": min(completion, 100),
                "status": status,
            }
        )

    template = "sportsday/partials/meets_board.html" if request.headers.get("HX-Request") else "sportsday/meets_list.html"
    return render(request, template, {"cards": cards, "active_meet": None})


def meet_create(request: HttpRequest) -> HttpResponse:
    """Render the meet creation wizard."""

    meet = _get_wizard_meet(request)
    wizard_state = _get_wizard_state(request)
    steps = [
        {
            "key": "basics",
            "label": "Basics",
            "description": "Dates, slug, and the essentials to get started.",
            "title": "Meet basics",
            "tagline": "Step 1 of 3",
            "disabled": False,
        },
        {
            "key": "events",
            "label": "Events Builder",
            "description": "Add sport types, configure attempts, and plan the schedule.",
            "title": "Build events",
            "tagline": "Step 2 of 3",
            "disabled": meet is None,
        },
        {
            "key": "people",
            "label": "People",
            "description": "Bring students and staff into the mix.",
            "title": "Roster & officials",
            "tagline": "Step 3 of 3",
            "disabled": meet is None,
        },
    ]
    steps[0]["complete"] = meet is not None
    steps[1]["complete"] = bool(meet and meet.events.exists())
    steps[2]["complete"] = bool(wizard_state.get("people_uploaded"))

    step_map = {step["key"]: step for step in steps}
    requested_step = request.GET.get("step", "basics")
    current = step_map.get(requested_step, steps[0])
    if current.get("disabled"):
        current = steps[0]
    index = steps.index(current)
    previous_step = next((steps[i] for i in range(index - 1, -1, -1)), None)
    next_step = next((steps[i] for i in range(index + 1, len(steps))), None)

    context = {
        "steps": steps,
        "active_step": current["key"],
        "current_stage": {
            "title": current["title"],
            "tagline": current["tagline"],
            "lede": current["description"],
            "hx_url": f"{reverse('sportsday:meet-wizard-stage')}?step={current['key']}",
        },
        "previous_step": previous_step,
        "next_step": next_step,
        "next_step_enabled": bool(next_step and not next_step.get("disabled")),
        "active_meet": meet,
    }
    return render(request, "sportsday/meet_wizard.html", context)


def meet_wizard_stage(request: HttpRequest) -> HttpResponse:
    """Return the HTMX fragment for the requested wizard step."""

    step = request.GET.get("step", "basics")
    if step == "events":
        if request.method == "POST":
            action = request.POST.get("action")
            if action == "delete":
                return _wizard_delete_event(request)
            return _wizard_create_event(request)
        return _render_wizard_events(request)
    if step == "people":
        if request.method == "POST":
            return _wizard_people_post(request)
        return _render_wizard_people(request)
    if request.method == "POST":
        return _wizard_basics_post(request)
    return _render_wizard_basics(request)


def _wizard_basics_post(request: HttpRequest) -> HttpResponse:
    meet = _get_wizard_meet(request)
    scoring_rule = meet.scoring_rules.first() if meet else None
    form = forms.MeetBasicsForm(request.POST, instance=meet, scoring_rule=scoring_rule)
    if form.is_valid():
        meet = form.save()
        models.ScoringRule.objects.update_or_create(
            meet=meet,
            defaults={
                "points_csv": form.cleaned_data["points_csv"],
                "participation_point": form.cleaned_data["participation_point"],
                "tie_method": form.cleaned_data["tie_method"],
            },
        )
        _set_wizard_state(request, {"meet_id": meet.pk})
        return _render_wizard_basics(request, form=forms.MeetBasicsForm(instance=meet, scoring_rule=meet.scoring_rules.first()), saved=True)
    return _render_wizard_basics(request, form=form, saved=False)


def _render_wizard_basics(
    request: HttpRequest, form: forms.MeetBasicsForm | None = None, saved: bool = False
) -> HttpResponse:
    meet = _get_wizard_meet(request)
    scoring_rule = meet.scoring_rules.first() if meet else None
    if form is None:
        form = forms.MeetBasicsForm(instance=meet, scoring_rule=scoring_rule)
    preview_points, preview_participation = _resolve_scoring_preview(form)
    context = {
        "form": form,
        "meet": meet,
        "saved": saved,
        "scoring_preview": {
            "points_csv": preview_points,
            "participation_point": preview_participation,
        },
    }
    return render(request, "sportsday/partials/wizard_basics.html", context)


def _resolve_scoring_preview(form: forms.MeetBasicsForm) -> tuple[str, Decimal]:
    source = form.data if form.is_bound else form.initial
    preset_key = (source.get("scoring_preset") if hasattr(source, "get") else None) or form.initial.get("scoring_preset")
    if preset_key and preset_key != "custom":
        preset = next((item for item in forms.SCORING_PRESETS if item.key == preset_key), None)
        if preset:
            return preset.points_csv, preset.participation_point
    points_csv = None
    participation_point: Decimal | None = None
    if hasattr(source, "get"):
        points_csv = source.get("points_csv") or None
        participation_raw = source.get("participation_point") or None
    else:
        points_csv = source.get("points_csv") if isinstance(source, dict) else None
        participation_raw = source.get("participation_point") if isinstance(source, dict) else None
    if not points_csv:
        points_csv = form.initial.get("points_csv") or forms.SCORING_PRESETS[0].points_csv
    if participation_raw is None:
        participation_raw = form.initial.get("participation_point") or forms.SCORING_PRESETS[0].participation_point
    if isinstance(participation_raw, Decimal):
        participation_point = participation_raw
    else:
        try:
            participation_point = Decimal(str(participation_raw))
        except (ArithmeticError, ValueError, TypeError):
            participation_point = forms.SCORING_PRESETS[0].participation_point
    return str(points_csv), participation_point


def _render_wizard_events(
    request: HttpRequest, form: forms.EventConfigForm | None = None, saved: bool = False
) -> HttpResponse:
    meet = _get_wizard_meet(request)
    if not meet:
        return render(request, "sportsday/partials/wizard_events.html", {"meet": None, "events": []})
    teacher_qs = models.Teacher.objects.order_by("last_name", "first_name")
    selected_sport = None
    if form is None:
        sport_id = request.GET.get("sport") or request.GET.get("sport_type")
        initial: dict[str, object] = {}
        if sport_id:
            selected_sport = models.SportType.objects.filter(pk=sport_id).first()
            if selected_sport:
                initial = {
                    "sport_type": selected_sport,
                    "name": selected_sport.label,
                    "measure_unit": selected_sport.default_unit,
                    "capacity": selected_sport.default_capacity,
                    "attempts": selected_sport.default_attempts,
                }
        form = forms.EventConfigForm(initial=initial, teacher_queryset=teacher_qs)
        if selected_sport is None:
            selected_sport = initial.get("sport_type") if isinstance(initial.get("sport_type"), models.SportType) else None
    else:
        selected_sport = _determine_selected_sport(form)
    events = (
        meet.events.select_related("sport_type")
        .prefetch_related("assigned_teachers")
        .order_by("schedule_dt", "name")
    )
    context = {
        "meet": meet,
        "form": form,
        "events": events,
        "saved": saved,
        "selected_sport": selected_sport,
        "sport_types": models.SportType.objects.order_by("label"),
        "unit_choices": models.SportType.DefaultUnit.choices,
    }
    return render(request, "sportsday/partials/wizard_events.html", context)


def _determine_selected_sport(form: forms.EventConfigForm) -> models.SportType | None:
    if hasattr(form, "cleaned_data") and form.is_bound and form.is_valid():
        sport_type = form.cleaned_data.get("sport_type")
        if sport_type:
            return sport_type
    value = None
    if form.is_bound:
        value = form.data.get("sport_type")
    if not value:
        value = form.initial.get("sport_type")
    if isinstance(value, models.SportType):
        return value
    if value:
        try:
            return models.SportType.objects.get(pk=value)
        except (models.SportType.DoesNotExist, ValueError, TypeError):
            return None
    return None


def _wizard_create_event(request: HttpRequest) -> HttpResponse:
    meet = _get_wizard_meet(request)
    if not meet:
        return _render_wizard_events(request)
    teacher_qs = models.Teacher.objects.order_by("last_name", "first_name")
    form = forms.EventConfigForm(request.POST, teacher_queryset=teacher_qs)
    if form.is_valid():
        event = form.save(commit=False)
        event.meet = meet
        if not event.name:
            event.name = event.sport_type.label
        if not event.measure_unit:
            event.measure_unit = event.sport_type.default_unit
        if not event.capacity:
            event.capacity = event.sport_type.default_capacity
        if event.sport_type.archetype == models.SportType.Archetype.TRACK_TIME:
            event.attempts = 1
        elif not event.attempts:
            event.attempts = event.sport_type.default_attempts
        event.save()
        form.save_m2m()
        state = _get_wizard_state(request)
        state.update({"meet_id": meet.pk, "events_configured": True})
        _set_wizard_state(request, state)
        return _render_wizard_events(
            request,
            form=forms.EventConfigForm(
                initial={
                    "sport_type": event.sport_type,
                    "name": event.sport_type.label,
                    "measure_unit": event.sport_type.default_unit,
                    "capacity": event.sport_type.default_capacity,
                    "attempts": event.sport_type.default_attempts,
                },
                teacher_queryset=teacher_qs,
            ),
            saved=True,
        )
    return _render_wizard_events(request, form=form, saved=False)


def _wizard_delete_event(request: HttpRequest) -> HttpResponse:
    meet = _get_wizard_meet(request)
    if not meet:
        return _render_wizard_events(request)
    event_id = request.POST.get("event_id")
    if event_id:
        models.Event.objects.filter(meet=meet, pk=event_id).delete()
    meet.refresh_from_db()
    state = _get_wizard_state(request)
    state.update({"meet_id": meet.pk, "events_configured": meet.events.exists()})
    _set_wizard_state(request, state)
    return _render_wizard_events(request, saved=False)


def _render_wizard_people(
    request: HttpRequest,
    student_form: forms.StudentUploadForm | None = None,
    teacher_form: forms.TeacherUploadForm | None = None,
    summary: dict[str, object] | None = None,
) -> HttpResponse:
    meet = _get_wizard_meet(request)
    if not meet:
        return render(request, "sportsday/partials/wizard_people.html", {"meet": None})
    if student_form is None:
        student_form = forms.StudentUploadForm()
    if teacher_form is None:
        teacher_form = forms.TeacherUploadForm()
    summary = summary or {}
    summary.setdefault("students", None)
    summary.setdefault("teachers", None)
    students = (
        models.Student.objects.annotate(
            events_tally=Count("entries", filter=Q(entries__event__meet=meet), distinct=True)
        )
        .order_by("last_name", "first_name")
        .distinct()
    )
    context = {
        "meet": meet,
        "student_form": student_form,
        "teacher_form": teacher_form,
        "students": students,
        "summary": summary,
    }
    return render(request, "sportsday/partials/wizard_people.html", context)


def _wizard_people_post(request: HttpRequest) -> HttpResponse:
    meet = _get_wizard_meet(request)
    if not meet:
        return _render_wizard_people(request)
    upload_type = request.POST.get("upload_type")
    summary: dict[str, object] = {}
    student_form = forms.StudentUploadForm()
    teacher_form = forms.TeacherUploadForm()
    state = _get_wizard_state(request)
    if upload_type == "students":
        student_form = forms.StudentUploadForm(request.POST, request.FILES)
        if student_form.is_valid():
            result = _import_students(student_form.cleaned_data["file"])
            summary["students"] = result
            if result["created"] or result["updated"]:
                state.update({"meet_id": meet.pk, "people_uploaded": True})
                _set_wizard_state(request, state)
            student_form = forms.StudentUploadForm()
        else:
            summary["students"] = {"errors": student_form.errors.get("file")}
    elif upload_type == "teachers":
        teacher_form = forms.TeacherUploadForm(request.POST, request.FILES)
        if teacher_form.is_valid():
            result = _import_teachers(teacher_form.cleaned_data["file"])
            summary["teachers"] = result
            if result["created"] or result["updated"]:
                state.update({"meet_id": meet.pk, "people_uploaded": True})
                _set_wizard_state(request, state)
            teacher_form = forms.TeacherUploadForm()
        else:
            summary["teachers"] = {"errors": teacher_form.errors.get("file")}
    return _render_wizard_people(
        request,
        student_form=student_form,
        teacher_form=teacher_form,
        summary=summary,
    )


def meet_wizard_event_preview(request: HttpRequest) -> HttpResponse:
    """Return a preview of the marshal UI for the proposed event."""

    meet = _get_wizard_meet(request)
    if not meet:
        return HttpResponseBadRequest("Create the meet basics first.")
    teacher_qs = models.Teacher.objects.order_by("last_name", "first_name")
    form = forms.EventConfigForm(request.POST or None, teacher_queryset=teacher_qs)
    if not form.is_valid():
        return render(
            request,
            "sportsday/partials/wizard_event_preview.html",
            {"form": form, "errors": form.errors, "event": None},
        )
    data = form.cleaned_data
    sport_type = data["sport_type"]
    attempts = data.get("attempts") or sport_type.default_attempts
    if sport_type.archetype == models.SportType.Archetype.TRACK_TIME:
        attempts = 1
    measure_unit = data.get("measure_unit") or sport_type.default_unit
    rounds_total = data.get("rounds_total") or 1
    attempts_list = list(range(1, attempts + 1))
    preview = SimpleNamespace(
        name=data.get("name") or sport_type.label,
        sport_type=sport_type,
        measure_unit=measure_unit,
        attempts=attempts,
        rounds_total=rounds_total,
    )
    return render(
        request,
        "sportsday/partials/wizard_event_preview.html",
        {"event": preview, "form": form, "attempt_numbers": attempts_list},
    )


def meet_wizard_scoring_preview(request: HttpRequest) -> HttpResponse:
    """Render a lightweight preview of scoring values."""

    form = forms.MeetBasicsForm(request.GET or None)
    points, participation = _resolve_scoring_preview(form)
    context = {"points_csv": points, "participation_point": participation}
    return render(request, "sportsday/partials/wizard_scoring_preview.html", context)


def meet_slugify(request: HttpRequest) -> HttpResponse:
    """Return a slugified version of the provided meet name."""

    name = request.GET.get("name", "")
    candidate = slugify(name) or "meet"
    base = candidate
    index = 2
    while models.Meet.objects.filter(slug=candidate).exists():
        candidate = f"{base}-{index}"
        index += 1
    return render(
        request,
        "sportsday/partials/wizard_slug_field.html",
        {"value": candidate, "errors": []},
    )


def meet_wizard_download_template(request: HttpRequest, kind: str) -> HttpResponse:
    """Serve CSV templates for bulk imports."""

    if kind == "students":
        content = "first_name,last_name,dob,grade,house,gender,external_id\n"
        filename = "students_template.csv"
    elif kind == "teachers":
        content = "first_name,last_name,email,external_id\n"
        filename = "teachers_template.csv"
    else:
        return HttpResponseBadRequest("Unknown template type")
    response = HttpResponse(content, content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _import_students(upload) -> dict[str, object]:
    created = updated = 0
    errors: list[str] = []
    try:
        data = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        upload.seek(0)
        data = upload.read().decode("latin-1")
    reader = csv.DictReader(io.StringIO(data))
    required = {"first_name", "last_name", "dob", "grade", "house", "gender"}
    for line_number, row in enumerate(reader, start=2):
        if not any(row.values()):
            continue
        missing = [field for field in required if not (row.get(field) or "").strip()]
        if missing:
            errors.append(f"Row {line_number}: missing fields {', '.join(missing)}")
            continue
        dob = _parse_date(row.get("dob", ""))
        if not dob:
            errors.append(f"Row {line_number}: invalid date '{row.get('dob')}'")
            continue
        external_id = (row.get("external_id") or "").strip()
        first = row.get("first_name", "").strip()
        last = row.get("last_name", "").strip()
        grade = row.get("grade", "").strip()
        house = row.get("house", "").strip()
        gender = row.get("gender", "").strip()
        lookup = models.Student.objects.all()
        student = None
        if external_id:
            student = lookup.filter(external_id=external_id).first()
        if student is None:
            lower = dob - timedelta(days=3)
            upper = dob + timedelta(days=3)
            student = (
                lookup.filter(
                    first_name__iexact=first,
                    last_name__iexact=last,
                    dob__range=(lower, upper),
                ).first()
            )
        if student:
            student.first_name = first
            student.last_name = last
            student.dob = dob
            student.grade = grade
            student.house = house
            student.gender = gender
            student.external_id = external_id
            student.save()
            updated += 1
        else:
            models.Student.objects.create(
                first_name=first,
                last_name=last,
                dob=dob,
                grade=grade,
                house=house,
                gender=gender,
                external_id=external_id,
            )
            created += 1
    upload.close()
    return {"created": created, "updated": updated, "errors": errors, "details": []}


def _import_teachers(upload) -> dict[str, object]:
    created = updated = 0
    errors: list[str] = []
    try:
        data = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        upload.seek(0)
        data = upload.read().decode("latin-1")
    reader = csv.DictReader(io.StringIO(data))
    required = {"first_name", "last_name"}
    for line_number, row in enumerate(reader, start=2):
        if not any(row.values()):
            continue
        missing = [field for field in required if not (row.get(field) or "").strip()]
        if missing:
            errors.append(f"Row {line_number}: missing fields {', '.join(missing)}")
            continue
        external_id = (row.get("external_id") or "").strip()
        first = row.get("first_name", "").strip()
        last = row.get("last_name", "").strip()
        email = (row.get("email") or "").strip()
        lookup = models.Teacher.objects.all()
        teacher = None
        if external_id:
            teacher = lookup.filter(external_id=external_id).first()
        if teacher is None and email:
            teacher = lookup.filter(
                first_name__iexact=first,
                last_name__iexact=last,
                email__iexact=email,
            ).first()
        if teacher:
            teacher.first_name = first
            teacher.last_name = last
            teacher.email = email
            teacher.external_id = external_id
            teacher.save()
            updated += 1
        else:
            models.Teacher.objects.create(
                first_name=first,
                last_name=last,
                email=email,
                external_id=external_id,
            )
            created += 1
    upload.close()
    return {"created": created, "updated": updated, "errors": errors}


def _parse_date(value: str) -> datetime.date | None:
    value = (value or "").strip()
    if not value:
        return None
    formats = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def meet_detail(request: HttpRequest, slug: str) -> HttpResponse:
    """Meet hub with schedule cards and quick links."""

    meet = get_object_or_404(models.Meet.objects.prefetch_related("events", "events__assigned_teachers"), slug=slug)
    highlight_event = meet.events.order_by("schedule_dt", "name").first()
    mobile_nav, mobile_nav_active = _build_meet_mobile_nav(meet, active="start")
    entries_total = models.Entry.objects.filter(event__meet=meet).count()
    students_total = meet.participating_students().count()
    scoring_rule = meet.scoring_rules.first()

    context = {
        "meet": meet,
        "highlight_event": highlight_event.pk if highlight_event else None,
        "mobile_nav": mobile_nav,
        "mobile_nav_active": mobile_nav_active,
        "active_meet": meet,
        "events_count": meet.events.count(),
        "entries_total": entries_total,
        "students_total": students_total,
        "scoring_rule": scoring_rule,
    }
    return render(request, "sportsday/meet_detail.html", context)


def meet_schedule_fragment(request: HttpRequest, slug: str) -> HttpResponse:
    """HTMX fragment summarising the meet schedule."""

    meet = get_object_or_404(models.Meet.objects.prefetch_related("events", "events__assigned_teachers"), slug=slug)
    events = list(meet.events.select_related("sport_type").order_by("schedule_dt", "name"))
    teachers_assigned = models.Teacher.objects.filter(events__meet=meet).distinct().count()

    def bucket(event: models.Event) -> str:
        if event.schedule_dt:
            hour = event.schedule_dt.time().hour
            if hour < 12:
                return "Morning"
            if hour < 16:
                return "Afternoon"
            return "Final session"
        return "Unscheduled"

    grouped: dict[str, list[models.Event]] = defaultdict(list)
    for event in events:
        grouped[bucket(event)].append(event)

    schedule_blocks = []
    for label in ["Morning", "Afternoon", "Final session", "Unscheduled"]:
        block_events = grouped.get(label, [])
        if not block_events and label != "Unscheduled":
            continue
        window = "To be announced"
        if block_events and block_events[0].schedule_dt:
            first_time = min(e.schedule_dt.time() for e in block_events if e.schedule_dt)
            last_time = max(e.schedule_dt.time() for e in block_events if e.schedule_dt)
            window = f"{first_time.strftime('%H:%M')} – {last_time.strftime('%H:%M')}"
        schedule_blocks.append(
            {
                "title": label,
                "window": window,
                "events": [
                    {
                        "name": e.name,
                        "time": e.schedule_dt.strftime("%H:%M") if e.schedule_dt else "TBC",
                    }
                    for e in block_events
                ],
            }
        )

    return render(
        request,
        "sportsday/partials/meet_schedule.html",
        {
            "meet": meet,
            "schedule_blocks": schedule_blocks,
            "teachers_assigned": teachers_assigned,
        },
    )


def meet_people_fragment(request: HttpRequest, slug: str) -> HttpResponse:
    """HTMX fragment showing staff allocations."""

    meet = get_object_or_404(models.Meet, slug=slug)
    teachers = (
        models.Teacher.objects.filter(events__meet=meet)
        .order_by("last_name", "first_name")
        .distinct()
    )
    teacher_assignments = []
    for teacher in teachers:
        events = list(teacher.events.filter(meet=meet).order_by("schedule_dt", "name"))
        if events:
            label = ", ".join(e.name for e in events[:3])
            if len(events) > 3:
                label += f" +{len(events) - 3}"
        else:
            label = "Awaiting assignment"
        teacher_assignments.append(
            {
                "name": str(teacher),
                "events": len(events),
                "events_label": label,
            }
        )

    return render(
        request,
        "sportsday/partials/meet_people.html",
        {
            "teacher_assignments": teacher_assignments,
            "volunteer_count": 0,
        },
    )


@require_POST
def meet_toggle_lock(request: HttpRequest, slug: str) -> HttpResponse:
    """Lock or unlock a meet via a quick action toggle."""

    meet = get_object_or_404(models.Meet, slug=slug)
    action = request.POST.get("action", "lock")
    meet.is_locked = action != "unlock"
    meet.save(update_fields=["is_locked"])
    redirect_url = reverse("sportsday:meet-detail", kwargs={"slug": slug})
    if request.headers.get("HX-Request"):
        response = HttpResponse(status=204)
        response["HX-Redirect"] = redirect_url
        return response
    return redirect(redirect_url)


@staff_member_required
def events_generate(request: HttpRequest, slug: str) -> HttpResponse:
    """Bulk generate events for a meet using grade/gender divisions."""

    meet = get_object_or_404(models.Meet, slug=slug)
    grade_options = list(
        models.Student.objects.values_list("grade", flat=True).distinct().order_by("grade")
    )
    form = forms.EventGenerationForm(request.POST or None, grades=grade_options)
    summary: dict[str, object] | None = None
    generated: list[models.Event] = []

    if request.method == "POST" and form.is_valid():
        cleaned = form.cleaned_data
        summary = services.generate_events(
            meet=meet,
            sport_types=list(cleaned["sport_types"]),
            grades=cleaned["grades"],
            genders=cleaned["genders"],
            name_pattern=cleaned["name_pattern"],
            capacity_override=cleaned.get("capacity_override"),
            attempts_override=cleaned.get("attempts_override"),
            rounds_total=cleaned.get("rounds_total") or 1,
        )
        generated = summary.get("events", [])
        form = forms.EventGenerationForm(grades=grade_options)

    context = {
        "meet": meet,
        "form": form,
        "summary": summary,
        "generated_events": generated,
        "active_meet": meet,
    }
    return render(request, "sportsday/events_generate.html", context)


@staff_member_required
def entries_bulk(request: HttpRequest, slug: str) -> HttpResponse:
    """Bulk assign entries to events within a meet."""

    meet = get_object_or_404(models.Meet, slug=slug)
    form = forms.BulkEntryAssignmentForm(
        request.POST or None, request.FILES or None, meet=meet
    )
    summary: dict[str, object] | None = None

    if request.method == "POST" and form.is_valid():
        mode = form.cleaned_data["mode"]
        if mode == forms.BulkEntryAssignmentForm.MODE_CSV:
            summary = _bulk_assign_entries_from_csv(meet, form.cleaned_data["csv_file"])
        else:
            summary = _bulk_assign_entries_from_rules(meet, form.cleaned_data["events"])
        form = forms.BulkEntryAssignmentForm(meet=meet)

    context = {
        "meet": meet,
        "form": form,
        "summary": summary,
        "active_meet": meet,
    }
    return render(request, "sportsday/entries_bulk.html", context)


def _bulk_assign_entries_from_csv(meet: models.Meet, upload) -> dict[str, object]:
    created = updated = 0
    errors: list[str] = []
    try:
        data = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        upload.seek(0)
        data = upload.read().decode("latin-1")
    reader = csv.DictReader(io.StringIO(data))
    if not reader.fieldnames:
        errors.append("CSV file has no headers.")
        return {"created": 0, "updated": 0, "errors": errors}
    required = {"student_external_id"}
    missing_headers = required - set(field.strip() for field in reader.fieldnames if field)
    if missing_headers:
        errors.append(f"Missing columns: {', '.join(sorted(missing_headers))}")
        return {"created": 0, "updated": 0, "errors": errors}
    for line_number, row in enumerate(reader, start=2):
        if not any(row.values()):
            continue
        external_id = (row.get("student_external_id") or "").strip()
        if not external_id:
            errors.append(f"Row {line_number}: student_external_id is required")
            continue
        student = models.Student.objects.filter(external_id=external_id).first()
        if not student:
            errors.append(f"Row {line_number}: no student with external_id '{external_id}'")
            continue
        event = _resolve_event_for_csv(meet, row)
        if not event:
            errors.append(f"Row {line_number}: event could not be found")
            continue
        round_value = (row.get("round_no") or "1").strip() or "1"
        heat_value = (row.get("heat") or "1").strip() or "1"
        try:
            round_no = int(round_value)
            heat = int(heat_value)
        except ValueError:
            errors.append(f"Row {line_number}: invalid round or heat value")
            continue
        lane_value = row.get("lane_or_order")
        lane: int | None
        if lane_value in (None, ""):
            lane = None
        else:
            try:
                lane = int(lane_value)
            except ValueError:
                errors.append(f"Row {line_number}: invalid lane_or_order '{lane_value}'")
                continue
        entry = models.Entry.objects.filter(event=event, student=student, round_no=round_no).first()
        created_flag = False
        if entry is None:
            entry = models.Entry(event=event, student=student, round_no=round_no)
            created_flag = True
        entry.heat = heat
        entry.lane_or_order = lane
        try:
            entry.save()
        except ValidationError as exc:
            errors.append(f"Row {line_number}: {'; '.join(exc.messages)}")
            continue
        if created_flag:
            created += 1
        else:
            updated += 1
    upload.close()
    return {"created": created, "updated": updated, "errors": errors}


def _resolve_event_for_csv(meet: models.Meet, row: dict[str, str]) -> models.Event | None:
    event_id = (row.get("event_id") or "").strip()
    event_name = (row.get("event_name") or "").strip()
    event = None
    if event_id:
        try:
            event = meet.events.get(pk=int(event_id))
        except (ValueError, models.Event.DoesNotExist):
            event = None
    if event is None and event_name:
        event = meet.events.filter(name__iexact=event_name).first()
    return event


def _bulk_assign_entries_from_rules(
    meet: models.Meet, events: Iterable[models.Event]
) -> dict[str, object]:
    events = list(events)
    summary = {"created": 0, "errors": [], "details": [], "updated": None}
    if not events:
        return summary

    student_counts = defaultdict(int)
    for row in (
        models.Entry.objects.filter(event__meet=meet)
        .values("student")
        .annotate(total=Count("id"))
    ):
        student_counts[row["student"]] = row["total"]

    students = list(
        models.Student.objects.filter(is_active=True).order_by("house", "last_name", "first_name")
    )
    meet_limit = meet.max_events_per_student or 0

    for event in events:
        event = models.Event.objects.select_related("sport_type", "meet").get(pk=event.pk)
        event_entries = list(event.entries.select_related("student"))
        house_counts = defaultdict(int)
        existing_student_ids = set()
        for entry in event_entries:
            existing_student_ids.add(entry.student_id)
            house_counts[entry.student.house or "Unassigned"] += 1
        capacity = event.capacity or 0
        slots = max(capacity - len(event_entries), 0)
        if slots <= 0:
            summary["details"].append({"event": event, "assigned": []})
            continue
        candidates: list[models.Student] = []
        for student in students:
            if student.pk in existing_student_ids:
                continue
            if not event.grade_allows(student.grade):
                continue
            if not event.gender_allows(student.gender):
                continue
            if meet_limit and student_counts.get(student.pk, 0) >= meet_limit:
                continue
            if services.compute_timetable_clashes(student=student, event=event):
                continue
            candidates.append(student)
        buckets: dict[str, list[models.Student]] = defaultdict(list)
        for student in candidates:
            buckets[student.house or "Unassigned"].append(student)
        for bucket in buckets.values():
            bucket.sort(key=lambda s: (student_counts.get(s.pk, 0), s.last_name, s.first_name))

        assigned: list[models.Student] = []
        while slots and any(buckets.values()):
            available = [house for house, bucket in buckets.items() if bucket]
            if not available:
                break
            chosen_house = min(available, key=lambda h: (house_counts.get(h, 0), h))
            student = buckets[chosen_house].pop(0)
            entry = models.Entry(event=event, student=student, round_no=1, heat=1)
            try:
                entry.save()
            except ValidationError as exc:
                summary["errors"].append(
                    f"{event.name}: {student} – {'; '.join(exc.messages)}"
                )
                continue
            house_counts[chosen_house] += 1
            student_counts[student.pk] = student_counts.get(student.pk, 0) + 1
            assigned.append(student)
            summary["created"] += 1
            slots -= 1
        summary["details"].append({"event": event, "assigned": assigned})
    return summary


def students_upload(request: HttpRequest) -> HttpResponse:
    """Allow coordinators to re-upload student CSVs or add individuals."""

    upload_form = forms.StudentUploadForm()
    student_form = forms.StudentForm()
    upload_summary: dict[str, object] | None = None
    created_student: models.Student | None = None

    if request.method == "POST":
        form_type = request.POST.get("form_type", "upload")
        if form_type == "add":
            student_form = forms.StudentForm(request.POST)
            if student_form.is_valid():
                created_student = student_form.save()
                student_form = forms.StudentForm()
        else:
            upload_form = forms.StudentUploadForm(request.POST, request.FILES)
            if upload_form.is_valid():
                upload_summary = _import_students(upload_form.cleaned_data["file"])
                upload_form = forms.StudentUploadForm()

    context = {
        "upload_form": upload_form,
        "student_form": student_form,
        "upload_summary": upload_summary,
        "created_student": created_student,
    }
    return render(request, "sportsday/students_upload.html", context)


def teachers_upload(request: HttpRequest) -> HttpResponse:
    """Allow coordinators to re-upload teacher CSVs or add individuals."""

    upload_form = forms.TeacherUploadForm()
    teacher_form = forms.TeacherForm()
    upload_summary: dict[str, object] | None = None
    created_teacher: models.Teacher | None = None

    if request.method == "POST":
        form_type = request.POST.get("form_type", "upload")
        if form_type == "add":
            teacher_form = forms.TeacherForm(request.POST)
            if teacher_form.is_valid():
                created_teacher = teacher_form.save()
                teacher_form = forms.TeacherForm()
        else:
            upload_form = forms.TeacherUploadForm(request.POST, request.FILES)
            if upload_form.is_valid():
                upload_summary = _import_teachers(upload_form.cleaned_data["file"])
                upload_form = forms.TeacherUploadForm()

    context = {
        "upload_form": upload_form,
        "teacher_form": teacher_form,
        "upload_summary": upload_summary,
        "created_teacher": created_teacher,
    }
    return render(request, "sportsday/teachers_upload.html", context)


def student_list(request: HttpRequest) -> HttpResponse:
    """Directory of students with event tallies."""

    meet_options = models.Meet.objects.order_by("name")
    houses = models.Student.objects.values_list("house", flat=True).distinct().order_by("house")
    filters = _student_filters(request)
    meet_slug = filters.get("meet")
    active_meet = models.Meet.objects.filter(slug=meet_slug).first() if meet_slug else None
    mobile_nav = mobile_nav_active = None
    if active_meet:
        mobile_nav, mobile_nav_active = _build_meet_mobile_nav(active_meet, active="students")

    context = {
        "meet_options": meet_options,
        "houses": houses,
        "active_meet": active_meet,
        "mobile_nav": mobile_nav,
        "mobile_nav_active": mobile_nav_active,
        "query_params": _student_filter_query(filters),
    }
    return render(request, "sportsday/students_list.html", context)


def students_table_fragment(request: HttpRequest) -> HttpResponse:
    """HTMX table of students respecting filters."""

    filters = _student_filters(request)
    students = _students_queryset(filters)
    filters_context = filters.copy()
    filters_context["query_string"] = _student_filter_query(filters)

    return render(
        request,
        "sportsday/partials/students_table.html",
        {"students": students, "filters": filters_context},
    )


@staff_member_required
def student_edit(request: HttpRequest, student_id: int) -> HttpResponse:
    """Edit an existing student record."""

    student = get_object_or_404(models.Student, pk=student_id)
    filters = _student_filters(request)
    filters_context = filters.copy()
    filters_context["query_string"] = _student_filter_query(filters)
    return_url = _students_redirect_url(filters)

    if request.method == "POST":
        form = forms.StudentForm(request.POST, instance=student)
        if form.is_valid():
            updated_student = form.save()
            messages.success(request, f"Updated {updated_student.first_name} {updated_student.last_name}.")
            return redirect(return_url)
    else:
        form = forms.StudentForm(instance=student)

    active_meet = None
    if filters.get("meet"):
        active_meet = models.Meet.objects.filter(slug=filters["meet"]).first()
    mobile_nav = mobile_nav_active = None
    if active_meet:
        mobile_nav, mobile_nav_active = _build_meet_mobile_nav(active_meet, active="students")

    context = {
        "form": form,
        "student": student,
        "filters": filters_context,
        "return_url": return_url,
        "active_meet": active_meet,
        "mobile_nav": mobile_nav,
        "mobile_nav_active": mobile_nav_active,
    }
    return render(request, "sportsday/student_form.html", context)


@staff_member_required
@require_POST
def student_delete(request: HttpRequest, student_id: int) -> HttpResponse:
    """Remove a student and refresh the table when requested via HTMX."""

    student = get_object_or_404(models.Student, pk=student_id)
    filters = _student_filters(request)
    student_name = str(student)
    student.delete()

    if request.headers.get("HX-Request"):
        filters_context = filters.copy()
        filters_context["query_string"] = _student_filter_query(filters)
        students = _students_queryset(filters)
        return render(
            request,
            "sportsday/partials/students_table.html",
            {"students": students, "filters": filters_context},
        )

    messages.success(request, f"Deleted {student_name}.")
    return redirect(_students_redirect_url(filters))


def teacher_list(request: HttpRequest) -> HttpResponse:
    """List teachers and provide import actions."""

    context = {
        "active_meet": None,
    }
    return render(request, "sportsday/teachers_list.html", context)


def teachers_table_fragment(request: HttpRequest) -> HttpResponse:
    """HTMX table of teachers with assignment counts."""

    teachers = (
        models.Teacher.objects.annotate(assignment_count=Count("events", distinct=True))
        .order_by("last_name", "first_name")
    )
    return render(request, "sportsday/partials/teachers_table.html", {"teachers": teachers})


def event_list(request: HttpRequest) -> HttpResponse:
    """List events for a meet with management shortcuts."""

    meet_options = models.Meet.objects.order_by("name")
    meet_slug = request.GET.get("meet")
    if not meet_slug and meet_options.exists():
        meet_slug = meet_options.first().slug
    active_meet = models.Meet.objects.filter(slug=meet_slug).first() if meet_slug else None

    events = models.Event.objects.none()
    query = request.GET.get("q")
    if active_meet:
        events = (
            models.Event.objects.filter(meet=active_meet)
            .select_related("sport_type", "meet")
            .prefetch_related("assigned_teachers")
            .annotate(entries_total=Count("entries", distinct=True))
            .order_by("schedule_dt", "name")
        )
        if query:
            events = events.filter(
                Q(name__icontains=query)
                | Q(sport_type__label__icontains=query)
                | Q(grade_min__icontains=query)
                | Q(grade_max__icontains=query)
            )
        if not request.user.is_staff:
            teacher = _teacher_for_user(request.user)
            if teacher:
                events = events.filter(assigned_teachers=teacher)
            else:
                events = events.none()

    mobile_nav = mobile_nav_active = None
    if active_meet:
        mobile_nav, mobile_nav_active = _build_meet_mobile_nav(active_meet, active="results")

    context = {
        "events": events,
        "meet_options": meet_options,
        "active_meet": active_meet,
        "mobile_nav": mobile_nav,
        "mobile_nav_active": mobile_nav_active,
    }

    return render(request, "sportsday/events_list.html", context)


def _build_event_group(events: Iterable[models.Event], meet: models.Meet | None) -> dict[str, object]:
    """Create a table group for a sequence of events on the same day."""

    events = list(events)
    if not events:
        return {"label": "", "subtitle": "", "events": []}
    start = min(event.schedule_dt for event in events if event.schedule_dt)
    end = max(event.schedule_dt for event in events if event.schedule_dt)
    subtitle = f"{start.strftime('%H:%M')} – {end.strftime('%H:%M')}"
    if meet and meet.location:
        subtitle = f"{meet.location} · {subtitle}"
    return {
        "label": start.strftime("%A %d %B"),
        "subtitle": subtitle,
        "events": events,
    }


def events_table_fragment(request: HttpRequest) -> HttpResponse:
    """Lightweight event cards used in the wizard preview."""

    meet_slug = request.GET.get("meet")
    events = models.Event.objects.select_related("sport_type", "meet")
    if meet_slug:
        events = events.filter(meet__slug=meet_slug)
    events = events.order_by("schedule_dt", "name")[:10]
    return render(request, "sportsday/partials/events_table.html", {"events": events})


def event_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Detailed controls for a single event."""

    event = get_object_or_404(models.Event.objects.select_related("meet", "sport_type"), pk=pk)
    mobile_nav, mobile_nav_active = _build_event_mobile_nav(event, active="start")

    context = {
        "event": event,
        "active_meet": event.meet,
        "mobile_nav": mobile_nav,
        "mobile_nav_active": mobile_nav_active,
    }
    return render(request, "sportsday/event_detail.html", context)


@require_POST
def event_toggle_lock(request: HttpRequest, pk: int) -> HttpResponse:
    """Lock or unlock an individual event."""

    event = get_object_or_404(models.Event.objects.select_related("meet"), pk=pk)
    action = request.POST.get("action", "lock")
    if event.meet.is_locked and action != "unlock":
        return HttpResponseBadRequest("Unlock the meet before changing event locks.")
    event.is_locked = action != "unlock"
    event.save(update_fields=["is_locked"])
    redirect_url = reverse("sportsday:event-detail", kwargs={"pk": pk})
    if request.headers.get("HX-Request"):
        response = HttpResponse(status=204)
        response["HX-Redirect"] = redirect_url
        return response
    return redirect(redirect_url)


def _determine_active_round(request: HttpRequest, event: models.Event) -> int:
    """Return the round number being managed for the start list."""

    raw_value = request.GET.get("round") or request.POST.get("round_no") or 1
    try:
        round_no = int(raw_value)
    except (TypeError, ValueError):
        round_no = 1
    return max(1, min(round_no, event.rounds_total))


def _determine_active_heat(request: HttpRequest, event: models.Event, round_no: int) -> int | None:
    """Return the active heat for the event results view."""

    if event.sport_type.archetype != models.SportType.Archetype.TRACK_TIME:
        return None
    if not event.sport_type.supports_heats:
        return None
    heat_raw = request.GET.get("heat") or request.POST.get("heat")
    if heat_raw is None:
        heat_raw = 1
    try:
        heat = int(heat_raw)
    except (TypeError, ValueError):
        heat = 1
    min_heat = event.entries.filter(round_no=round_no).aggregate(min_heat=Min("heat"))[
        "min_heat"
    ]
    max_heat = event.entries.filter(round_no=round_no).aggregate(max_heat=Max("heat"))[
        "max_heat"
    ]
    if min_heat is None or max_heat is None:
        return 1
    return max(min_heat, min(max_heat, heat))


def _result_form_factory(event: models.Event, field_size: int) -> tuple[type[forms.BaseResultForm], dict[str, object]]:
    archetype = event.sport_type.archetype
    if archetype == models.SportType.Archetype.TRACK_TIME:
        return forms.TrackResultForm, {}
    if archetype == models.SportType.Archetype.FIELD_DISTANCE:
        return forms.FieldDistanceResultForm, {"attempts": event.attempts}
    if archetype == models.SportType.Archetype.FIELD_COUNT:
        return forms.FieldCountResultForm, {}
    if archetype == models.SportType.Archetype.RANK_ONLY:
        return forms.RankOnlyResultForm, {"field_size": field_size}
    raise ValueError("Unsupported sport type")


def _serialize_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def _entry_payload_from_attempts(event: models.Event, entry: models.Entry) -> dict[str, object]:
    archetype = event.sport_type.archetype
    status = entry.status
    payload: dict[str, object] = {
        "entry": entry,
        "status": status,
        "rank": getattr(getattr(entry, "result", None), "rank", None),
        "best_value": None,
        "series": [],
        "tiebreak": {},
    }
    attempts = list(entry.attempts.all())

    if archetype == models.SportType.Archetype.TRACK_TIME:
        attempt = next((item for item in attempts if item.attempt_no == 1), None)
        value = attempt.time_seconds if attempt else None
        if status != models.Entry.Status.CONFIRMED:
            value = None
        payload["best_value"] = value
        payload["series"] = [value] if value is not None else []
        payload["tiebreak"] = {"time": _serialize_decimal(value)} if value is not None else {}
    elif archetype == models.SportType.Archetype.FIELD_DISTANCE:
        marks = []
        for attempt in attempts:
            mark = attempt.distance_m if attempt.valid else None
            marks.append(mark)
        valid_marks = [mark for mark in marks if mark is not None]
        best_value = max(valid_marks) if valid_marks else None
        if status != models.Entry.Status.CONFIRMED:
            best_value = None
        payload["best_value"] = best_value
        payload["series"] = sorted(valid_marks, reverse=True)
        payload["tiebreak"] = {
            "attempts": [_serialize_decimal(mark) if mark is not None else None for mark in marks]
        }
    elif archetype == models.SportType.Archetype.FIELD_COUNT:
        attempt = next((item for item in attempts if item.attempt_no == 1), None)
        count_value = Decimal(attempt.count) if attempt and attempt.count is not None else None
        if status != models.Entry.Status.CONFIRMED:
            count_value = None
        payload["best_value"] = count_value
        payload["series"] = [count_value] if count_value is not None else []
        payload["tiebreak"] = {}
    elif archetype == models.SportType.Archetype.RANK_ONLY:
        rank = payload["rank"]
        payload["best_value"] = Decimal(rank) if rank is not None else None
        attempt = next((item for item in attempts if item.attempt_no == 1), None)
        if attempt and attempt.time_seconds is not None:
            payload["tiebreak"] = {"time": _serialize_decimal(attempt.time_seconds)}
        else:
            payload["tiebreak"] = {}
    return payload


def _build_payload_from_form(event: models.Event, form: forms.BaseResultForm) -> dict[str, object]:
    archetype = event.sport_type.archetype
    cleaned = form.cleaned_data
    payload = {
        "entry": form.entry,
        "status": cleaned.get("status"),
        "best_value": None,
        "rank": None,
        "series": [],
        "tiebreak": {},
    }
    status = payload["status"]
    if status != models.Entry.Status.CONFIRMED:
        return payload

    if archetype == models.SportType.Archetype.TRACK_TIME:
        time_value = cleaned.get("time_display")
        payload["best_value"] = time_value
        payload["series"] = [time_value] if time_value is not None else []
        payload["attempts"] = [{"attempt_no": 1, "time": time_value}]
        payload["tiebreak"] = {"time": _serialize_decimal(time_value)} if time_value is not None else {}
    elif archetype == models.SportType.Archetype.FIELD_DISTANCE:
        attempts = cleaned.get("attempts", [])
        payload["attempts"] = attempts
        marks = [item["value"] if item.get("valid") else None for item in attempts]
        valid_marks = [mark for mark in marks if mark is not None]
        best = max(valid_marks) if valid_marks else None
        payload["best_value"] = best
        payload["series"] = sorted(valid_marks, reverse=True)
        payload["tiebreak"] = {
            "attempts": [_serialize_decimal(mark) if mark is not None else None for mark in marks]
        }
    elif archetype == models.SportType.Archetype.FIELD_COUNT:
        count_value = cleaned.get("count")
        best_value = Decimal(count_value) if count_value is not None else None
        payload["best_value"] = best_value
        payload["series"] = [best_value] if best_value is not None else []
        payload["attempts"] = [{"attempt_no": 1, "count": count_value}]
    elif archetype == models.SportType.Archetype.RANK_ONLY:
        rank = cleaned.get("rank")
        if rank is None:
            raise ValueError("Provide a rank for each confirmed competitor.")
        payload["rank"] = rank
        payload["best_value"] = Decimal(rank)
        time_value = cleaned.get("time_display")
        payload["attempts"] = [{"attempt_no": 1, "time": time_value}] if time_value is not None else []
        payload["tiebreak"] = {"time": _serialize_decimal(time_value)} if time_value is not None else {}
    return payload


def _persist_entry_payload(event: models.Event, payload: dict[str, object], finalize: bool) -> None:
    entry: models.Entry = payload["entry"]
    status = payload.get("status")
    entry.status = status
    entry.save(update_fields=["status"])

    archetype = event.sport_type.archetype
    if status != models.Entry.Status.CONFIRMED:
        entry.attempts.all().delete()
        result, _ = models.Result.objects.get_or_create(entry=entry)
        result.best_value = None
        if archetype == models.SportType.Archetype.RANK_ONLY:
            result.rank = None
        else:
            result.rank = None
        result.tiebreak = {}
        result.finalized = finalize or result.finalized
        result.save()
        return

    if archetype == models.SportType.Archetype.TRACK_TIME:
        time_value: Decimal | None = payload.get("best_value")
        if time_value is not None:
            attempt, _ = models.Attempt.objects.get_or_create(entry=entry, attempt_no=1)
            attempt.time_seconds = time_value
            attempt.distance_m = None
            attempt.count = None
            attempt.valid = True
            attempt.save()
        else:
            entry.attempts.filter(attempt_no=1).delete()
    elif archetype == models.SportType.Archetype.FIELD_DISTANCE:
        attempts = payload.get("attempts", [])
        seen = []
        for attempt_data in attempts:
            attempt_no = attempt_data["attempt_no"]
            seen.append(attempt_no)
            attempt_obj, _ = models.Attempt.objects.get_or_create(entry=entry, attempt_no=attempt_no)
            value = attempt_data.get("value")
            valid = bool(attempt_data.get("valid"))
            attempt_obj.time_seconds = None
            attempt_obj.count = None
            attempt_obj.valid = valid
            attempt_obj.distance_m = value if valid and value is not None else None
            attempt_obj.save()
        entry.attempts.exclude(attempt_no__in=seen).delete()
    elif archetype == models.SportType.Archetype.FIELD_COUNT:
        attempts = payload.get("attempts", [])
        count_value = attempts[0].get("count") if attempts else None
        if count_value is not None:
            attempt, _ = models.Attempt.objects.get_or_create(entry=entry, attempt_no=1)
            attempt.count = int(count_value)
            attempt.time_seconds = None
            attempt.distance_m = None
            attempt.valid = True
            attempt.save()
        else:
            entry.attempts.filter(attempt_no=1).delete()
    elif archetype == models.SportType.Archetype.RANK_ONLY:
        attempts = payload.get("attempts", [])
        time_value = attempts[0].get("time") if attempts else None
        if time_value is not None:
            attempt, _ = models.Attempt.objects.get_or_create(entry=entry, attempt_no=1)
            attempt.time_seconds = time_value
            attempt.distance_m = None
            attempt.count = None
            attempt.valid = True
            attempt.save()
        else:
            entry.attempts.filter(attempt_no=1).delete()

    result, _ = models.Result.objects.get_or_create(entry=entry)
    if archetype != models.SportType.Archetype.RANK_ONLY:
        result.best_value = payload.get("best_value")
    else:
        result.best_value = payload.get("best_value")
        result.rank = payload.get("rank")
    if payload.get("rank") is not None:
        result.rank = payload.get("rank")
    result.tiebreak = payload.get("tiebreak", {})
    if finalize:
        result.finalized = True
    else:
        result.finalized = False
    result.save()


def _collect_round_payloads(event: models.Event, round_no: int) -> list[dict[str, object]]:
    attempts_prefetch = Prefetch("attempts", queryset=models.Attempt.objects.order_by("attempt_no"))
    entries = (
        event.entries.filter(round_no=round_no)
        .select_related("result")
        .prefetch_related(attempts_prefetch)
    )
    return [_entry_payload_from_attempts(event, entry) for entry in entries]


def _update_round_ranks(event: models.Event, round_no: int) -> None:
    payloads = _collect_round_payloads(event, round_no)
    archetype = event.sport_type.archetype
    if archetype == models.SportType.Archetype.TRACK_TIME:
        services.rank_track(payloads)
    elif archetype in (
        models.SportType.Archetype.FIELD_DISTANCE,
        models.SportType.Archetype.FIELD_COUNT,
    ):
        services.rank_field(payloads)

    for payload in payloads:
        entry = payload["entry"]
        result, _ = models.Result.objects.get_or_create(entry=entry)
        if archetype != models.SportType.Archetype.RANK_ONLY:
            result.rank = payload.get("rank")
            result.best_value = payload.get("best_value")
        result.tiebreak = payload.get("tiebreak", result.tiebreak)
        result.save()


def _message_for_action(action: str) -> str:
    return {
        "save": "Draft saved.",
        "validate": "Times validated and ranks updated.",
        "submit": "Round submitted.",
        "lock": "Event locked and results finalised.",
    }.get(action, "Results updated.")


def _log_result_submission(
    event: models.Event,
    action: str,
    round_no: int,
    heat: int | None,
    qualifiers: int,
) -> None:
    models.AuditLog.objects.create(
        action=f"event_results_{action}",
        payload={
            "event_id": event.pk,
            "event_name": event.name,
            "meet": event.meet.slug,
            "round": round_no,
            "heat": heat,
            "qualifiers_created": qualifiers,
        },
    )


def _process_results_submission(
    event: models.Event,
    round_no: int,
    heat: int | None,
    action: str,
    forms_list: list[forms.BaseResultForm],
) -> tuple[int, bool, str]:
    lock_reason = _event_lock_reason(event)
    if lock_reason:
        raise ValueError(lock_reason)
    payloads = [_build_payload_from_form(event, form) for form in forms_list]
    archetype = event.sport_type.archetype
    if archetype == models.SportType.Archetype.RANK_ONLY:
        ranks = [payload.get("rank") for payload in payloads if payload.get("status") == models.Entry.Status.CONFIRMED]
        ranks = [rank for rank in ranks if rank is not None]
        if len(ranks) != len(set(ranks)):
            raise ValueError("Ranks must be unique for this round.")

    finalize = action in {"submit", "lock"}
    with transaction.atomic():
        for payload in payloads:
            _persist_entry_payload(event, payload, finalize)
        _update_round_ranks(event, round_no)
        if action == "lock" and not event.is_locked:
            event.is_locked = True
            event.save(update_fields=["is_locked"])

    qualifiers_created = 0
    if (
        action in {"submit", "lock"}
        and archetype == models.SportType.Archetype.TRACK_TIME
        and round_no < event.rounds_total
    ):
        round_payloads = _collect_round_payloads(event, round_no)
        services.rank_track(round_payloads)
        qualifiers_created = len(services.apply_qualifiers(round_payloads, event.knockout_qualifiers))

    _log_result_submission(event, action, round_no, heat, qualifiers_created)
    return qualifiers_created, action != "validate", _message_for_action(action)


def _eligible_students_queryset(event: models.Event, search_query: str, round_no: int):
    """Return the queryset used in the add-to-start-list dropdown."""

    queryset = models.Student.objects.filter(is_active=True)
    if event.gender_limit != models.Event.GenderLimit.MIXED:
        queryset = queryset.filter(gender=event.gender_limit)
    if search_query:
        queryset = queryset.filter(
            Q(first_name__icontains=search_query)
            | Q(last_name__icontains=search_query)
            | Q(external_id__icontains=search_query)
        )
    assigned_ids = event.entries.filter(round_no=round_no).values_list("student_id", flat=True)
    queryset = queryset.exclude(pk__in=assigned_ids)
    return queryset.order_by("last_name", "first_name").distinct()


def _calculate_next_assignment(event: models.Event, round_no: int) -> tuple[int, int]:
    """Determine the heat and lane/order for the next entry."""

    capacity = max(event.capacity, 1)
    supports_heats = event.sport_type.supports_heats
    existing_count = event.entries.filter(round_no=round_no).count()
    if not supports_heats:
        heat = 1
        lane = existing_count + 1
    else:
        heat = existing_count // capacity + 1
        lane = existing_count % capacity + 1
    return heat, lane


def _apply_lane_assignments(event: models.Event, entries: list[models.Entry]) -> None:
    """Persist contiguous lane/order values for the provided entries."""

    capacity = max(event.capacity, 1)
    supports_heats = event.sport_type.supports_heats
    heat = 1
    lane = 1
    for entry in entries:
        if supports_heats:
            if lane > capacity:
                heat += 1
                lane = 1
            entry.heat = heat
        else:
            entry.heat = 1
        entry.lane_or_order = lane
        entry.save(update_fields=["heat", "lane_or_order"])
        lane += 1


def _render_event_start_list(
    request: HttpRequest,
    event: models.Event,
    *,
    round_no: int,
    search_query: str,
    form: forms.StartListAddForm | None = None,
    status: int = 200,
    locked_reason: str | None = None,
) -> HttpResponse:
    """Render the start list partial with the supplied configuration."""

    entries = (
        event.entries.select_related("student")
        .filter(round_no=round_no)
        .order_by("heat", "lane_or_order", "student__last_name", "student__first_name")
    )
    eligible_queryset = _eligible_students_queryset(event, search_query, round_no)
    if form is None:
        form = forms.StartListAddForm(event=event, queryset=eligible_queryset, initial_round=round_no)
    else:
        form.fields["student"].queryset = eligible_queryset
    if locked_reason:
        for field in form.fields.values():
            field.disabled = True
    student_widget = form.fields["student"].widget
    student_widget.attrs.setdefault(
        "class",
        "w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500",
    )
    round_widget = form.fields["round_no"].widget
    if not getattr(round_widget, "is_hidden", False):
        round_widget.attrs.setdefault(
            "class",
            "w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500",
        )
    round_options = [number for number in range(1, event.rounds_total + 1)]
    context = {
        "event": event,
        "entries": entries,
        "form": form,
        "round_options": round_options,
        "active_round": round_no,
        "search_query": search_query,
        "capacity": event.capacity,
        "supports_heats": event.sport_type.supports_heats,
        "locked_reason": locked_reason,
    }
    return render(request, "sportsday/partials/event_start_list.html", context, status=status)


def event_start_list_fragment(request: HttpRequest, pk: int) -> HttpResponse:
    """HTMX table for start lists."""

    event = get_object_or_404(models.Event.objects.select_related("sport_type"), pk=pk)
    round_no = _determine_active_round(request, event)
    search_query = request.GET.get("q", "")
    locked_reason = _event_lock_reason(event)
    return _render_event_start_list(
        request,
        event,
        round_no=round_no,
        search_query=search_query,
        locked_reason=locked_reason,
    )


def event_start_list_add(request: HttpRequest, pk: int) -> HttpResponse:
    """Add a student to the start list after eligibility checks."""

    event = get_object_or_404(models.Event.objects.select_related("sport_type", "meet"), pk=pk)
    round_no = _determine_active_round(request, event)
    search_query = request.POST.get("q", "")
    eligible_queryset = _eligible_students_queryset(event, search_query, round_no)
    form = forms.StartListAddForm(
        data=request.POST or None,
        event=event,
        queryset=eligible_queryset,
        initial_round=round_no,
    )
    locked_reason = _event_lock_reason(event)
    if locked_reason:
        form.add_error(None, locked_reason)
        return _render_event_start_list(
            request,
            event,
            round_no=round_no,
            search_query=search_query,
            form=form,
            status=LOCKED_STATUS_CODE,
            locked_reason=locked_reason,
        )
    if form.is_valid():
        student = form.cleaned_data["student"]
        round_no = form.cleaned_data["round_no"]
        if not event.sport_type.supports_heats and event.entries.filter(round_no=round_no).count() >= event.capacity:
            form.add_error("student", "This event is already at capacity for the selected round.")
        else:
            heat, lane = _calculate_next_assignment(event, round_no)
            models.Entry.objects.create(
                event=event,
                student=student,
                round_no=round_no,
                heat=heat,
                lane_or_order=lane,
            )
            return _render_event_start_list(
                request,
                event,
                round_no=round_no,
                search_query=search_query,
                locked_reason=_event_lock_reason(event),
            )

    return _render_event_start_list(
        request,
        event,
        round_no=round_no,
        search_query=search_query,
        form=form,
        status=400,
        locked_reason=_event_lock_reason(event),
    )


def event_start_list_remove(request: HttpRequest, pk: int, entry_id: int) -> HttpResponse:
    """Remove a student from the start list and resequence lanes."""

    event = get_object_or_404(models.Event.objects.select_related("sport_type"), pk=pk)
    round_no = _determine_active_round(request, event)
    search_query = request.POST.get("q", "")
    locked_reason = _event_lock_reason(event)
    if locked_reason:
        return _render_event_start_list(
            request,
            event,
            round_no=round_no,
            search_query=search_query,
            status=LOCKED_STATUS_CODE,
            locked_reason=locked_reason,
        )
    entry = get_object_or_404(models.Entry, pk=entry_id, event=event)
    round_no = entry.round_no
    entry.delete()
    remaining = list(
        event.entries.filter(round_no=round_no).order_by("heat", "lane_or_order", "pk")
    )
    _apply_lane_assignments(event, remaining)
    return _render_event_start_list(
        request,
        event,
        round_no=round_no,
        search_query=search_query,
        locked_reason=_event_lock_reason(event),
    )


def _extract_ordering(request: HttpRequest) -> list[int]:
    """Extract ordering IDs from sortable HTMX submissions."""

    for key in ("order[]", "entry[]", "entries[]", "sorting[]", "items[]"):
        values = request.POST.getlist(key)
        if values:
            return [int(value) for value in values if value.isdigit()]
    for key in request.POST:
        if key.endswith("[]"):
            values = request.POST.getlist(key)
            if values and all(value.isdigit() for value in values):
                return [int(value) for value in values]
    payload = request.POST.get("order")
    if payload:
        return [int(value) for value in payload.split(",") if value.strip().isdigit()]
    return []


def event_start_list_reorder(request: HttpRequest, pk: int) -> HttpResponse:
    """Persist drag-and-drop changes to the start list."""

    event = get_object_or_404(models.Event.objects.select_related("sport_type"), pk=pk)
    round_no = _determine_active_round(request, event)
    search_query = request.POST.get("q", "")
    ordered_ids = _extract_ordering(request)
    locked_reason = _event_lock_reason(event)
    if locked_reason:
        return _render_event_start_list(
            request,
            event,
            round_no=round_no,
            search_query=search_query,
            status=LOCKED_STATUS_CODE,
            locked_reason=locked_reason,
        )
    if not ordered_ids:
        return _render_event_start_list(
            request,
            event,
            round_no=round_no,
            search_query=search_query,
            locked_reason=None,
        )
    entries = list(models.Entry.objects.filter(event=event, round_no=round_no, pk__in=ordered_ids))
    entries.sort(key=lambda item: ordered_ids.index(item.pk))
    _apply_lane_assignments(event, entries)
    return _render_event_start_list(
        request,
        event,
        round_no=round_no,
        search_query=search_query,
        locked_reason=_event_lock_reason(event),
    )


def event_start_list_autobalance(request: HttpRequest, pk: int) -> HttpResponse:
    """Compact heats so lanes are filled sequentially."""

    event = get_object_or_404(models.Event.objects.select_related("sport_type"), pk=pk)
    round_no = _determine_active_round(request, event)
    search_query = request.POST.get("q", "")
    locked_reason = _event_lock_reason(event)
    if locked_reason:
        return _render_event_start_list(
            request,
            event,
            round_no=round_no,
            search_query=search_query,
            status=LOCKED_STATUS_CODE,
            locked_reason=locked_reason,
        )
    entries = list(
        event.entries.filter(round_no=round_no).order_by("heat", "lane_or_order", "pk")
    )
    _apply_lane_assignments(event, entries)
    return _render_event_start_list(
        request,
        event,
        round_no=round_no,
        search_query=search_query,
        locked_reason=_event_lock_reason(event),
    )


def event_start_list_autoseed(request: HttpRequest, pk: int) -> HttpResponse:
    """Seed heats alphabetically by student to create a baseline order."""

    event = get_object_or_404(models.Event.objects.select_related("sport_type"), pk=pk)
    round_no = _determine_active_round(request, event)
    search_query = request.POST.get("q", "")
    locked_reason = _event_lock_reason(event)
    if locked_reason:
        return _render_event_start_list(
            request,
            event,
            round_no=round_no,
            search_query=search_query,
            status=LOCKED_STATUS_CODE,
            locked_reason=locked_reason,
        )
    entries = list(
        event.entries.filter(round_no=round_no)
        .select_related("student")
        .order_by("student__last_name", "student__first_name", "pk")
    )
    _apply_lane_assignments(event, entries)
    return _render_event_start_list(
        request,
        event,
        round_no=round_no,
        search_query=search_query,
        locked_reason=_event_lock_reason(event),
    )


def export_students_csv(request: HttpRequest) -> HttpResponse:
    """Download a CSV of students for the selected meet."""

    meet_slug = request.GET.get("meet")
    if not meet_slug:
        return HttpResponseBadRequest("Provide a meet slug via ?meet=slug.")
    meet = get_object_or_404(models.Meet, slug=meet_slug)
    students = (
        models.Student.objects.filter(entries__event__meet=meet)
        .distinct()
        .order_by("last_name", "first_name")
    )
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="students-{meet.slug}.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            "external_id",
            "first_name",
            "last_name",
            "dob",
            "grade",
            "house",
            "gender",
            "events_signed_up",
        ]
    )
    for student in students:
        events_signed = models.Entry.objects.filter(event__meet=meet, student=student).count()
        writer.writerow(
            [
                student.external_id,
                student.first_name,
                student.last_name,
                student.dob.isoformat(),
                student.grade,
                student.house,
                student.gender,
                events_signed,
            ]
        )
    return response


def export_teachers_csv(request: HttpRequest) -> HttpResponse:
    """Download all teachers as a CSV."""

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="teachers.csv"'
    writer = csv.writer(response)
    writer.writerow(["external_id", "first_name", "last_name", "email"])
    for teacher in models.Teacher.objects.order_by("last_name", "first_name"):
        writer.writerow([teacher.external_id, teacher.first_name, teacher.last_name, teacher.email])
    return response


def export_startlists_csv(request: HttpRequest) -> HttpResponse:
    """Download a CSV describing start lists for an event."""

    event_id = request.GET.get("event")
    if not event_id:
        return HttpResponseBadRequest("Provide an event id via ?event=<id>.")
    try:
        event_id_int = int(event_id)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Event id must be an integer.")
    event = get_object_or_404(models.Event.objects.select_related("meet"), pk=event_id_int)
    entries = event.entries.select_related("student").order_by("round_no", "heat", "lane_or_order", "pk")
    round_param = request.GET.get("round")
    if round_param:
        try:
            round_filter = int(round_param)
        except (TypeError, ValueError):
            return HttpResponseBadRequest("Round must be an integer when supplied.")
        entries = entries.filter(round_no=round_filter)
    response = HttpResponse(content_type="text/csv")
    filename = f"startlists-{event.meet.slug}-{event.pk}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(
        [
            "event",
            "round",
            "heat",
            "lane_or_order",
            "student_external_id",
            "student_first_name",
            "student_last_name",
            "status",
        ]
    )
    for entry in entries:
        writer.writerow(
            [
                event.name,
                entry.round_no,
                entry.heat,
                entry.lane_or_order or "",
                entry.student.external_id,
                entry.student.first_name,
                entry.student.last_name,
                entry.get_status_display(),
            ]
        )
    return response


def export_results_csv(request: HttpRequest) -> HttpResponse:
    """Download finalized results with scoring allocations."""

    meet_slug = request.GET.get("meet")
    if not meet_slug:
        return HttpResponseBadRequest("Provide a meet slug via ?meet=slug.")
    meet = get_object_or_404(models.Meet, slug=meet_slug)
    records = services.compute_scoring_records(meet)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="sportsday-results-{meet.slug}.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            "Event",
            "Round",
            "Heat",
            "Lane/Order",
            "Student",
            "House",
            "Grade",
            "Rank",
            "Status",
            "Performance",
            "Points",
            "Participation",
            "Total",
        ]
    )
    sorted_records = sorted(
        records,
        key=lambda record: (
            record.event.name,
            record.rank or 999,
            record.student.last_name,
            record.student.first_name,
        ),
    )
    for record in sorted_records:
        entry = record.entry
        writer.writerow(
            [
                record.event.name,
                entry.round_no,
                entry.heat,
                entry.lane_or_order or "",
                f"{record.student.first_name} {record.student.last_name}",
                record.house,
                record.grade,
                record.rank or "",
                entry.get_status_display(),
                format(record.best_value.normalize(), "f") if record.best_value is not None else "",
                _format_decimal(record.points),
                _format_decimal(record.participation),
                _format_decimal(record.total),
            ]
        )
    return response


def export_leaderboard_csv(request: HttpRequest) -> HttpResponse:
    """Download leaderboard summaries for the selected meet."""

    meet_slug = request.GET.get("meet")
    if not meet_slug:
        return HttpResponseBadRequest("Provide a meet slug via ?meet=slug.")
    meet = get_object_or_404(models.Meet, slug=meet_slug)
    records = services.compute_scoring_records(meet)
    summaries = _build_leaderboard_summaries(records)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="sportsday-leaderboard-{meet.slug}.csv"'
    writer = csv.writer(response)
    writer.writerow([f"Overall house points for {meet.name}"])
    writer.writerow(["House", "Points", "Athletes"])
    for row in summaries["overall"]:
        writer.writerow([row["house"], _format_decimal(row["points"]), row["athletes"]])
    writer.writerow([])
    writer.writerow(["By grade"])
    writer.writerow(["Grade", "House", "Points", "Athletes"])
    for row in summaries["grade"]:
        writer.writerow([row["grade"], row["house"], _format_decimal(row["points"]), row["athletes"]])
    writer.writerow([])
    writer.writerow(["By event"])
    writer.writerow(["Event", "House", "Points", "Entries"])
    for row in summaries["event"]:
        writer.writerow([row["event"].name, row["house"], _format_decimal(row["points"]), row["entries"]])
    writer.writerow([])
    writer.writerow(["Participation"])
    writer.writerow(["House", "Participation pts", "Entries", "Athletes", "Events"])
    for row in summaries["participation"]:
        writer.writerow(
            [
                row["house"],
                _format_decimal(row["points"]),
                row["entries"],
                row["athletes"],
                row["events"],
            ]
        )
    return response


def event_results_fragment(request: HttpRequest, pk: int) -> HttpResponse:
    """HTMX fragment for entering event results."""

    event = get_object_or_404(models.Event.objects.select_related("sport_type", "meet"), pk=pk)
    round_no = _determine_active_round(request, event)
    heat = _determine_active_heat(request, event, round_no)

    attempts_prefetch = Prefetch("attempts", queryset=models.Attempt.objects.order_by("attempt_no"))
    round_entries_qs = (
        event.entries.filter(round_no=round_no)
        .select_related("student", "result")
        .prefetch_related(attempts_prefetch)
        .order_by("heat", "lane_or_order", "student__last_name", "student__first_name")
    )
    round_entries = list(round_entries_qs)
    is_track_with_heats = (
        event.sport_type.archetype == models.SportType.Archetype.TRACK_TIME
        and event.sport_type.supports_heats
    )
    heat_options = (
        sorted({entry.heat for entry in round_entries}) if round_entries and is_track_with_heats else []
    )
    if heat is None and heat_options:
        heat = heat_options[0]

    visible_entries = (
        [entry for entry in round_entries if heat is None or entry.heat == heat]
        if is_track_with_heats
        else round_entries
    )
    field_size = max(event.capacity, len(round_entries)) or event.capacity
    form_class, extra_kwargs = _result_form_factory(event, field_size)
    forms_list: list[forms.BaseResultForm] = []
    for entry in visible_entries:
        kwargs = extra_kwargs.copy()
        form = form_class(
            data=request.POST if request.method == "POST" else None,
            entry=entry,
            prefix=f"entry-{entry.pk}",
            **kwargs,
        )
        forms_list.append(form)

    locked_reason = _event_lock_reason(event)
    if locked_reason:
        for form in forms_list:
            for field in form.fields.values():
                field.disabled = True

    action = request.POST.get("action", "save") if request.method == "POST" else "save"
    status_message = None
    clear_cache = False
    qualifiers_created = 0

    if request.method == "POST" and not locked_reason:
        if forms_list and all(form.is_valid() for form in forms_list):
            try:
                qualifiers_created, clear_cache, status_message = _process_results_submission(
                    event, round_no, heat, action, forms_list
                )
                event.refresh_from_db(fields=["is_locked"])
                round_entries_qs = (
                    event.entries.filter(round_no=round_no)
                    .select_related("student", "result")
                    .prefetch_related(attempts_prefetch)
                    .order_by("heat", "lane_or_order", "student__last_name", "student__first_name")
                )
                round_entries = list(round_entries_qs)
                heat_options = (
                    sorted({entry.heat for entry in round_entries})
                    if round_entries and is_track_with_heats
                    else []
                )
                if heat is not None and heat_options and heat not in heat_options:
                    heat = heat_options[0]
                visible_entries = (
                    [entry for entry in round_entries if heat is None or entry.heat == heat]
                    if is_track_with_heats
                    else round_entries
                )
                forms_list = []
                for entry in visible_entries:
                    kwargs = extra_kwargs.copy()
                    forms_list.append(
                        form_class(
                            data=None,
                            entry=entry,
                            prefix=f"entry-{entry.pk}",
                            **kwargs,
                        )
                    )
            except ValueError as exc:
                for form in forms_list:
                    form.add_error(None, str(exc))
        elif not forms_list:
            status_message = "No entries available for this round."
    elif request.method == "POST" and locked_reason:
        status_message = locked_reason

    round_options = [number for number in range(1, event.rounds_total + 1)]
    cache_key = f"sportsday:event:{event.pk}:round:{round_no}:heat:{heat or 0}"

    context = {
        "event": event,
        "forms": forms_list,
        "round_no": round_no,
        "round_options": round_options,
        "heat": heat,
        "heat_options": heat_options,
        "status_message": status_message,
        "clear_cache": clear_cache,
        "qualifiers_created": qualifiers_created,
        "cache_key": cache_key,
        "has_heats": is_track_with_heats and len(heat_options) > 1,
        "action": action,
        "locked_reason": locked_reason,
    }
    return render(request, "sportsday/partials/event_results.html", context)


def event_printables_fragment(request: HttpRequest, pk: int) -> HttpResponse:
    """HTMX content describing printable assets."""

    event = get_object_or_404(models.Event, pk=pk)
    round_no = _determine_active_round(request, event)
    return render(
        request,
        "sportsday/partials/event_printables.html",
        {
            "event": event,
            "active_round": round_no,
        },
    )


def event_start_list_printable(request: HttpRequest, pk: int) -> HttpResponse:
    """Printable A4 start list for marshalling teams."""

    event = get_object_or_404(models.Event.objects.select_related("meet", "sport_type"), pk=pk)
    round_no = _determine_active_round(request, event)
    entries = (
        event.entries.filter(round_no=round_no)
        .select_related("student")
        .order_by("heat", "lane_or_order", "student__last_name", "student__first_name")
    )
    grouped: dict[int, list[models.Entry]] = defaultdict(list)
    for entry in entries:
        grouped[entry.heat].append(entry)
    orientation = "landscape" if request.GET.get("orientation") == "landscape" else "portrait"
    context = {
        "event": event,
        "round_no": round_no,
        "entries": entries,
        "grouped_entries": sorted(grouped.items(), key=lambda item: item[0]),
        "orientation": orientation,
        "supports_heats": event.sport_type.supports_heats,
        "rounds": range(1, event.rounds_total + 1),
    }
    return render(request, "sportsday/printables/start_list.html", context)


def event_marshal_cards_printable(request: HttpRequest, pk: int) -> HttpResponse:
    """Printable marshal cards for quick distribution on the field."""

    event = get_object_or_404(models.Event.objects.select_related("meet", "sport_type"), pk=pk)
    round_no = _determine_active_round(request, event)
    entries = (
        event.entries.filter(round_no=round_no)
        .select_related("student")
        .order_by("heat", "lane_or_order", "student__last_name", "student__first_name")
    )
    cards = [
        {
            "student": entry.student,
            "heat": entry.heat,
            "lane": entry.lane_or_order,
            "house": entry.student.house,
        }
        for entry in entries
    ]
    context = {
        "event": event,
        "round_no": round_no,
        "cards": cards,
        "supports_heats": event.sport_type.supports_heats,
    }
    return render(request, "sportsday/printables/marshal_cards.html", context)


def event_medal_labels_printable(request: HttpRequest, pk: int) -> HttpResponse:
    """Printable medal/award labels for podium presentations."""

    event = get_object_or_404(models.Event.objects.select_related("meet", "sport_type"), pk=pk)
    results = (
        models.Result.objects.filter(
            entry__event=event,
            entry__round_no=event.rounds_total,
            finalized=True,
        )
        .select_related("entry__student", "entry__event")
        .order_by("rank", "entry__student__last_name", "entry__student__first_name")
    )
    context = {
        "event": event,
        "results": results,
    }
    return render(request, "sportsday/printables/medal_labels.html", context)


def event_results_qr(request: HttpRequest, pk: int) -> HttpResponse:
    """Return an SVG QR code linking to the live results endpoint."""

    event = get_object_or_404(models.Event, pk=pk)
    target_url = request.build_absolute_uri(reverse("sportsday:event-results-fragment", kwargs={"pk": pk}))
    try:
        svg_markup = qr.make_svg(target_url)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    response = HttpResponse(svg_markup, content_type="image/svg+xml")
    response["Content-Disposition"] = f'inline; filename="event-{event.pk}-results-qr.svg"'
    return response


def leaderboards(request: HttpRequest) -> HttpResponse:
    """High level leaderboard views for a meet."""

    meet_slug = request.GET.get("meet")
    active_meet = models.Meet.objects.filter(slug=meet_slug).first() if meet_slug else None
    mobile_nav = mobile_nav_active = None
    if active_meet:
        mobile_nav, mobile_nav_active = _build_meet_mobile_nav(active_meet, active="leaders")

    context = {
        "meet_options": models.Meet.objects.order_by("name"),
        "active_meet": active_meet,
        "mobile_nav": mobile_nav,
        "mobile_nav_active": mobile_nav_active,
        "query_params": request.GET.urlencode(),
    }
    return render(request, "sportsday/leaderboards.html", context)


def leaderboards_panel_fragment(request: HttpRequest) -> HttpResponse:
    """Return a leaderboard table fragment for HTMX consumers."""

    meet_slug = request.GET.get("meet")
    preview = request.GET.get("preview")
    view_mode = request.GET.get("view", "overall")
    panel_id = request.GET.get("panel_id", "leaderboard-panel")

    records: list[services.ScoringRecord] = []
    rule = None
    if meet_slug:
        meet = get_object_or_404(models.Meet, slug=meet_slug)
        records = services.compute_scoring_records(meet)
        rule = services.scoring_rule_for_meet(meet)
    else:
        meet = None
        if preview:
            rule = SimpleNamespace(points_csv="10,8,6,5,4,3,2,1", participation_point=Decimal("0"))

    rows, columns, heading, subheading = _compute_leaderboard(records, view_mode, meet, preview, rule)

    return render(
        request,
        "sportsday/partials/leaderboard_panel.html",
        {
            "rows": rows,
            "columns": columns,
            "heading": heading,
            "subheading": subheading,
            "panel_id": panel_id,
            "refresh_url": request.get_full_path(),
        },
    )


def _compute_leaderboard(
    records: list[services.ScoringRecord],
    view_mode: str,
    meet: models.Meet | None,
    preview: str | None,
    rule: models.ScoringRule | SimpleNamespace | None,
):
    """Build leaderboard metadata for the requested view mode."""

    if preview and not records:
        rows = [
            [
                {"value": "Blue House"},
                {"value": "32", "align": "text-right"},
                {"value": "11", "align": "text-right"},
            ],
            [
                {"value": "Gold House"},
                {"value": "28", "align": "text-right"},
                {"value": "9", "align": "text-right"},
            ],
        ]
        columns = [
            {"label": "Group"},
            {"label": "Points", "align": "text-right"},
            {"label": "Athletes", "align": "text-right"},
        ]
        return rows, columns, "Live preview", "Real data will appear once results flow in."

    if meet is None and not preview:
        columns = [
            {"label": "House"},
            {"label": "Points", "align": "text-right"},
            {"label": "Athletes", "align": "text-right"},
        ]
        return [], columns, "Select a meet", "Choose a meet to see real scoring data."

    summaries = _build_leaderboard_summaries(records)

    if view_mode == "grade":
        rows = [
            [
                {"value": item["grade"]},
                {"value": item["house"]},
                {"value": _format_decimal(item["points"]), "align": "text-right"},
                {"value": item["athletes"], "align": "text-right"},
            ]
            for item in summaries["grade"]
        ]
        columns = [
            {"label": "Grade"},
            {"label": "House"},
            {"label": "Points", "align": "text-right"},
            {"label": "Athletes", "align": "text-right"},
        ]
        heading = "By grade"
        subheading = "House points per year level."
    elif view_mode == "event":
        rows = [
            [
                {"value": item["event"].name},
                {"value": item["house"]},
                {"value": _format_decimal(item["points"]), "align": "text-right"},
                {"value": item["entries"], "align": "text-right"},
            ]
            for item in summaries["event"]
        ]
        columns = [
            {"label": "Event"},
            {"label": "Leading house"},
            {"label": "Points", "align": "text-right"},
            {"label": "Entries", "align": "text-right"},
        ]
        heading = "By event"
        subheading = "Live leaders for each discipline."
    elif view_mode == "participation":
        rows = [
            [
                {"value": item["house"]},
                {"value": _format_decimal(item["points"]), "align": "text-right"},
                {"value": item["entries"], "align": "text-right"},
                {"value": item["athletes"], "align": "text-right"},
                {"value": item["events"], "align": "text-right"},
            ]
            for item in summaries["participation"]
        ]
        columns = [
            {"label": "House"},
            {"label": "Participation pts", "align": "text-right"},
            {"label": "Entries", "align": "text-right"},
            {"label": "Athletes", "align": "text-right"},
            {"label": "Events", "align": "text-right"},
        ]
        heading = "Participation"
        subheading = "Bonus points for turning up and showing up."
    else:
        rows = [
            [
                {"value": item["house"]},
                {"value": _format_decimal(item["points"]), "align": "text-right"},
                {"value": item["athletes"], "align": "text-right"},
            ]
            for item in summaries["overall"]
        ]
        columns = [
            {"label": "House"},
            {"label": "Points", "align": "text-right"},
            {"label": "Athletes", "align": "text-right"},
        ]
        subheading = "Scoring" if rule is None else f"Using {getattr(rule, 'points_csv', 'configured points')}"
        heading = "Overall house points"

    return rows, columns, heading, subheading
