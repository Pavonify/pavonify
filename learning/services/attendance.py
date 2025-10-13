"""Utilities for managing club attendance sessions."""

from __future__ import annotations

from datetime import date
from typing import Tuple

from django.db import transaction

from learning.models import (
    Class,
    ClubAttendance,
    ClubSession,
    Student,
    StudentCalendarEntry,
    TeacherNotification,
    User,
)


def get_or_create_session(
    club: Class, session_date: date, *, created_by: User | None = None
) -> Tuple[ClubSession, bool]:
    """Return an existing session for the date or create a new one."""

    session, created = ClubSession.objects.get_or_create(
        club=club,
        session_date=session_date,
        defaults={"created_by": created_by},
    )

    if not created and session.created_by is None and created_by is not None:
        session.created_by = created_by
        session.save(update_fields=["created_by"])

    return session, created


def add_student_to_session(
    session: ClubSession,
    student: Student,
    *,
    status: str = ClubAttendance.STATUS_PRESENT,
) -> Tuple[ClubAttendance, bool]:
    """Add or update a student's attendance for the provided session.

    Returns a tuple of the attendance object and a boolean indicating
    whether the record was newly created.
    """

    with transaction.atomic():
        is_member = student.classes.filter(id=session.club_id).exists()
        original_clubs = list(student.classes.exclude(id=session.club_id))
        original_club = original_clubs[0] if original_clubs else None
        is_one_off = not is_member

        attendance, created = ClubAttendance.objects.update_or_create(
            session=session,
            student=student,
            defaults={
                "status": status,
                "is_one_off": is_one_off,
                "original_club": original_club,
            },
        )

        if is_one_off:
            calendar_entry, _ = StudentCalendarEntry.objects.get_or_create(
                student=student,
                club_session=session,
                defaults={"is_one_off": True},
            )
            if not calendar_entry.is_one_off:
                calendar_entry.is_one_off = True
                calendar_entry.save(update_fields=["is_one_off"])
        else:
            StudentCalendarEntry.objects.filter(
                student=student, club_session=session
            ).update(is_one_off=False)

        if is_one_off:
            for original in original_clubs:
                for teacher in original.teachers.all():
                    message = (
                        f"{student.first_name} {student.last_name} attended "
                        f"{session.club.name} on {session.session_date.isoformat()} "
                        f"instead of {original.name}."
                    )
                    notification, notif_created = TeacherNotification.objects.get_or_create(
                        teacher=teacher,
                        student=student,
                        original_club=original,
                        alternate_session=session,
                        defaults={"message": message},
                    )
                    if not notif_created and notification.message != message:
                        notification.message = message
                        notification.is_read = False
                        notification.save(update_fields=["message", "is_read"])
        else:
            TeacherNotification.objects.filter(
                student=student,
                alternate_session=session,
            ).delete()

    return attendance, created


__all__ = ["add_student_to_session", "get_or_create_session"]
