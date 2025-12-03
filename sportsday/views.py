"""HTMX-friendly views for the sportsday application."""
from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from uuid import uuid4
from decimal import Decimal
from types import SimpleNamespace
from typing import Iterable
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, F, Max, Min, Prefetch, Q
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import forms, models, qr, services


LOCKED_STATUS_CODE = 423


SCHEDULE_ORDERING = (F("schedule_dt").asc(nulls_last=True), "pk")


QUICK_ASSIGNMENT_LOG_SESSION_KEY = "sportsday.quick-assignments.log"
QUICK_ASSIGNMENT_LOG_LIMIT = 50


def _quick_assignment_user_label(user) -> str:
    """Return a readable label for the acting staff member."""

    if hasattr(user, "get_full_name"):
        full_name = (user.get_full_name() or "").strip()
        if full_name:
            return full_name
    username = getattr(user, "get_username", lambda: "")()
    return (username or getattr(user, "username", "") or "Staff")


def _get_quick_assignment_log(request: HttpRequest) -> list[dict[str, object]]:
    """Return the per-session quick assignment log."""

    entries = request.session.get(QUICK_ASSIGNMENT_LOG_SESSION_KEY, [])
    if isinstance(entries, list):
        return [entry for entry in entries if isinstance(entry, dict)]
    return []


def _save_quick_assignment_log(request: HttpRequest, entries: list[dict[str, object]]) -> None:
    """Persist the quick assignment log back to the session."""

    request.session[QUICK_ASSIGNMENT_LOG_SESSION_KEY] = entries[:QUICK_ASSIGNMENT_LOG_LIMIT]
    request.session.modified = True


def _append_quick_assignment_log(
    request: HttpRequest,
    *,
    action: str,
    student: models.Student,
    event: models.Event,
    entry_id: int | None,
    entry_snapshot: dict[str, object] | None = None,
) -> None:
    """Store a change in the per-session log for undo support."""

    payload = {
        "id": str(uuid4()),
        "timestamp": timezone.now().isoformat(),
        "action": action,
        "student_id": student.pk,
        "student_name": str(student),
        "event_id": event.pk,
        "event_name": event.name,
        "user_name": _quick_assignment_user_label(request.user),
        "entry_id": entry_id,
        "entry_snapshot": entry_snapshot or {},
        "undone": False,
    }

    entries = _get_quick_assignment_log(request)
    entries.insert(0, payload)
    _save_quick_assignment_log(request, entries)


