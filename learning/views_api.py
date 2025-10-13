import json
from io import BytesIO

from django.contrib.auth.decorators import login_required
from django.http import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    JsonResponse,
)
from django.db.models import Case, Count, Sum, When
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST
from xml.sax.saxutils import escape

from datetime import datetime
from zipfile import ZipFile

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
from .models import (
    Assignment,
    AssignmentAttempt,
    AssignmentProgress,
    Class,
    ClubAttendance,
    Student,
)
from .services.attendance import add_student_to_session, get_or_create_session


def _column_letter(index: int) -> str:
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters or "A"


def _render_sheet_xml(headers, rows):
    data_rows = [headers] + rows
    max_cols = max((len(row) for row in data_rows), default=len(headers) or 1)
    total_rows = len(data_rows)
    if max_cols <= 0:
        max_cols = 1
    if total_rows <= 0:
        total_rows = 1

    last_cell = f"{_column_letter(max_cols)}{total_rows}"
    dimension_ref = f"A1:{last_cell}"

    sheet_rows = []
    for row_idx, row in enumerate(data_rows, start=1):
        cells_xml = []
        for col_idx, value in enumerate(row, start=1):
            cell_ref = f"{_column_letter(col_idx)}{row_idx}"
            if value is None or value == "":
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells_xml.append(f"<c r=\"{cell_ref}\"><v>{value}</v></c>")
            else:
                text = escape(str(value)).replace("\n", "&#10;")
                cells_xml.append(
                    f"<c r=\"{cell_ref}\" t=\"inlineStr\"><is><t>{text}</t></is></c>"
                )
        sheet_rows.append(f"<row r=\"{row_idx}\">{''.join(cells_xml)}</row>")

    sheet_data = "".join(sheet_rows)
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" "
        "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\">"
        f"<dimension ref=\"{dimension_ref}\"/>"
        "<sheetViews><sheetView workbookViewId=\"0\"/></sheetViews>"
        "<sheetFormatPr defaultRowHeight=\"15\"/>"
        f"<sheetData>{sheet_data}</sheetData>"
        "</worksheet>"
    )


