from __future__ import annotations

import json
from datetime import date

from django.test import TestCase
from django.urls import reverse

from learning.models import (
    Class,
    ClubAttendance,
    School,
    Student,
    StudentCalendarEntry,
    TeacherNotification,
    User,
)
from learning.services.attendance import add_student_to_session, get_or_create_session


class AttendanceServiceTests(TestCase):
    def setUp(self) -> None:
        self.school = School.objects.create(name="Example School")
        self.teacher_home = User.objects.create_user(
            username="teacher_home",
            password="pass1234",
            first_name="Home",
            last_name="Teacher",
            is_teacher=True,
            school=self.school,
        )
        self.teacher_alt = User.objects.create_user(
            username="teacher_alt",
            password="pass1234",
            first_name="Alt",
            last_name="Teacher",
            is_teacher=True,
            school=self.school,
        )
        self.original_club = Class.objects.create(
            school=self.school,
            name="French Club",
            language="French",
        )
        self.original_club.teachers.add(self.teacher_home)
        self.alt_club = Class.objects.create(
            school=self.school,
            name="Spanish Club",
            language="Spanish",
        )
        self.alt_club.teachers.add(self.teacher_alt)
        self.student = Student.objects.create(
            school=self.school,
            first_name="Test",
            last_name="Student",
            year_group=7,
            date_of_birth=date(2010, 1, 1),
            username="student1",
            password="pass1234",
        )
        self.student.classes.add(self.original_club)

    def test_one_off_attendance_creates_calendar_and_notification(self):
        session, created = get_or_create_session(
            self.alt_club, date.today(), created_by=self.teacher_alt
        )
        self.assertTrue(created)

        attendance, created = add_student_to_session(session, self.student)
        self.assertTrue(created)
        self.assertTrue(attendance.is_one_off)
        self.assertEqual(attendance.original_club, self.original_club)

        self.assertTrue(
            StudentCalendarEntry.objects.filter(
                student=self.student,
                club_session=session,
                is_one_off=True,
            ).exists()
        )
        notifications = TeacherNotification.objects.filter(
            student=self.student, alternate_session=session
        )
        self.assertEqual(notifications.count(), 1)
        self.assertEqual(notifications.first().teacher, self.teacher_home)

        # Calling the service again should not duplicate records
        attendance_again, created_again = add_student_to_session(
            session, self.student
        )
        self.assertFalse(created_again)
        self.assertEqual(
            TeacherNotification.objects.filter(
                student=self.student, alternate_session=session
            ).count(),
            1,
        )

    def test_member_attendance_has_no_one_off_side_effects(self):
        member = Student.objects.create(
            school=self.school,
            first_name="Another",
            last_name="Student",
            year_group=8,
            date_of_birth=date(2010, 6, 1),
            username="student2",
            password="pass1234",
        )
        member.classes.add(self.alt_club)

        session, _ = get_or_create_session(
            self.alt_club, date.today(), created_by=self.teacher_alt
        )
        attendance, created = add_student_to_session(session, member)

        self.assertTrue(created)
        self.assertFalse(attendance.is_one_off)
        self.assertIsNone(attendance.original_club)
        self.assertFalse(
            StudentCalendarEntry.objects.filter(
                student=member, club_session=session
            ).exists()
        )
        self.assertFalse(
            TeacherNotification.objects.filter(student=member).exists()
        )


class AttendanceAPITests(TestCase):
    def setUp(self) -> None:
        self.school = School.objects.create(name="Example School")
        self.teacher_home = User.objects.create_user(
            username="api_teacher_home",
            password="pass1234",
            first_name="Home",
            last_name="Teacher",
            is_teacher=True,
            school=self.school,
        )
        self.teacher_alt = User.objects.create_user(
            username="api_teacher_alt",
            password="pass1234",
            first_name="Alt",
            last_name="Teacher",
            is_teacher=True,
            school=self.school,
        )
        self.original_club = Class.objects.create(
            school=self.school,
            name="Drama Club",
            language="English",
        )
        self.original_club.teachers.add(self.teacher_home)
        self.alt_club = Class.objects.create(
            school=self.school,
            name="Music Club",
            language="English",
        )
        self.alt_club.teachers.add(self.teacher_alt)
        self.student = Student.objects.create(
            school=self.school,
            first_name="Api",
            last_name="Student",
            year_group=9,
            date_of_birth=date(2009, 5, 20),
            username="api_student",
            password="pass1234",
        )
        self.student.classes.add(self.original_club)

    def test_teacher_can_add_one_off_student_via_api(self):
        self.client.force_login(self.teacher_alt)
        url = reverse("api_add_one_off_attendance", args=[self.alt_club.id])
        payload = {
            "student_id": str(self.student.id),
            "session_date": date.today().isoformat(),
        }
        response = self.client.post(
            url, data=json.dumps(payload), content_type="application/json"
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data["is_one_off"])
        self.assertEqual(data["original_club_id"], str(self.original_club.id))
        self.assertEqual(TeacherNotification.objects.count(), 1)

    def test_non_teacher_cannot_add_attendance(self):
        non_teacher = User.objects.create_user(
            username="not_teacher",
            password="pass1234",
            first_name="No",
            last_name="Teacher",
            school=self.school,
        )
        self.client.force_login(non_teacher)
        url = reverse("api_add_one_off_attendance", args=[self.alt_club.id])
        payload = {
            "student_id": str(self.student.id),
            "session_date": date.today().isoformat(),
        }
        response = self.client.post(
            url, data=json.dumps(payload), content_type="application/json"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ClubAttendance.objects.count(), 0)