def _hydrate_quick_assignment_log(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    """Attach parsed timestamps so templates can render nicely."""

    hydrated: list[dict[str, object]] = []
    for entry in entries:
        data = entry.copy()
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            try:
                data["timestamp_obj"] = datetime.fromisoformat(timestamp)
            except ValueError:
                data["timestamp_obj"] = None
        undo_timestamp = data.get("undo_timestamp")
        if isinstance(undo_timestamp, str):
            try:
                data["undo_timestamp_obj"] = datetime.fromisoformat(undo_timestamp)
            except ValueError:
                data["undo_timestamp_obj"] = None
        hydrated.append(data)
    return hydrated


def _extract_quick_assignment_form_state(request: HttpRequest) -> dict[str, str]:
    """Return the persisted form state for the quick assignment console."""

    data = request.POST if request.method == "POST" else request.GET
    mode = (data.get("mode") or "add").lower()
    if mode not in {"add", "remove"}:
        mode = "add"
    student_query = (data.get("student_query") or data.get("q") or "").strip()
    return {
        "mode": mode,
        "student_query": student_query,
        "student_id": (data.get("student_id") or "").strip(),
        "event_query": (data.get("event_query") or "").strip(),
        "event_id": (data.get("event_id") or "").strip(),
    }


def _resolve_quick_assignment_student(form_state: dict[str, str]) -> models.Student | None:
    """Fetch the selected student from the current form state."""

    student_id = form_state.get("student_id") or ""
    if not student_id:
        return None
    try:
        student = models.Student.objects.get(pk=int(student_id))
    except (ValueError, models.Student.DoesNotExist):
        form_state["student_id"] = ""
        return None
    if not form_state.get("student_query"):
        form_state["student_query"] = str(student)
    return student


def _resolve_quick_assignment_event(form_state: dict[str, str]) -> models.Event | None:
    """Fetch the selected event from the current form state."""

    event_id = form_state.get("event_id") or ""
    if not event_id:
        return None
    try:
        return models.Event.objects.select_related("meet", "sport_type").get(pk=int(event_id))
    except (ValueError, models.Event.DoesNotExist):
        form_state["event_id"] = ""
        return None


def _build_quick_assignment_panel_context(
    request: HttpRequest,
    *,
    form_state: dict[str, str],
    selected_student: models.Student | None,
    focus_target: str,
    error_message: str | None,
    info_message: str | None,
    active_meet: models.Meet | None,
    student_error_message: str | None = None,
) -> dict[str, object]:
    """Bundle all context needed to render the quick assignment panel."""

    return {
        "form_state": form_state,
        "selected_student": selected_student,
        "focus_target": focus_target,
        "error_message": error_message,
        "info_message": info_message,
        "active_meet": active_meet,
        "log_entries": _hydrate_quick_assignment_log(_get_quick_assignment_log(request)),
        "student_error_message": student_error_message,
        "student_helper_text": "Type at least two characters to search.",
        "event_helper_text": "Start typing to search for events.",
    }


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


def _format_result_value(event: models.Event, value: Decimal | None) -> str:
    """Return a human readable performance string for an event result."""

    if value is None:
        return ""

    archetype = getattr(event.sport_type, "archetype", "")
    unit = (event.measure_unit or "").strip()

    if archetype == models.SportType.Archetype.TRACK_TIME:
        minutes = int(value // Decimal(60))
        seconds = (value - Decimal(minutes) * Decimal(60)).quantize(Decimal("0.001"))
        seconds_text = format(seconds, ".3f")
        if minutes:
            seconds_text = seconds_text.zfill(6)
            display = f"{minutes}:{seconds_text}"
        else:
            display = seconds_text
        return f"{display} {unit}".strip()

    if archetype == models.SportType.Archetype.FIELD_COUNT:
        display = f"{int(value)}"
    else:
        quantized = value.quantize(Decimal("0.001"))
        display = format(quantized.normalize(), "f")

    return f"{display} {unit}".strip()


def _grade_sort_key(grade: str) -> tuple[int, str]:
    return models._grade_key(grade)


def _grade_option_sort_key(grade: str) -> tuple[int, str]:
    """Sort helper that keeps numeric grade labels ordered naturally."""

    return models._grade_key(grade)


def _event_form_grade_choices(
    form: forms.EventConfigForm,
) -> tuple[list[str], list[str]]:
    """Return available grade options and the selected range for a form."""

    grade_values = list(
        models.Student.objects.values_list("grade", flat=True).distinct()
    )
    # Include form-provided values so that editing existing events always shows them.
    grade_min = (form["grade_min"].value() or "").strip() if "grade_min" in form.fields else ""
    grade_max = (form["grade_max"].value() or "").strip() if "grade_max" in form.fields else ""
    for value in (grade_min, grade_max):
        if value and value not in grade_values:
            grade_values.append(value)

    seen: set[str] = set()
    cleaned: list[str] = []
    for value in grade_values:
        normalised = (value or "").strip()
        if not normalised or normalised in seen:
            continue
        seen.add(normalised)
        cleaned.append(normalised)
    cleaned.sort(key=_grade_option_sort_key)

    selected: list[str] = []
    if grade_min and grade_max and grade_min in cleaned and grade_max in cleaned:
        start = cleaned.index(grade_min)
        end = cleaned.index(grade_max)
        if start > end:
            start, end = end, start
        selected = cleaned[start : end + 1]
    else:
        for value in (grade_min, grade_max):
            if value and value in cleaned and value not in selected:
                selected.append(value)

    return cleaned, selected


def _gender_label(code: str) -> str:
    mapping = {
        models.Event.GenderLimit.MALE: "Boys",
        models.Event.GenderLimit.FEMALE: "Girls",
        models.Event.GenderLimit.MIXED: "Mixed",
    }
    return mapping.get(code, code)


def _teacher_for_user(user) -> models.Teacher | None:
    """Best-effort mapping from the logged-in user to a Teacher record.

    Historically teachers authenticated via email, but some deployments only
    populate the ``external_id`` field when syncing staff lists.  The updated
    lookup keeps the email matching behaviour while also falling back to common
    identifiers so that marshals without stored emails can still be recognised
    as assigned teachers.
    """

    if not getattr(user, "is_authenticated", False):
        return None

    filters = Q()
    email = (getattr(user, "email", "") or "").strip()
    if email:
        filters |= Q(email__iexact=email)

    username = (getattr(user, "username", "") or "").strip()
    if username:
        filters |= Q(external_id__iexact=username)

    user_pk = getattr(user, "pk", None)
    if user_pk:
        filters |= Q(external_id__iexact=str(user_pk))

    if not filters:
        return None

    return models.Teacher.objects.filter(filters).first()


def _format_decimal_input(value: Decimal | None) -> str:
    """Format decimal values for pre-populating inputs."""

    if value is None:
        return ""
    quantized = value.quantize(Decimal("0.001"))
    text = format(quantized.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _annotate_replacement_options(
    rows: list[dict[str, object]],
    event: models.Event,
) -> None:
    """Attach eligible replacement student options to each row."""

    if not rows:
        return

    combos: set[tuple[str, str]] = set()
    for row in rows:
        student = row.get("student")
        if not isinstance(student, models.Student):
            row["replacement_choices"] = []
            continue
        house = (student.house or "").strip()
        gender = (student.gender or "").strip()
        combos.add((house, gender))

    if not combos:
        for row in rows:
            row["replacement_choices"] = []
        return

    candidate_filter: Q | None = None
    for house, gender in combos:
        clause = Q()
        if house:
            clause &= Q(house=house)
        else:
            clause &= (Q(house__isnull=True) | Q(house=""))
        if gender:
            clause &= Q(gender=gender)
        else:
            clause &= (Q(gender__isnull=True) | Q(gender=""))
        candidate_filter = clause if candidate_filter is None else candidate_filter | clause

    candidates = models.Student.objects.filter(is_active=True)
    if candidate_filter is not None:
        candidates = candidates.filter(candidate_filter)
    candidates = candidates.order_by("last_name", "first_name")

    event_student_ids: set[int] = set()
    for row in rows:
        entry = row.get("entry")
        if isinstance(entry, models.Entry) and entry.student_id is not None:
            event_student_ids.add(entry.student_id)

    mapping: dict[tuple[str, str], list[dict[str, object]]] = {
        combo: [] for combo in combos
    }
    for student in candidates:
        if not event.grade_allows(student.grade):
            continue
        combo = ((student.house or "").strip(), (student.gender or "").strip())
        if combo not in mapping:
            continue
        if student.pk in event_student_ids:
            continue
        grade = (student.grade or "").strip()
        label_grade = f"Grade {grade}" if grade else "Grade —"
        mapping[combo].append(
            {
                "id": student.pk,
                "label": f"{student.first_name} {student.last_name} – {label_grade}",
            }
        )

    for row in rows:
        student = row.get("student")
        if not isinstance(student, models.Student):
            row["replacement_choices"] = []
            continue
        combo = ((student.house or "").strip(), (student.gender or "").strip())
        choices = mapping.get(combo, [])
        row["replacement_choices"] = choices


def _track_rows_from_db(entries: list[models.Entry], *, allow_time: bool) -> list[dict[str, object]]:
    """Prepare track-row dictionaries from persisted data."""

    rows: list[dict[str, object]] = []
    for entry in entries:
        result = getattr(entry, "result", None)
        attempt_lookup = {attempt.attempt_no: attempt for attempt in entry.attempts.all()}
        attempt = attempt_lookup.get(1)
        time_value: Decimal | None = None
        if attempt and attempt.time_seconds is not None:
            time_value = attempt.time_seconds
        elif result and result.best_value is not None:
            time_value = result.best_value
        dq = entry.status == models.Entry.Status.DQ
        dns = entry.status == models.Entry.Status.DNS
        if dq and dns:
            dns = True
            dq = False
        rows.append(
            {
                "entry": entry,
                "entry_id": entry.pk,
                "student": entry.student,
                "house": entry.student.house or "—",
                "rank_input": str(result.rank) if result and result.rank is not None else "",
                "rank_value": result.rank if result else None,
                "time_input": _format_decimal_input(time_value) if allow_time else "",
                "parsed_time": time_value,
                "dq": dq,
                "dns": dns,
                "status": entry.status,
            }
        )
    return rows


def _track_rows_from_post(
    entries: list[models.Entry],
    data,
    *,
    allow_time: bool,
) -> tuple[list[dict[str, object]], list[str]]:
    """Parse submitted track rows from POST data."""

    rows: list[dict[str, object]] = []
    errors: list[str] = []
    for entry in entries:
        dq = bool(data.get(f"dq[{entry.pk}]"))
        dns = bool(data.get(f"dns[{entry.pk}]"))
        if dq and dns:
            dq = False
            dns = True
        rank_raw = (data.get(f"rank[{entry.pk}]") or "").strip()
        time_raw = (data.get(f"time[{entry.pk}]") or "").strip() if allow_time else ""
        rank_value: int | None = None
        time_value: Decimal | None = None
        if not dq and not dns and rank_raw:
            try:
                rank_value = int(rank_raw)
                if rank_value < 1:
                    raise ValueError
            except ValueError:
                errors.append(f"{entry.student} – enter a positive rank.")
        if allow_time and not dq and not dns and time_raw:
            try:
                time_value = services.parse_time(time_raw)
            except ValueError:
                errors.append(
                    f"{entry.student} – enter time as mm:ss.SSS, ss.SSS, or whole seconds."
                )
        status = models.Entry.Status.DNS if dns else (
            models.Entry.Status.DQ if dq else models.Entry.Status.CONFIRMED
        )
        rows.append(
            {
                "entry": entry,
                "entry_id": entry.pk,
                "student": entry.student,
                "house": entry.student.house or "—",
                "rank_input": rank_raw,
                "rank_value": rank_value,
                "time_input": time_raw,
                "parsed_time": time_value,
                "dq": dq,
                "dns": dns,
                "status": status,
            }
        )
    return rows, errors


def _field_rows_from_db(
    entries: list[models.Entry],
    *,
    attempt_count: int,
    archetype: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for entry in entries:
        attempts_lookup = {attempt.attempt_no: attempt for attempt in entry.attempts.all()}
        row_attempts: list[dict[str, object]] = []
        for index in range(1, attempt_count + 1):
            attempt = attempts_lookup.get(index)
            decimal_value: Decimal | None = None
            count_value: int | None = None
            if archetype == models.SportType.Archetype.FIELD_DISTANCE:
                if attempt and attempt.valid and attempt.distance_m is not None:
                    decimal_value = attempt.distance_m
            else:
                if attempt and attempt.valid and attempt.count is not None:
                    count_value = attempt.count
                    decimal_value = Decimal(count_value)
            if archetype == models.SportType.Archetype.FIELD_DISTANCE:
                display_value = _format_decimal_input(decimal_value)
            else:
                display_value = str(count_value) if count_value is not None else ""
            row_attempts.append(
                {
                    "index": index,
                    "raw": display_value,
                    "decimal": decimal_value,
                    "count": count_value,
                }
            )
        dq = entry.status == models.Entry.Status.DQ
        dns = entry.status == models.Entry.Status.DNS
        if dq and dns:
            dns = True
            dq = False
        rows.append(
            {
                "entry": entry,
                "entry_id": entry.pk,
                "student": entry.student,
                "house": entry.student.house or "—",
                "attempts": row_attempts,
                "dq": dq,
                "dns": dns,
                "status": entry.status,
                "best_value": None,
                "best_display": "",
                "position": None,
                "best_attempt_no": None,
            }
        )
    _assign_field_positions(rows, archetype)
    return rows


def _field_rows_from_post(
    entries: list[models.Entry],
    data,
    *,
    attempt_count: int,
    archetype: str,
) -> tuple[list[dict[str, object]], list[str]]:
    rows: list[dict[str, object]] = []
    errors: list[str] = []
    for entry in entries:
        dq = bool(data.get(f"dq[{entry.pk}]"))
        dns = bool(data.get(f"dns[{entry.pk}]"))
        if dq and dns:
            dq = False
            dns = True
        row_attempts: list[dict[str, object]] = []
        for index in range(1, attempt_count + 1):
            field_name = f"attempt[{entry.pk}][{index}]"
            raw_value = (data.get(field_name) or "").strip()
            decimal_value: Decimal | None = None
            count_value: int | None = None
            if raw_value:
                try:
                    if archetype == models.SportType.Archetype.FIELD_DISTANCE:
                        decimal_value = services.parse_distance(raw_value)
                    else:
                        count_value = services.parse_count(raw_value)
                        if count_value is not None:
                            decimal_value = Decimal(count_value)
                except ValueError:
                    errors.append(
                        f"{entry.student} attempt {index} – enter a valid number."
                    )
            if archetype == models.SportType.Archetype.FIELD_DISTANCE:
                display_value = raw_value
            else:
                display_value = raw_value
            row_attempts.append(
                {
                    "index": index,
                    "raw": display_value,
                    "decimal": decimal_value,
                    "count": count_value,
                }
            )
        status = models.Entry.Status.DNS if dns else (
            models.Entry.Status.DQ if dq else models.Entry.Status.CONFIRMED
        )
        rows.append(
            {
                "entry": entry,
                "entry_id": entry.pk,
                "student": entry.student,
                "house": entry.student.house or "—",
                "attempts": row_attempts,
                "dq": dq,
                "dns": dns,
                "status": status,
                "best_value": None,
                "best_display": "",
                "position": None,
                "best_attempt_no": None,
            }
        )
    _assign_field_positions(rows, archetype)
    return rows, errors


def _assign_field_positions(rows: list[dict[str, object]], archetype: str) -> None:
    """Compute best attempts and live positions for field events."""

    contenders: list[tuple[tuple, int, int, dict[str, object]]] = []
    for row in rows:
        status = row.get("status")
        if status not in {
            models.Entry.Status.CONFIRMED,
            models.Entry.Status.DQ,
            models.Entry.Status.DNS,
        }:
            status = models.Entry.Status.CONFIRMED
        row["status"] = status
        if status != models.Entry.Status.CONFIRMED:
            row["best_value"] = None
            row["best_display"] = ""
            row["position"] = None
            row["best_attempt_no"] = None
            continue
        valid_values: list[Decimal] = [
            attempt["decimal"]
            for attempt in row.get("attempts", [])
            if attempt.get("decimal") is not None
        ]
        if not valid_values:
            row["best_value"] = None
            row["best_display"] = ""
            row["position"] = None
            row["best_attempt_no"] = None
            continue
        best_value = max(valid_values)
        row["best_value"] = best_value
        row["best_display"] = _format_decimal_input(best_value)
        best_attempt_no: int | None = None
        for attempt in row.get("attempts", []):
            if attempt.get("decimal") == best_value:
                best_attempt_no = attempt.get("index")
                break
        row["best_attempt_no"] = best_attempt_no
        ordered_series = sorted(valid_values, reverse=True)
        row["series"] = ordered_series
        best_attempt_key = best_attempt_no if best_attempt_no is not None else 9999
        sort_key = tuple(-value for value in ordered_series)
        contenders.append((sort_key, best_attempt_key, row["entry"].pk, row))

    contenders.sort(key=lambda item: (item[0], item[1], item[2]))
    current_rank = 1
    index = 0
    while index < len(contenders):
        group = [contenders[index]]
        while (
            index + len(group) < len(contenders)
            and contenders[index + len(group)][0] == group[0][0]
            and contenders[index + len(group)][1] == group[0][1]
        ):
            group.append(contenders[index + len(group)])
        for _, _, _, row in group:
            row["position"] = current_rank
        current_rank += len(group)
        index += len(group)

    # Clear helper keys from rows without contenders
    for row in rows:
        if row.get("position") is None:
            row.setdefault("best_display", "")

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
    track_filter = tally_filter & Q(
        entries__event__sport_type__archetype__startswith="TRACK"
    )
    field_filter = tally_filter & Q(
        entries__event__sport_type__archetype__startswith="FIELD"
    )

    return (
        students.annotate(
            events_tally=Count("entries", filter=tally_filter, distinct=True),
            track_events_tally=Count("entries", filter=track_filter, distinct=True),
            field_events_tally=Count("entries", filter=field_filter, distinct=True),
        )
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
            "description": "Create a meet, set the basics, and start building events in minutes.",
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


@require_POST
def meet_sync_event_dates(request: HttpRequest) -> HttpResponse:
    """Align all scheduled events so their dates match the parent meet date."""

    events = models.Event.objects.select_related("meet").filter(schedule_dt__isnull=False)
    updated = 0

    for event in events:
        schedule_dt = event.schedule_dt
        meet_date = event.meet.date
        if not schedule_dt or schedule_dt.date() == meet_date:
            continue

        new_dt = datetime.combine(meet_date, schedule_dt.timetz())
        event.schedule_dt = new_dt
        event.save(update_fields=["schedule_dt"])
        updated += 1

    if updated:
        messages.success(
            request,
            f"Synced {updated} event{'s' if updated != 1 else ''} to their meet dates.",
        )
    else:
        messages.info(request, "All scheduled events already match their meet dates.")

    return redirect("sportsday:meet-list")


def meet_create(request: HttpRequest) -> HttpResponse:
    """Create a new meet from a single form."""

    form = forms.MeetBasicsForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        meet = form.save()
        models.ScoringRule.objects.update_or_create(
            meet=meet,
            defaults={
                "points_csv": form.cleaned_data["points_csv"],
                "participation_point": form.cleaned_data["participation_point"],
                "tie_method": form.cleaned_data["tie_method"],
            },
        )
        messages.success(request, f"Created meet {meet.name}.")
        return redirect("sportsday:meet-detail", slug=meet.slug)

    context = {
        "form": form,
        "active_meet": None,
        "is_create": True,
    }
    return render(request, "sportsday/meet_form.html", context)


def meet_update(request: HttpRequest, slug: str) -> HttpResponse:
    """Edit the configuration of an existing meet."""

    meet = get_object_or_404(models.Meet.objects.prefetch_related("scoring_rules"), slug=slug)
    scoring_rule = meet.scoring_rules.first()
    form = forms.MeetBasicsForm(request.POST or None, instance=meet, scoring_rule=scoring_rule)
    if request.method == "POST" and form.is_valid():
        meet = form.save()
        models.ScoringRule.objects.update_or_create(
            meet=meet,
            defaults={
                "points_csv": form.cleaned_data["points_csv"],
                "participation_point": form.cleaned_data["participation_point"],
                "tie_method": form.cleaned_data["tie_method"],
            },
        )
        messages.success(request, f"Updated meet {meet.name}.")
        return redirect("sportsday:meet-detail", slug=meet.slug)

    context = {
        "form": form,
        "meet": meet,
        "active_meet": meet,
        "is_create": False,
    }
    return render(request, "sportsday/meet_form.html", context)


def meet_download_template(request: HttpRequest, kind: str) -> HttpResponse:
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
    highlight_event = meet.events.order_by(*SCHEDULE_ORDERING).first()
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
    events = list(meet.events.select_related("sport_type").order_by(*SCHEDULE_ORDERING))
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
        events = list(teacher.events.filter(meet=meet).order_by(*SCHEDULE_ORDERING))
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


@require_POST
def meet_delete(request: HttpRequest, slug: str) -> HttpResponse:
    """Delete a meet and tidy related session state."""

    meet = get_object_or_404(models.Meet, slug=slug)
    meet_name = meet.name
    meet.delete()
    messages.success(request, f"Deleted meet {meet_name}.")
    return redirect("sportsday:meet-list")


def events_generate(request: HttpRequest, slug: str) -> HttpResponse:
    """Bulk generate events for a meet using grade/gender divisions."""

    meet = get_object_or_404(models.Meet, slug=slug)
    grade_options = list(
        models.Student.objects.values_list("grade", flat=True).distinct().order_by("grade")
    )
    form = forms.EventGenerationForm(request.POST or None, grades=grade_options)
    summary: dict[str, object] | None = None
    payload_json: str | None = None
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


def events_import(request: HttpRequest, slug: str) -> HttpResponse:
    """Bulk create events for a meet from a CSV file."""

    meet = get_object_or_404(models.Meet, slug=slug)
    form = forms.EventImportForm(request.POST or None, request.FILES or None)
    preview: list[dict[str, object]] | None = None
    summary: dict[str, object] | None = None
    errors: list[str] = []
    payload_json: str | None = None

    if request.method == "POST":
        payload = request.POST.get("payload")
        if payload:
            summary = _persist_imported_events(payload, meet)
        elif form.is_valid():
            preview, errors = _parse_event_import_csv(
                form.cleaned_data["csv_file"], meet, capacity_override=form.cleaned_data.get("capacity_override")
            )
            if preview:
                payload_json = json.dumps(
                    [
                        {
                            "name": row["name"],
                            "grade_min": row["grade_min"],
                            "grade_max": row["grade_max"],
                            "gender_limit": row["gender_limit"],
                            "schedule_dt": row["schedule_dt"].isoformat() if row["schedule_dt"] else None,
                            "sport_type_id": row["sport_type"].pk,
                            "capacity": row.get("capacity"),
                        }
                        for row in preview
                    ]
                )
            if not preview and not errors:
                errors.append("No rows found in the CSV file.")

    context = {
        "meet": meet,
        "form": form,
        "preview": preview,
        "payload_json": payload_json,
        "errors": errors,
        "summary": summary,
        "active_meet": meet,
    }
    return render(request, "sportsday/events_import.html", context)


def _parse_event_import_csv(upload, meet: models.Meet, *, capacity_override: int | None = None) -> tuple[list[dict[str, object]], list[str]]:
    try:
        data = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        upload.seek(0)
        data = upload.read().decode("latin-1")
    reader = csv.DictReader(io.StringIO(data))
    preview: list[dict[str, object]] = []
    errors: list[str] = []

    if not reader.fieldnames:
        errors.append("CSV file has no headers.")
        return preview, errors

    header_map = {header.strip().lower(): header for header in reader.fieldnames if header}
    required_headers = {"event", "grade", "m/f", "time"}
    missing_headers = required_headers - set(header_map)
    if missing_headers:
        errors.append(f"Missing columns: {', '.join(sorted(missing_headers))}")
        return preview, errors

    for line_number, row in enumerate(reader, start=2):
        if not any(row.values()):
            continue
        name = (row.get(header_map["event"]) or "").strip()
        grade_label = (row.get(header_map["grade"]) or "").strip()
        gender_value = (row.get(header_map["m/f"]) or "").strip()
        time_value = (row.get(header_map["time"]) or "").strip()

        if not name:
            errors.append(f"Row {line_number}: event name is required")
            continue
        grade_bounds = _parse_grade_bounds(grade_label)
        if grade_bounds is None:
            errors.append(f"Row {line_number}: could not interpret grade '{grade_label}'")
            continue
        gender_limit = _parse_gender(gender_value)
        if gender_limit is None:
            errors.append(f"Row {line_number}: gender must be M or F")
            continue
        schedule_dt = _parse_meet_time(meet, time_value)
        if time_value and schedule_dt is None:
            errors.append(f"Row {line_number}: could not parse time '{time_value}'")
            continue
        sport_type = _resolve_sport_type(name)
        if sport_type is None:
            errors.append(
                f"Row {line_number}: no sport type found for '{name}'. Please create a sport type first."
            )
            continue

        grade_min, grade_max, connector = grade_bounds
        formatted_grade = _format_grade_label(grade_min, grade_max, connector)
        event_name = f"{name} {formatted_grade} {gender_limit}".strip()
        preview.append(
            {
                "name": event_name,
                "grade_min": grade_min,
                "grade_max": grade_max,
                "grade_connector": connector,
                "gender_limit": gender_limit,
                "schedule_dt": schedule_dt,
                "time_input": time_value,
                "sport_type": sport_type,
                "capacity": capacity_override or sport_type.default_capacity,
            }
        )
    upload.close()
    return preview, errors


def _parse_grade_bounds(raw: str) -> tuple[str, str, str] | None:
    text = (raw or "").strip()
    if not text:
        return None
    tokens = [part for part in re.split(r"[^A-Za-z0-9]+", text) if part]
    if not tokens:
        return None
    connector = "range" if re.search(r"\bto\b|-", text.lower()) else "list"
    grade_labels: list[str] = []
    for token in tokens:
        label = models.normalise_grade_label(token)
        if label:
            grade_labels.append(label)

    if not grade_labels:
        return None

    grade_min = grade_labels[0]
    grade_max = grade_labels[-1]
    return grade_min, grade_max, connector


def _format_grade_label(grade_min: str, grade_max: str, connector: str) -> str:
    """Build a readable grade label for event names."""

    if grade_min == grade_max:
        return grade_min
    glue = " to " if connector == "range" else " & "
    compact_max = grade_max[1:] if grade_min.startswith("G") and grade_max.startswith("G") else grade_max
    return f"{grade_min}{glue}{compact_max}"


def _parse_gender(raw: str) -> str | None:
    value = (raw or "").strip().upper()
    if value in {models.Event.GenderLimit.MALE, "MALE", "M"}:
        return models.Event.GenderLimit.MALE
    if value in {models.Event.GenderLimit.FEMALE, "FEMALE", "F"}:
        return models.Event.GenderLimit.FEMALE
    if value in {models.Event.GenderLimit.MIXED, "X", "MIXED", "OPEN"}:
        return models.Event.GenderLimit.MIXED
    return None


def _parse_meet_time(meet: models.Meet, value: str) -> datetime | None:
    if not value:
        return None
    time_text = value.strip()
    if re.fullmatch(r"\d{4}", time_text):
        time_text = f"{time_text[:2]}:{time_text[2:]}"
    try:
        parsed_time = datetime.strptime(time_text, "%H:%M").time()
    except ValueError:
        return None
    combined = datetime.combine(meet.date, parsed_time)
    if timezone.is_naive(combined):
        return timezone.make_aware(combined)
    return combined


def _resolve_sport_type(name: str) -> models.SportType | None:
    cleaned = (name or "").strip()
    if not cleaned:
        return None

    field_map = {
        "LJ": "Standing Long jump",
        "SLJ": "Standing Long jump",
        "SP": "Shot put",
        "HJ": "High jump",
        "JAV": "Javelin",
        "TB": "Tennis ball throw",
        "SB": "Speed bounce",
        "SACK": "Sack Race",
        "Bean": "Beanbag Race",
        "BB Bal": "Beanbag Race",
        "HOOP": "Hoop Relay",
        "TR&B": "Tennis Racket & Ball Race",
        "OBR": "Obstacle Race",
        "RELAY": "4x50m Relay",
    }

    def _find_by_keys(keys: Iterable[str]) -> models.SportType | None:
        for key in keys:
            match = models.SportType.objects.filter(label__iexact=key).first()
            if match:
                return match
            match = models.SportType.objects.filter(key__iexact=key).first()
            if match:
                return match
        return None

    upper_name = cleaned.upper()
    if upper_name in field_map:
        mapped = field_map[upper_name]
        sport_type = _find_by_keys([mapped, upper_name, cleaned])
        if sport_type:
            return sport_type

    distance_match = re.match(r"^(\d+)", cleaned)
    if distance_match:
        distance = distance_match.group(1)
        candidates = [f"{distance}m", f"{distance} m", distance]
        sport_type = _find_by_keys(candidates)
        if sport_type:
            return sport_type

    return _find_by_keys([cleaned])


def _persist_imported_events(payload: str, meet: models.Meet) -> dict[str, object]:
    created = skipped = 0
    errors: list[str] = []
    try:
        rows = json.loads(payload)
    except json.JSONDecodeError:
        return {"created": 0, "skipped": 0, "errors": ["Import payload was invalid."]}

    teacher = (
        models.Teacher.objects.filter(first_name__iexact="Matthew", last_name__iexact="McClune").first()
        or models.Teacher.objects.create(first_name="Matthew", last_name="McClune")
    )

    for index, row in enumerate(rows, start=1):
        sport_type = models.SportType.objects.filter(pk=row.get("sport_type_id")).first()
        if not sport_type:
            errors.append(f"Row {index}: sport type could not be found")
            continue
        schedule_dt = None
        if row.get("schedule_dt"):
            try:
                parsed_dt = datetime.fromisoformat(row["schedule_dt"])
                schedule_dt = timezone.make_aware(parsed_dt) if timezone.is_naive(parsed_dt) else parsed_dt
            except (TypeError, ValueError):
                errors.append(f"Row {index}: invalid schedule time")
                continue

        existing = models.Event.objects.filter(
            meet=meet,
            name=row.get("name", ""),
            grade_min=row.get("grade_min", ""),
            grade_max=row.get("grade_max", ""),
            gender_limit=row.get("gender_limit", ""),
        ).first()
        if existing:
            skipped += 1
            continue

        capacity = row.get("capacity")
        event = models.Event(
            meet=meet,
            sport_type=sport_type,
            name=row.get("name", "").strip(),
            grade_min=row.get("grade_min", ""),
            grade_max=row.get("grade_max", ""),
            gender_limit=row.get("gender_limit", models.Event.GenderLimit.MIXED),
            measure_unit=sport_type.default_unit,
            capacity=capacity if capacity else sport_type.default_capacity,
            attempts=sport_type.default_attempts,
            rounds_total=1,
            schedule_dt=schedule_dt,
        )
        event.save()
        if teacher:
            event.assigned_teachers.add(teacher)
        created += 1
    return {"created": created, "skipped": skipped, "errors": errors}


def entries_bulk(request: HttpRequest, slug: str) -> HttpResponse:
    """Spreadsheet-style bulk assignment UI for a meet."""

    meet = get_object_or_404(models.Meet, slug=slug)
    students = list(
        models.Student.objects.filter(is_active=True).order_by("last_name", "first_name")
    )

    def _eligible_students(event: models.Event) -> list[models.Student]:
        return [
            student
            for student in students
            if event.grade_allows(student.grade) and event.gender_allows(student.gender)
        ]

    events = list(
        meet.events.prefetch_related(
            Prefetch("entries", queryset=models.Entry.objects.select_related("student"))
        )
    )

    summary: dict[str, object] | None = None

    if request.method == "POST":
        summary = {
            "created": 0,
            "removed": 0,
            "errors": [],
        }
        for event in events:
            lock_reason = _event_lock_reason(event)
            if lock_reason:
                summary["errors"].append(f"{event.name}: {lock_reason}")
                continue

            slot_count = max(
                int(request.POST.get(f"event-{event.pk}-slots", event.capacity) or 0),
                len(event.entries.all()),
                event.capacity,
            )
            selected_ids: list[int] = []

            for index in range(slot_count):
                raw_value = (request.POST.get(f"event-{event.pk}-slot-{index}") or "").strip()
                if not raw_value:
                    continue
                match = re.match(r"^(\d+)", raw_value)
                if not match:
                    summary["errors"].append(
                        f"{event.name}: Could not understand '{raw_value}'. Use the suggested options."
                    )
                    continue
                selected_ids.append(int(match.group(1)))

            eligible_ids = {student.pk for student in _eligible_students(event)}
            filtered_ids: list[int] = []
            for student_id in selected_ids:
                if student_id in filtered_ids:
                    continue
                if student_id not in eligible_ids:
                    summary["errors"].append(
                        f"{event.name}: Student {student_id} is not eligible for this event."
                    )
                    continue
                filtered_ids.append(student_id)

            existing = {
                entry.student_id: entry
                for entry in event.entries.all()
                if entry.round_no == 1
            }

            for student_id, entry in list(existing.items()):
                if student_id not in filtered_ids:
                    entry.delete()
                    summary["removed"] += 1

            for student_id in filtered_ids:
                if student_id in existing:
                    continue
                try:
                    models.Entry.objects.create(
                        event=event,
                        student_id=student_id,
                        round_no=1,
                        heat=1,
                    )
                except ValidationError as exc:
                    summary["errors"].append(
                        f"{event.name}: {exc.messages[0] if exc.messages else 'Could not add student.'}"
                    )
                    continue
                summary["created"] += 1

        events = list(
            meet.events.prefetch_related(
                Prefetch("entries", queryset=models.Entry.objects.select_related("student"))
            )
        )

    event_rows: list[dict[str, object]] = []
    for event in events:
        eligible = _eligible_students(event)
        existing_entries = [
            entry for entry in event.entries.all() if getattr(entry, "round_no", 1) == 1
        ]
        slot_count = max(event.capacity, len(existing_entries))
        assigned_values = [
            f"{entry.student.pk} · {entry.student.first_name} {entry.student.last_name}"
            for entry in existing_entries
        ]
        slot_values = [assigned_values[i] if i < len(assigned_values) else "" for i in range(slot_count)]
        event_rows.append(
            {
                "event": event,
                "eligible_students": eligible,
                "entries": existing_entries,
                "slot_count": slot_count,
                "fill_count": len(existing_entries),
                "assigned_values": assigned_values,
                "slot_range": range(slot_count),
                "slot_values": slot_values,
            }
        )

    max_slot_count = max((row["slot_count"] for row in event_rows), default=0)
    for row in event_rows:
        padding = max_slot_count - row["slot_count"]
        row["slot_range"] = range(row["slot_count"])
        row["padding_range"] = range(padding if padding > 0 else 0)
    context = {
        "meet": meet,
        "event_rows": event_rows,
        "max_slot_count": max_slot_count,
        "slot_range": range(max_slot_count),
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

    meet_options = models.Meet.objects.order_by("-date", "name")
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


def sport_type_admin(request: HttpRequest) -> HttpResponse:
    """Simple management console for sport types."""

    sport_queryset = models.SportType.objects.order_by("label")
    selected_instance: models.SportType | None = None
    form: forms.SportTypeForm | None = None

    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action == "delete":
            sport_id = request.POST.get("sport_id")
            sport = get_object_or_404(models.SportType, pk=sport_id)
            label = sport.label
            sport.delete()
            messages.success(request, f"Removed {label} from the sports list.")
            return redirect("sportsday:sport-types")
        sport_id = request.POST.get("sport_id")
        instance = models.SportType.objects.filter(pk=sport_id).first() if sport_id else None
        form = forms.SportTypeForm(request.POST, instance=instance)
        if form.is_valid():
            sport = form.save()
            verb = "Updated" if instance else "Added"
            messages.success(request, f"{verb} {sport.label}.")
            return redirect(f"{reverse('sportsday:sport-types')}?sport={sport.pk}")
        selected_instance = instance
    else:
        sport_id = request.GET.get("sport")
        if sport_id:
            selected_instance = models.SportType.objects.filter(pk=sport_id).first()
        form = forms.SportTypeForm(instance=selected_instance)

    if form is None:
        form = forms.SportTypeForm(instance=selected_instance)

    context = {
        "sports": sport_queryset,
        "form": form,
        "selected_sport": selected_instance,
        "active_meet": None,
    }
    return render(request, "sportsday/sport_types_admin.html", context)


def _user_can_quick_edit(user) -> bool:
    """Quick edit is available to all visitors."""

    return True


def _meet_from_request(request: HttpRequest) -> models.Meet:
    """Return the meet referenced by the current request."""

    slug = (request.GET.get("meet") or "").strip()
    if not slug:
        raise Http404("Meet not specified.")
    return get_object_or_404(models.Meet, slug=slug)


def event_reassign(request: HttpRequest) -> HttpResponse:
    """Open access page to quickly move events between meets."""

    events = models.Event.objects.select_related("meet", "sport_type").order_by(
        "meet__name", "name"
    )

    if request.method == "POST":
        updated = 0
        for event in events:
            raw_meet_id = (request.POST.get(f"meet_{event.pk}") or "").strip()
            if not raw_meet_id:
                continue

            try:
                new_meet_id = int(raw_meet_id)
            except ValueError:
                messages.error(request, f"{event.name}: enter a valid meet id.")
                continue

            if new_meet_id == event.meet_id:
                continue

            target_meet = models.Meet.objects.filter(pk=new_meet_id).first()
            if not target_meet:
                messages.error(request, f"{event.name}: meet id {new_meet_id} was not found.")
                continue

            lock_reason = _event_lock_reason(event)
            if lock_reason:
                messages.error(request, f"{event.name}: {lock_reason}")
                continue

            if target_meet.is_locked:
                messages.error(
                    request,
                    f"{event.name}: {target_meet.name} is locked. Unlock it before moving events.",
                )
                continue

            event.meet = target_meet
            event.save(update_fields=["meet"])
            updated += 1

        if updated:
            messages.success(request, f"Updated {updated} event{'s' if updated != 1 else ''}.")
        return redirect("sportsday:event-reassign")

    context = {
        "events": events,
        "active_meet": None,
    }
    return render(request, "sportsday/events_reassign.html", context)


def event_list(request: HttpRequest) -> HttpResponse:
    """List events for a meet with management shortcuts."""

    meet_options = models.Meet.objects.order_by("-date", "name")
    teacher_options = models.Teacher.objects.order_by("last_name", "first_name")
    meet_slug = request.POST.get("meet") if request.method == "POST" else request.GET.get("meet")
    if not meet_slug and meet_options.exists():
        meet_slug = meet_options.first().slug
    active_meet = models.Meet.objects.filter(slug=meet_slug).first() if meet_slug else None

    if request.method == "POST" and request.POST.get("quick_edit") == "1":
        redirect_response = _process_quick_edit_form(request, active_meet)
        if redirect_response is not None:
            return redirect_response

    events = models.Event.objects.none()
    query = request.GET.get("q")
    teacher_filter = request.GET.get("teacher")
    if active_meet:
        events = (
            models.Event.objects.filter(meet=active_meet)
            .select_related("sport_type", "meet")
            .prefetch_related("assigned_teachers")
            .annotate(entries_total=Count("entries", distinct=True))
            .order_by(*SCHEDULE_ORDERING)
        )
        if query:
            events = events.filter(
                Q(name__icontains=query)
                | Q(sport_type__label__icontains=query)
                | Q(grade_min__icontains=query)
                | Q(grade_max__icontains=query)
            )
        if teacher_filter:
            events = events.filter(assigned_teachers__pk=teacher_filter)
        if not request.user.is_staff:
            teacher = _teacher_for_user(request.user)
            if teacher:
                events = events.annotate(
                    is_assigned_to_user=Count(
                        "assigned_teachers",
                        filter=Q(assigned_teachers=teacher),
                        distinct=True,
                    )
                )

    mobile_nav = mobile_nav_active = None
    if active_meet:
        mobile_nav, mobile_nav_active = _build_meet_mobile_nav(active_meet, active="results")

    context = {
        "events": events,
        "meet_options": meet_options,
        "active_meet": active_meet,
        "teacher_options": teacher_options,
        "mobile_nav": mobile_nav,
        "mobile_nav_active": mobile_nav_active,
        "can_quick_edit": _user_can_quick_edit(request.user),
    }

    return render(request, "sportsday/events_list.html", context)


def _process_quick_edit_form(
    request: HttpRequest, active_meet: models.Meet | None
) -> HttpResponse | None:
    """Handle inline updates from the quick edit table."""

    if not _user_can_quick_edit(request.user):
        messages.error(request, "You do not have permission to quick edit events.")
    elif not active_meet:
        messages.error(request, "Select a meet before using quick edit.")
    else:
        updated_count = 0
        for event_id in request.POST.getlist("event_ids"):
            try:
                event = active_meet.events.get(pk=int(event_id))
            except (ValueError, models.Event.DoesNotExist):
                continue

            lock_reason = _event_lock_reason(event)
            if lock_reason:
                messages.error(request, f"{event.name}: {lock_reason}")
                continue

            changed = False

            teacher_ids: list[int] = []
            for value in request.POST.getlist(f"teachers_{event.pk}"):
                try:
                    teacher_ids.append(int(value))
                except (TypeError, ValueError):
                    continue

            existing_teachers = set(
                event.assigned_teachers.values_list("pk", flat=True)
            )
            if set(teacher_ids) != existing_teachers:
                event.assigned_teachers.set(teacher_ids)
                changed = True

            schedule_raw = (request.POST.get(f"schedule_{event.pk}") or "").strip()
            if schedule_raw:
                schedule_candidate = schedule_raw.replace("T", " ")
                try:
                    parsed_dt = datetime.strptime(schedule_candidate, "%Y-%m-%d %H:%M")
                except ValueError:
                    messages.error(
                        request,
                        f"{event.name}: Invalid date and time. Use YYYY-MM-DD HH:MM.",
                    )
                else:
                    if timezone.is_naive(parsed_dt):
                        parsed_dt = timezone.make_aware(
                            parsed_dt, timezone.get_current_timezone()
                        )
                    if event.schedule_dt != parsed_dt:
                        event.schedule_dt = parsed_dt
                        event.save(update_fields=["schedule_dt"])
                        changed = True
            else:
                if event.schedule_dt is not None:
                    event.schedule_dt = None
                    event.save(update_fields=["schedule_dt"])
                    changed = True

            if changed:
                updated_count += 1

        if updated_count:
            messages.success(
                request,
                f"Updated {updated_count} event{'s' if updated_count != 1 else ''}.",
            )

    params: dict[str, str] = {}
    for key in ("meet", "q", "teacher"):
        value = (request.POST.get(key) or "").strip()
        if value:
            params[key] = value

    url = reverse("sportsday:events")
    if params:
        url = f"{url}?{urlencode(params)}"

    return redirect(url)


def quick_assignments(request: HttpRequest) -> HttpResponse:
    """Keyboard-first console to add or remove students from events."""

    meet_slug = request.GET.get("meet") or request.POST.get("meet")
    active_meet = None
    if meet_slug:
        active_meet = models.Meet.objects.filter(slug=meet_slug).first()

    form_state = _extract_quick_assignment_form_state(request)
    selected_student = _resolve_quick_assignment_student(form_state)
    selected_event = _resolve_quick_assignment_event(form_state)
    focus_target = "event" if selected_student else "student"
    error_message = None
    info_message = None
    student_error_message = None

    if request.method == "POST":
        if not selected_student:
            student_error_message = "Select a student before submitting."
            focus_target = "student"
        elif not selected_event:
            error_message = "Select an event before submitting."
            focus_target = "event"
        else:
            lock_reason = _event_lock_reason(selected_event)
            if lock_reason:
                error_message = lock_reason
            elif form_state["mode"] == "remove":
                entry = models.Entry.objects.filter(
                    event=selected_event, student=selected_student
                ).first()
                if not entry:
                    error_message = "That student is not currently in this event."
                else:
                    entry_snapshot = {
                        "round_no": entry.round_no,
                        "heat": entry.heat,
                        "lane_or_order": entry.lane_or_order,
                        "status": entry.status,
                    }
                    entry_pk = entry.pk
                    entry.delete()
                    _append_quick_assignment_log(
                        request,
                        action="remove",
                        student=selected_student,
                        event=selected_event,
                        entry_id=entry_pk,
                        entry_snapshot=entry_snapshot,
                    )
                    info_message = f"Removed {selected_student} from {selected_event.name}."
                    form_state["event_query"] = ""
                    form_state["event_id"] = ""
                    selected_event = None
                    focus_target = "event"
            else:
                entry, created = models.Entry.objects.get_or_create(
                    event=selected_event, student=selected_student
                )
                if not created:
                    error_message = "That student is already assigned to this event."
                else:
                    _append_quick_assignment_log(
                        request,
                        action="add",
                        student=selected_student,
                        event=selected_event,
                        entry_id=entry.pk,
                    )
                    info_message = f"Added {selected_student} to {selected_event.name}."
                    form_state["event_query"] = ""
                    form_state["event_id"] = ""
                    selected_event = None
                    focus_target = "event"

    panel_context = _build_quick_assignment_panel_context(
        request,
        form_state=form_state,
        selected_student=selected_student,
        focus_target=focus_target,
        error_message=error_message,
        info_message=info_message,
        active_meet=active_meet,
        student_error_message=student_error_message,
    )

    if request.headers.get("HX-Request") == "true":
        return render(request, "sportsday/partials/quick_assignments_panel.html", panel_context)

    context = panel_context.copy()
    context["active_meet"] = active_meet
    return render(request, "sportsday/quick_assignments.html", context)


def quick_assignment_student_search(request: HttpRequest) -> HttpResponse:
    """Return student suggestions for the quick assignment console."""

    query = (request.GET.get("q") or request.GET.get("student_query") or "").strip()
    message = None
    students = models.Student.objects.none()

    if len(query) < 2:
        message = "Type at least two characters to search."
    else:
        students = (
            models.Student.objects.filter(
                Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(external_id__icontains=query)
            )
            .order_by("last_name", "first_name")[:20]
        )
        if not students:
            message = "No students found."

    return render(
        request,
        "sportsday/partials/quick_assignments_student_suggestions.html",
        {"students": students, "query": query, "message": message},
    )


def quick_assignment_event_search(request: HttpRequest) -> HttpResponse:
    """Return event suggestions tailored to the selected student."""

    query = (request.GET.get("event_query") or "").strip()
    mode = (request.GET.get("mode") or "add").lower()
    if mode not in {"add", "remove"}:
        mode = "add"

    student: models.Student | None = None
    student_id = (request.GET.get("student_id") or "").strip()
    if student_id:
        try:
            student = models.Student.objects.get(pk=int(student_id))
        except (ValueError, models.Student.DoesNotExist):
            student = None

    events = models.Event.objects.none()
    helper_text = None
    limit = 12

    if mode == "remove" and not student:
        helper_text = "Select a student to see the events they are entered in."
    elif not query:
        helper_text = "Start typing to search events."
    else:
        events_qs = models.Event.objects.filter(name__icontains=query).select_related(
            "meet", "sport_type"
        )
        meet_slug = (request.GET.get("meet") or "").strip()
        if meet_slug:
            events_qs = events_qs.filter(meet__slug=meet_slug)
        if student and mode == "remove":
            events_qs = events_qs.filter(entries__student=student).distinct()
            events = events_qs.order_by("name")[:limit]
        elif student and mode == "add":
            existing_ids = set(
                models.Entry.objects.filter(student=student).values_list("event_id", flat=True)
            )
            filtered: list[models.Event] = []
            for event in events_qs.order_by("name")[: 4 * limit]:
                if event.pk in existing_ids:
                    continue
                if not event.grade_allows(student.grade):
                    continue
                if not event.gender_allows(student.gender):
                    continue
                filtered.append(event)
                if len(filtered) >= limit:
                    break
            events = filtered
            if not events:
                helper_text = "No eligible events match this search."
        else:
            events = events_qs.order_by("name")[:limit]

    return render(
        request,
        "sportsday/partials/quick_assignments_event_suggestions.html",
        {
            "events": events,
            "helper_text": helper_text,
            "mode": mode,
            "student": student,
            "query": query,
        },
    )


def quick_assignments_undo(request: HttpRequest) -> HttpResponse:
    """Undo a previous add/remove action from the live changelog."""

    meet_slug = request.POST.get("meet") or request.GET.get("meet")
    active_meet = None
    if meet_slug:
        active_meet = models.Meet.objects.filter(slug=meet_slug).first()

    form_state = _extract_quick_assignment_form_state(request)
    selected_student = _resolve_quick_assignment_student(form_state)
    focus_target = "event" if selected_student else "student"
    error_message = None
    info_message = None

    change_id = (request.POST.get("change_id") or "").strip()
    entries = _get_quick_assignment_log(request)
    target = next((entry for entry in entries if entry.get("id") == change_id), None)
    if not target:
        error_message = "That change could not be found."
    elif target.get("undone"):
        error_message = "This change has already been undone."
    else:
        student = models.Student.objects.filter(pk=target.get("student_id")).first()
        event = models.Event.objects.filter(pk=target.get("event_id")).first()
        if not student or not event:
            error_message = "The student or event no longer exists."
        else:
            if target.get("action") == "add":
                deleted = models.Entry.objects.filter(
                    pk=target.get("entry_id"), event=event, student=student
                ).delete()[0]
                if not deleted:
                    error_message = "The entry has already been removed."
                else:
                    info_message = f"Undo complete: removed {student} from {event.name}."
            else:
                snapshot = target.get("entry_snapshot") or {}
                defaults = {
                    "round_no": snapshot.get("round_no") or 1,
                    "heat": snapshot.get("heat") or 1,
                    "lane_or_order": snapshot.get("lane_or_order"),
                    "status": snapshot.get(
                        "status", models.Entry.Status.CONFIRMED
                    ),
                }
                entry, created = models.Entry.objects.get_or_create(
                    event=event, student=student, defaults=defaults
                )
                if not created:
                    for field, value in defaults.items():
                        setattr(entry, field, value)
                    entry.save(update_fields=list(defaults.keys()))
                target["entry_id"] = entry.pk
                info_message = f"Undo complete: restored {student} to {event.name}."

            if not error_message:
                target["undone"] = True
                target["undo_timestamp"] = timezone.now().isoformat()
                _save_quick_assignment_log(request, entries)

    panel_context = _build_quick_assignment_panel_context(
        request,
        form_state=form_state,
        selected_student=selected_student,
        focus_target=focus_target,
        error_message=error_message,
        info_message=info_message,
        active_meet=active_meet,
        student_error_message=None,
    )
    return render(request, "sportsday/partials/quick_assignments_panel.html", panel_context)


def event_create(request: HttpRequest) -> HttpResponse:
    """Create a standalone event for a meet."""

    teacher_qs = models.Teacher.objects.order_by("last_name", "first_name")
    meet_options = models.Meet.objects.order_by("name")
    selected_meet: models.Meet | None = None
    initial_meet = request.GET.get("meet") or request.POST.get("meet")
    if initial_meet:
        selected_meet = (
            models.Meet.objects.filter(slug=initial_meet).first()
            or models.Meet.objects.filter(pk=initial_meet).first()
        )

    form = forms.EventConfigForm(request.POST or None, teacher_queryset=teacher_qs)
    if request.method == "POST":
        meet_identifier = request.POST.get("meet")
        meet = (
            models.Meet.objects.filter(pk=meet_identifier).first()
            or models.Meet.objects.filter(slug=meet_identifier).first()
        )
        if not meet:
            form.add_error(None, "Select a meet for this event.")
        else:
            selected_meet = meet
        if form.is_valid():
            event = form.save(commit=False)
            event.meet = meet
            event.save()
            form.save_m2m()
            messages.success(request, f"Created event {event.name}.")
            return redirect(f"{reverse('sportsday:events')}?meet={event.meet.slug}")

    grade_options, selected_grade_values = _event_form_grade_choices(form)
    sport_type_meta = {
        str(sport.pk): {
            "label": sport.label,
            "archetype": sport.archetype,
            "archetype_label": sport.get_archetype_display(),
        }
        for sport in models.SportType.objects.all()
    }

    context = {
        "form": form,
        "meet_options": meet_options,
        "selected_meet": selected_meet,
        "grade_options": grade_options,
        "selected_grade_values": selected_grade_values,
        "is_create": True,
        "sport_type_meta": sport_type_meta,
        "selected_sport_type_id": form["sport_type"].value() or "",
        "selected_sport_type_meta": sport_type_meta.get(str(form["sport_type"].value() or "")),
    }
    return render(request, "sportsday/event_form.html", context)


def event_update(request: HttpRequest, pk: int) -> HttpResponse:
    """Edit an existing event."""

    event = get_object_or_404(models.Event.objects.select_related("meet"), pk=pk)
    teacher_qs = models.Teacher.objects.order_by("last_name", "first_name")
    meet_options = models.Meet.objects.order_by("name")
    form = forms.EventConfigForm(request.POST or None, instance=event, teacher_queryset=teacher_qs)
    if request.method == "POST":
        meet_identifier = request.POST.get("meet")
        meet = (
            models.Meet.objects.filter(pk=meet_identifier).first()
            or models.Meet.objects.filter(slug=meet_identifier).first()
        )
        if not meet:
            form.add_error(None, "Select a meet for this event.")
        else:
            selected_meet = meet
        if form.is_valid():
            event = form.save(commit=False)
            event.meet = meet
            event.save()
            form.save_m2m()
            messages.success(request, f"Updated event {event.name}.")
            return redirect(f"{reverse('sportsday:events')}?meet={event.meet.slug}")

    grade_options, selected_grade_values = _event_form_grade_choices(form)
    sport_type_meta = {
        str(sport.pk): {
            "label": sport.label,
            "archetype": sport.archetype,
            "archetype_label": sport.get_archetype_display(),
        }
        for sport in models.SportType.objects.all()
    }

    context = {
        "form": form,
        "meet_options": meet_options,
        "selected_meet": event.meet,
        "event": event,
        "grade_options": grade_options,
        "selected_grade_values": selected_grade_values,
        "is_create": False,
        "sport_type_meta": sport_type_meta,
        "selected_sport_type_id": form["sport_type"].value() or "",
        "selected_sport_type_meta": sport_type_meta.get(str(form["sport_type"].value() or "")),
    }
    return render(request, "sportsday/event_form.html", context)


@require_POST
def event_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Delete an event if it is not locked."""

    event = get_object_or_404(models.Event.objects.select_related("meet"), pk=pk)
    lock_reason = _event_lock_reason(event)
    if lock_reason:
        messages.error(request, lock_reason)
        return redirect("sportsday:events")

    event_name = event.name
    meet_slug = event.meet.slug
    with transaction.atomic():
        models.Result.objects.filter(entry__event=event).delete()
        event.entries.all().delete()
        event.delete()
    messages.success(request, f"Deleted event {event_name}.")
    return redirect(f"{reverse('sportsday:events')}?meet={meet_slug}")


def event_participants(request: HttpRequest, pk: int) -> HttpResponse:
    """Dual-list interface to assign participants to an event."""

    event = get_object_or_404(models.Event.objects.select_related("meet", "sport_type"), pk=pk)
    lock_reason = _event_lock_reason(event)
    round_no = 1
    assigned_entries = list(
        event.entries.filter(round_no=round_no)
        .select_related("student")
        .order_by("lane_or_order", "heat", "student__last_name", "student__first_name")
    )
    assigned_ids = [entry.student_id for entry in assigned_entries]
    eligible_students = list(
        _eligible_students_queryset(event, search_query="", round_no=round_no, include_assigned=True)
    )
    available_students = [student for student in eligible_students if student.pk not in assigned_ids]

    selected_student_ids = {entry.student_id for entry in assigned_entries}
    houses = sorted({(student.house or "Unassigned") for student in eligible_students})
    grades = sorted(
        {(student.grade or "Unassigned") for student in eligible_students},
        key=_grade_option_sort_key,
    )
    initial_house_counts: Counter[str] = Counter()
    initial_grade_counts: Counter[str] = Counter()
    for entry in assigned_entries:
        house = entry.student.house or "Unassigned"
        grade = entry.student.grade or "Unassigned"
        initial_house_counts[house] += 1
        initial_grade_counts[grade] += 1
    house_summary = [(house, initial_house_counts.get(house, 0)) for house in houses]
    grade_summary = [(grade, initial_grade_counts.get(grade, 0)) for grade in grades]

    if request.method == "POST":
        if lock_reason:
            messages.error(request, lock_reason)
            return redirect("sportsday:event-participants", pk=event.pk)

        selected_ids = [int(value) for value in request.POST.getlist("participants") if value.isdigit()]
        selected_set = set(selected_ids)
        students_map = {student.pk: student for student in models.Student.objects.filter(pk__in=selected_ids)}
        errors: list[str] = []

        if len(selected_ids) != len(students_map):
            errors.append("One or more selected students could not be found.")

        if not event.sport_type.supports_heats and len(selected_ids) > event.capacity:
            errors.append(f"This event can only host {event.capacity} participants.")

        assigned_lookup = {entry.student_id: entry for entry in assigned_entries}
        meet_limit = event.meet.max_events_per_student or 0
        if meet_limit:
            existing_counts = {
                row["student_id"]: row["total"]
                for row in models.Entry.objects.filter(event__meet=event.meet, student_id__in=selected_set)
                .exclude(event=event)
                .values("student_id")
                .annotate(total=Count("pk"))
            }
        else:
            existing_counts = {}

        for student_id in selected_ids:
            student = students_map.get(student_id)
            if not student:
                continue
            if not student.is_active:
                errors.append(f"{student} is inactive.")
                continue
            if not event.grade_allows(student.grade):
                errors.append(f"{student} is outside the grade range for this event.")
            if not event.gender_allows(student.gender):
                errors.append(f"{student} does not match the gender limit for this event.")
            if meet_limit:
                total_entries = existing_counts.get(student_id, 0) + 1
                if total_entries > meet_limit:
                    errors.append(f"{student} exceeds the {meet_limit} event limit for this meet.")

        if errors:
            for message_text in errors:
                messages.error(request, message_text)
        else:
            for entry in assigned_entries:
                if entry.student_id not in selected_set:
                    entry.delete()

            assigned_entries = list(
                event.entries.filter(round_no=round_no)
                .select_related("student")
                .order_by("lane_or_order", "heat", "student__last_name", "student__first_name")
            )
            assigned_lookup = {entry.student_id: entry for entry in assigned_entries}
            ordered_entries: list[models.Entry] = []

            for student_id in selected_ids:
                student = students_map.get(student_id)
                if not student:
                    continue
                entry = assigned_lookup.get(student_id)
                if entry is None:
                    entry = models.Entry.objects.create(
                        event=event,
                        student=student,
                        round_no=round_no,
                        heat=1,
                    )
                ordered_entries.append(entry)

            _apply_lane_assignments(event, ordered_entries)
            messages.success(request, "Updated event participants.")
            return redirect("sportsday:event-participants", pk=event.pk)

    context = {
        "event": event,
        "eligible_students": eligible_students,
        "available_students": available_students,
        "assigned_entries": assigned_entries,
        "assigned_student_ids": selected_student_ids,
        "houses": houses,
        "grades": grades,
        "house_summary": house_summary,
        "grade_summary": grade_summary,
        "selected_count": len(assigned_entries),
        "lock_reason": lock_reason,
    }
    return render(request, "sportsday/event_participants.html", context)


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
    """Lightweight event cards used in dashboard previews."""

    meet_slug = request.GET.get("meet")
    events = models.Event.objects.select_related("sport_type", "meet")
    if meet_slug:
        events = events.filter(meet__slug=meet_slug)
    events = events.order_by(*SCHEDULE_ORDERING)[:10]
    return render(request, "sportsday/partials/events_table.html", {"events": events})


def manage_event(request: HttpRequest, event_id: int) -> HttpResponse:
    """Unified results entry screen for track and field events."""

    event = get_object_or_404(
        models.Event.objects.select_related("meet", "sport_type")
        .prefetch_related("assigned_teachers"),
        pk=event_id,
    )
    entries = list(
        event.entries.select_related("student", "result")
        .prefetch_related("attempts")
        .order_by("student__last_name", "student__first_name")
    )

    manage_url = reverse("sportsday:manage-event", kwargs={"event_id": event.pk})

    archetype = event.sport_type.archetype
    mode = "track" if archetype.startswith("TRACK") or archetype == models.SportType.Archetype.RANK_ONLY else "field"
    allow_time_input = archetype == models.SportType.Archetype.TRACK_TIME
    attempt_count = event.attempts or event.sport_type.default_attempts or 1
    attempt_count = max(1, attempt_count)
    attempt_range = list(range(1, attempt_count + 1))

    lock_reason = _event_lock_reason(event)
    can_post = True

    def _build_context(rows: list[dict[str, object]], errors: list[str] | None = None) -> dict[str, object]:
        return {
            "event": event,
            "entries": rows,
            "mode": mode,
            "allow_time_input": allow_time_input,
            "attempt_count": attempt_count,
            "attempt_range": attempt_range,
            "lock_reason": lock_reason,
            "form_errors": errors or [],
            "is_rank_only": archetype == models.SportType.Archetype.RANK_ONLY,
            "can_edit": can_post and not lock_reason,
            "can_unlock": can_post and event.is_locked and not event.meet.is_locked,
            "active_meet": event.meet,
        }

    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action == "replace":
            if lock_reason:
                messages.error(request, lock_reason)
                return redirect(manage_url)
            entry_id_raw = (request.POST.get("entry_id") or "").strip()
            student_id_raw = (request.POST.get("replacement_student") or "").strip()
            try:
                entry_id = int(entry_id_raw)
            except (TypeError, ValueError):
                messages.error(request, "Select a participant to replace.")
                return redirect(manage_url)
            if not student_id_raw:
                messages.error(request, "Choose a replacement student before saving.")
                return redirect(manage_url)
            try:
                replacement_id = int(student_id_raw)
            except (TypeError, ValueError):
                messages.error(request, "Select a valid replacement student.")
                return redirect(manage_url)
            try:
                entry = event.entries.select_related("student").get(pk=entry_id)
            except models.Entry.DoesNotExist:
                messages.error(request, "Entry could not be found for this event.")
                return redirect(manage_url)
            old_student = entry.student
            try:
                replacement = models.Student.objects.get(pk=replacement_id)
            except models.Student.DoesNotExist:
                messages.error(request, "Replacement student could not be found.")
                return redirect(manage_url)

            if replacement.pk == old_student.pk:
                messages.info(request, "The selected student is already assigned to this entry.")
                return redirect(manage_url)

            if not replacement.is_active:
                messages.error(request, "Inactive students cannot be assigned to events.")
                return redirect(manage_url)

            original_house = (old_student.house or "").strip()
            original_gender = (old_student.gender or "").strip()
            if (replacement.house or "").strip() != original_house:
                messages.error(
                    request,
                    "Replacement students must belong to the same house as the original participant.",
                )
                return redirect(manage_url)
            if (replacement.gender or "").strip() != original_gender:
                messages.error(
                    request,
                    "Replacement students must match the original participant's gender.",
                )
                return redirect(manage_url)

            if not event.grade_allows(replacement.grade):
                messages.error(
                    request,
                    "Replacement students must fall within the event's allowed grade range.",
                )
                return redirect(manage_url)
            if not event.gender_allows(replacement.gender):
                messages.error(request, "Replacement student does not meet the event's gender rules.")
                return redirect(manage_url)

            if (
                event.entries.exclude(pk=entry.pk)
                .filter(student_id=replacement.pk)
                .exists()
            ):
                messages.error(request, "That student already has an entry in this event.")
                return redirect(manage_url)

            previous_status = entry.status
            try:
                with transaction.atomic():
                    entry.student = replacement
                    entry.status = models.Entry.Status.CONFIRMED
                    entry.save(update_fields=["student", "status"])
                    models.Attempt.objects.filter(entry=entry).delete()
                    models.Result.objects.filter(entry=entry).delete()
            except ValidationError as exc:
                entry.student = old_student
                entry.status = previous_status
                message_dict = getattr(exc, "message_dict", {})
                error_messages: list[str] = []
                for messages_list in message_dict.values():
                    error_messages.extend(messages_list)
                deduped_messages = list(dict.fromkeys(error_messages))
                messages.error(
                    request,
                    " ".join(deduped_messages) or str(exc),
                )
                return redirect(manage_url)

            messages.success(
                request,
                f"Replaced {old_student} with {replacement}.",
            )
            return redirect(manage_url)

        if lock_reason:
            messages.error(request, lock_reason)
            return redirect(manage_url)
        if mode == "track":
            rows, errors = _track_rows_from_post(entries, request.POST, allow_time=allow_time_input)
        else:
            rows, errors = _field_rows_from_post(
                entries,
                request.POST,
                attempt_count=attempt_count,
                archetype=archetype,
            )
        _annotate_replacement_options(rows, event)
        if errors:
            for message_text in errors:
                messages.error(request, message_text)
            context = _build_context(rows, errors)
            return render(request, "sportsday/manage_event.html", context)

        with transaction.atomic():
            if mode == "track":
                for row in rows:
                    entry: models.Entry = row["entry"]
                    status: str = row.get("status") or models.Entry.Status.CONFIRMED
                    if entry.status != status:
                        entry.status = status
                        entry.save(update_fields=["status"])
                    result, _ = models.Result.objects.get_or_create(entry=entry, defaults={"finalized": True})
                    if status != models.Entry.Status.CONFIRMED:
                        result.rank = None
                        result.best_value = None
                    else:
                        result.rank = row.get("rank_value")
                        result.best_value = row.get("parsed_time") if allow_time_input else None
                    result.finalized = True
                    result.save()
                    if status != models.Entry.Status.CONFIRMED or not allow_time_input or row.get("parsed_time") is None:
                        entry.attempts.all().delete()
                    else:
                        models.Attempt.objects.update_or_create(
                            entry=entry,
                            attempt_no=1,
                            defaults={
                                "time_seconds": row.get("parsed_time"),
                                "distance_m": None,
                                "count": None,
                                "valid": True,
                            },
                        )
                        entry.attempts.exclude(attempt_no=1).delete()
            else:
                valid_attempt_numbers = list(range(1, attempt_count + 1))
                for row in rows:
                    entry: models.Entry = row["entry"]
                    status: str = row.get("status") or models.Entry.Status.CONFIRMED
                    if entry.status != status:
                        entry.status = status
                        entry.save(update_fields=["status"])
                    result, _ = models.Result.objects.get_or_create(entry=entry, defaults={"finalized": True})
                    if status != models.Entry.Status.CONFIRMED:
                        result.rank = None
                        result.best_value = None
                    else:
                        result.rank = row.get("position")
                        result.best_value = row.get("best_value")
                    result.finalized = True
                    result.save()
                    for attempt in row.get("attempts", []):
                        decimal_value: Decimal | None = attempt.get("decimal")
                        count_value: int | None = attempt.get("count")
                        valid = decimal_value is not None
                        models.Attempt.objects.update_or_create(
                            entry=entry,
                            attempt_no=attempt["index"],
                            defaults={
                                "time_seconds": None,
                                "distance_m": decimal_value if archetype == models.SportType.Archetype.FIELD_DISTANCE and valid else None,
                                "count": count_value if archetype == models.SportType.Archetype.FIELD_COUNT and valid else None,
                                "valid": valid,
                            },
                        )
                    entry.attempts.exclude(attempt_no__in=valid_attempt_numbers).delete()

        action = request.POST.get("action", "save")
        if action == "lock":
            event.is_locked = True
            event.save(update_fields=["is_locked"])
            messages.success(request, "Event marked complete.")
        else:
            messages.success(request, "Results saved.")
        return redirect(manage_url)

    if mode == "track":
        rows = _track_rows_from_db(entries, allow_time=allow_time_input)
    else:
        rows = _field_rows_from_db(entries, attempt_count=attempt_count, archetype=archetype)
    _annotate_replacement_options(rows, event)

    context = _build_context(rows)
    return render(request, "sportsday/manage_event.html", context)


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

    default_redirect = reverse("sportsday:manage-event", kwargs={"event_id": event.pk})
    if request.headers.get("HX-Request"):
        default_redirect = reverse("sportsday:event-detail", kwargs={"pk": event.pk})

    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        redirect_url = next_url
    else:
        redirect_url = default_redirect

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


def _eligible_students_queryset(
    event: models.Event,
    search_query: str,
    round_no: int,
    *,
    include_assigned: bool = False,
):
    """Return the queryset used to select eligible students for an event."""

    queryset = models.Student.objects.filter(is_active=True)
    if event.gender_limit != models.Event.GenderLimit.MIXED:
        queryset = queryset.filter(gender=event.gender_limit)
    if search_query:
        queryset = queryset.filter(
            Q(first_name__icontains=search_query)
            | Q(last_name__icontains=search_query)
            | Q(external_id__icontains=search_query)
        )
    if not include_assigned:
        assigned_ids = event.entries.filter(round_no=round_no).values_list("student_id", flat=True)
        queryset = queryset.exclude(pk__in=assigned_ids)
    queryset = queryset.order_by("last_name", "first_name").distinct()
    grade_values = queryset.values("pk", "grade")
    allowed_ids = [row["pk"] for row in grade_values if event.grade_allows(row["grade"])]
    if allowed_ids:
        queryset = queryset.filter(pk__in=allowed_ids)
    else:
        queryset = queryset.none()
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


def export_events_overview(request: HttpRequest) -> HttpResponse:
    """Printable directory containing each event with assigned marshals."""

    meet = _meet_from_request(request)
    entries_prefetch = Prefetch(
        "entries",
        queryset=(
            models.Entry.objects.filter(round_no=1)
            .select_related("student")
            .order_by("student__last_name", "student__first_name", "pk")
        ),
        to_attr="export_entries",
    )
    events = (
        meet.events.select_related("sport_type")
        .prefetch_related("assigned_teachers", entries_prefetch)
        .order_by(*SCHEDULE_ORDERING)
    )

    payload: list[dict[str, object]] = []
    for event in events:
        teachers = list(event.assigned_teachers.all())
        participants: list[models.Student] = []
        seen: set[int] = set()
        for entry in getattr(event, "export_entries", []):
            if entry.student_id in seen or entry.student is None:
                continue
            seen.add(entry.student_id)
            participants.append(entry.student)
        payload.append(
            {
                "event": event,
                "teachers": teachers,
                "participants": participants,
            }
        )

    context = {"meet": meet, "events_payload": payload}
    return render(request, "sportsday/printables/events_overview.html", context)


def export_teacher_allocations(request: HttpRequest) -> HttpResponse:
    """Printable teacher allocation list for the selected meet."""

    meet = _meet_from_request(request)
    events = (
        meet.events.select_related("sport_type")
        .prefetch_related("assigned_teachers")
        .order_by(*SCHEDULE_ORDERING)
    )

    allocations: list[dict[str, object]] = []
    for event in events:
        event_url = request.build_absolute_uri(
            reverse("sportsday:manage-event", kwargs={"event_id": event.pk})
        )
        teachers = list(event.assigned_teachers.all())
        if teachers:
            for teacher in teachers:
                allocations.append({"event": event, "teacher": teacher, "url": event_url})
        else:
            allocations.append({"event": event, "teacher": None, "url": event_url})

    context = {"meet": meet, "allocations": allocations}
    return render(request, "sportsday/printables/teacher_allocations.html", context)


def export_event_schedule(request: HttpRequest) -> HttpResponse:
    """Printable day schedule ordered by event time."""

    meet = _meet_from_request(request)
    events = (
        meet.events.select_related("sport_type")
        .prefetch_related("assigned_teachers")
        .order_by(*SCHEDULE_ORDERING)
    )

    scheduled: list[dict[str, object]] = []
    unscheduled: list[dict[str, object]] = []
    for event in events:
        teachers = ", ".join(str(teacher) for teacher in event.assigned_teachers.all()) or "Unassigned"
        item = {
            "event": event,
            "teachers": teachers,
        }
        if event.schedule_dt:
            scheduled.append(item)
        else:
            unscheduled.append(item)

    context = {
        "meet": meet,
        "scheduled_events": scheduled,
        "unscheduled_events": unscheduled,
    }
    return render(request, "sportsday/printables/event_schedule.html", context)


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


def export_results_ticker(request: HttpRequest) -> HttpResponse:
    """Printable ticker-style view of live event results."""

    meet = _meet_from_request(request)
    results_prefetch = Prefetch(
        "entries",
        queryset=(
            models.Entry.objects.filter(
                round_no=F("event__rounds_total"),
                result__isnull=False,
            )
            .select_related("student", "result")
            .order_by(
                "result__rank",
                "student__last_name",
                "student__first_name",
                "pk",
            )
        ),
        to_attr="result_entries",
    )

    events = (
        meet.events.select_related("sport_type")
        .prefetch_related("assigned_teachers", results_prefetch)
        .order_by(*SCHEDULE_ORDERING)
    )

    events_payload: list[dict[str, object]] = []
    for event in events:
        teacher_labels = [str(teacher) for teacher in event.assigned_teachers.all()]
        entries = [
            entry
            for entry in getattr(event, "result_entries", [])
            if getattr(entry, "result", None) is not None
        ]
        entries.sort(
            key=lambda entry: (
                entry.result.rank if entry.result.rank is not None else 9999,
                (entry.student.last_name or "").lower(),
                (entry.student.first_name or "").lower(),
            )
        )
        rows = []
        for entry in entries:
            result = entry.result
            rows.append(
                {
                    "rank": result.rank,
                    "student_name": f"{entry.student.first_name} {entry.student.last_name}",
                    "house": entry.student.house or "—",
                    "grade": entry.student.grade or "—",
                    "performance": _format_result_value(event, result.best_value),
                    "status": entry.get_status_display(),
                    "finalized": result.finalized,
                }
            )
        events_payload.append(
            {
                "event": event,
                "teachers": teacher_labels,
                "results": rows,
            }
        )

    context = {
        "meet": meet,
        "events_payload": events_payload,
        "generated_at": timezone.localtime(),
        "refresh_default": 30,
    }
    return render(request, "sportsday/printables/results_ticker.html", context)


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