def _build_xlsx(headers, rows, sheet_name="Progress") -> bytes:
    created = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    core_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<cp:coreProperties xmlns:cp=\"http://schemas.openxmlformats.org/package/2006/metadata/core-properties\" "
        "xmlns:dc=\"http://purl.org/dc/elements/1.1/\" xmlns:dcterms=\"http://purl.org/dc/terms/\" "
        "xmlns:dcmitype=\"http://purl.org/dc/dcmitype/\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\">"
        "<dc:creator>Pavonify</dc:creator>"
        "<cp:lastModifiedBy>Pavonify</cp:lastModifiedBy>"
        f"<dcterms:created xsi:type=\"dcterms:W3CDTF\">{created}</dcterms:created>"
        f"<dcterms:modified xsi:type=\"dcterms:W3CDTF\">{created}</dcterms:modified>"
        "</cp:coreProperties>"
    )

    app_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Properties xmlns=\"http://schemas.openxmlformats.org/officeDocument/2006/extended-properties\" "
        "xmlns:vt=\"http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes\">"
        "<Application>Microsoft Excel</Application>"
        "</Properties>"
    )

    content_types_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
        "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
        "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
        "<Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/>"
        "<Override PartName=\"/xl/worksheets/sheet1.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>"
        "<Override PartName=\"/docProps/core.xml\" ContentType=\"application/vnd.openxmlformats-package.core-properties+xml\"/>"
        "<Override PartName=\"/docProps/app.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.extended-properties+xml\"/>"
        "<Override PartName=\"/xl/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml\"/>"
        "</Types>"
    )

    rels_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"xl/workbook.xml\"/>"
        "<Relationship Id=\"rId2\" Type=\"http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties\" Target=\"docProps/core.xml\"/>"
        "<Relationship Id=\"rId3\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties\" Target=\"docProps/app.xml\"/>"
        "</Relationships>"
    )

    workbook_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" "
        "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\">"
        "<fileVersion appName=\"xl\"/>"
        "<workbookPr/>"
        "<bookViews><workbookView/></bookViews>"
        f"<sheets><sheet name=\"{escape(sheet_name)}\" sheetId=\"1\" r:id=\"rId1\"/></sheets>"
        "</workbook>"
    )

    workbook_rels_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet1.xml\"/>"
        "<Relationship Id=\"rId2\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" Target=\"styles.xml\"/>"
        "</Relationships>"
    )

    styles_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<styleSheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">"
        "<fonts count=\"1\"><font><sz val=\"11\"/><color theme=\"1\"/><name val=\"Calibri\"/><family val=\"2\"/></font></fonts>"
        "<fills count=\"2\"><fill><patternFill patternType=\"none\"/></fill><fill><patternFill patternType=\"gray125\"/></fill></fills>"
        "<borders count=\"1\"><border><left/><right/><top/><bottom/><diagonal/></border></borders>"
        "<cellStyleXfs count=\"1\"><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\"/></cellStyleXfs>"
        "<cellXfs count=\"1\"><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\"/></cellXfs>"
        "<cellStyles count=\"1\"><cellStyle name=\"Normal\" xfId=\"0\" builtinId=\"0\"/></cellStyles>"
        "</styleSheet>"
    )

    sheet_xml = _render_sheet_xml(headers, rows)

    buffer = BytesIO()
    with ZipFile(buffer, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("docProps/core.xml", core_xml)
        zf.writestr("docProps/app.xml", app_xml)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        zf.writestr("xl/styles.xml", styles_xml)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)

    buffer.seek(0)
    return buffer.getvalue()


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
@require_GET
def api_export_progress(request, assignment_id):
    assignment = get_object_or_404(
        Assignment.objects.select_related("class_assigned"), id=assignment_id
    )
    if not _teacher_can_view(request.user, assignment):
        return HttpResponseForbidden()

    progress_qs = (
        AssignmentProgress.objects.filter(assignment=assignment)
        .select_related("student")
        .order_by("student__last_name", "student__first_name")
    )

    attempt_stats = (
        AssignmentAttempt.objects
        .filter(assignment=assignment)
        .values("student_id")
        .annotate(
            attempts=Count("id"),
            correct=Coalesce(Sum(Case(When(is_correct=True, then=1), default=0)), 0),
        )
    )
    stats_map = {row["student_id"]: row for row in attempt_stats}

    mastery_map = {
        entry["student_id"]: entry
        for entry in student_mastery(assignment_id)
    }

    student_rows = {}
    for progress in progress_qs:
        name = f"{progress.student.first_name} {progress.student.last_name}".strip()
        student_rows[progress.student_id] = {
            "name": name or progress.student.username,
            "username": progress.student.username,
            "points": progress.points_earned,
            "completed": "Yes" if progress.completed else "No",
            "time_spent": str(progress.time_spent) if progress.time_spent else "",
        }

    # Ensure we include students who have attempts but no progress row yet.
    missing_ids = [sid for sid in stats_map.keys() if sid not in student_rows]
    if missing_ids:
        for student in Student.objects.filter(id__in=missing_ids):
            name = f"{student.first_name} {student.last_name}".strip()
            student_rows[student.id] = {
                "name": name or student.username,
                "username": student.username,
                "points": "",
                "completed": "",
                "time_spent": "",
            }

    headers = [
        "Student",
        "Username",
        "Points Earned",
        "Completed",
        "Time Spent",
        "Total Attempts",
        "Correct",
        "Accuracy (%)",
        "Words Aced",
        "Needs Practice",
    ]
    rows = []

    for student_id, row in sorted(
        student_rows.items(), key=lambda item: item[1]["name"].lower()
    ):
        stats = stats_map.get(student_id, {})
        attempts = stats.get("attempts", 0) or 0
        correct = stats.get("correct", 0) or 0
        accuracy = round((correct / attempts * 100), 1) if attempts else 0.0

        mastery = mastery_map.get(student_id, {})
        words_aced = ", ".join(mastery.get("words_aced", []))
        needs_practice = ", ".join(mastery.get("needs_practice", []))

        rows.append(
            [
                row["name"],
                row["username"],
                row.get("points", ""),
                row.get("completed", ""),
                row.get("time_spent", ""),
                attempts,
                correct,
                accuracy,
                words_aced,
                needs_practice,
            ]
        )

    workbook_bytes = _build_xlsx(headers, rows, sheet_name="Progress")

    safe_name = slugify(assignment.name) or f"assignment-{assignment_id}"
    filename = f"{safe_name}-progress.xlsx"

    response = HttpResponse(
        workbook_bytes,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


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


@require_POST
@login_required
def api_add_one_off_attendance(request, class_id):
    """Allow a teacher to add a one-off attendee to a club session."""

    if not getattr(request.user, "is_teacher", False):
        return HttpResponseForbidden("Only teachers can record attendance.")

    club = get_object_or_404(Class, id=class_id)
    if not club.teachers.filter(id=request.user.id).exists():
        return HttpResponseForbidden("You are not assigned to this club.")

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)

    student_id = payload.get("student_id")
    session_date_raw = payload.get("session_date")
    status = payload.get("status", ClubAttendance.STATUS_PRESENT)

    if not student_id or not session_date_raw:
        return JsonResponse(
            {"error": "student_id and session_date are required."}, status=400
        )

    try:
        session_date = datetime.strptime(session_date_raw, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return JsonResponse(
            {"error": "session_date must be in YYYY-MM-DD format."}, status=400
        )

    valid_statuses = {choice[0] for choice in ClubAttendance.STATUS_CHOICES}
    if status not in valid_statuses:
        return JsonResponse({"error": "Invalid attendance status."}, status=400)

    student = get_object_or_404(Student, id=student_id)
    if student.school_id != club.school_id:
        return JsonResponse(
            {"error": "Student does not belong to this school."}, status=400
        )

    session, _ = get_or_create_session(club, session_date, created_by=request.user)
    attendance, created = add_student_to_session(
        session, student, status=status
    )

    original_club_id = (
        str(attendance.original_club_id) if attendance.original_club_id else None
    )

    return JsonResponse(
        {
            "attendance_id": attendance.id,
            "session_id": session.id,
            "status": attendance.status,
            "is_one_off": attendance.is_one_off,
            "original_club_id": original_club_id,
            "session_date": session.session_date.isoformat(),
        },
        status=201 if created else 200,
    )
