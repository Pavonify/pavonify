from django.test import TestCase, override_settings
from django.urls import reverse

from learning.forms import TeacherRegistrationForm
from learning.models import Class, School, Student, User, VocabularyList


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class SchoolAccountTests(TestCase):
    def setUp(self) -> None:
        self.password = "StrongPass123"

    def _create_teacher(self, username: str, *, school=None, is_lead=False) -> User:
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password=self.password,
            is_teacher=True,
        )
        if school:
            user.school = school
        user.is_school_lead = is_lead
        user.save(update_fields=["school", "is_school_lead"])
        return user

    def test_teacher_registration_creates_school(self):
        form = TeacherRegistrationForm(
            data={
                "full_name": "Alice Smith",
                "email": "alice@example.com",
                "username": "alice",
                "password1": "StrongPass123",
                "password2": "StrongPass123",
                "country": "GB",
                "school_option": "create",
                "school_name": "Greenfield High",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertTrue(user.is_school_lead)
        self.assertIsNotNone(user.school)
        self.assertEqual(user.school.name, "Greenfield High")
        self.assertEqual(len(user.school.school_code), 6)

    def test_teacher_registration_join_school(self):
        school = School.objects.create(name="Riverdale", school_code="ABC123")
        form = TeacherRegistrationForm(
            data={
                "full_name": "Bob Jones",
                "email": "bob@example.com",
                "username": "bobj",
                "password1": "StrongPass123",
                "password2": "StrongPass123",
                "country": "GB",
                "school_option": "join",
                "school_code": "abc123",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertFalse(user.is_school_lead)
        self.assertEqual(user.school, school)

    def test_only_lead_can_remove_teacher(self):
        school = School.objects.create(name="Northshore")
        lead = self._create_teacher("lead", school=school, is_lead=True)
        teacher = self._create_teacher("teacher", school=school)

        class_room = Class.objects.create(name="Year 7", language="en", school=school)
        class_room.teachers.add(lead, teacher)

        self.client.force_login(lead)
        response = self.client.post(reverse("remove_school_teacher", args=[teacher.id]))
        self.assertRedirects(response, f"{reverse('teacher_dashboard')}?pane=school")
        teacher.refresh_from_db()
        self.assertIsNone(teacher.school)
        self.assertFalse(class_room.teachers.filter(id=teacher.id).exists())

        self.client.force_login(teacher)
        response = self.client.post(reverse("remove_school_teacher", args=[lead.id]))
        self.assertEqual(response.status_code, 403)

    def test_school_shared_vocabulary_visible(self):
        school = School.objects.create(name="Langdale")
        lead = self._create_teacher("lead_teacher", school=school, is_lead=True)
        colleague = self._create_teacher("colleague", school=school)

        VocabularyList.objects.create(
            name="Shared List",
            source_language="en",
            target_language="fr",
            teacher=lead,
            shared_with_school=True,
        )

        self.client.force_login(colleague)
        response = self.client.get(reverse("teacher_dashboard"))
        self.assertEqual(response.status_code, 200)
        shared_lists = response.context["school_shared_vocab_lists"]
        self.assertTrue(shared_lists.exists())
        self.assertEqual(shared_lists.first().name, "Shared List")

    def test_school_leaderboard_aggregation(self):
        school = School.objects.create(name="Summerview")
        teacher = self._create_teacher("coach", school=school, is_lead=True)

        class_one = Class.objects.create(name="Class A", language="Spanish", school=school)
        class_one.teachers.add(teacher)

        student_one = Student.objects.create(
            school=school,
            first_name="Ana",
            last_name="Lopez",
            year_group=7,
            date_of_birth="2012-01-01",
            username="ana",
            password="pass",
        )
        student_one.total_points = 150
        student_one.save()
        student_one.classes.add(class_one)

        student_two = Student.objects.create(
            school=school,
            first_name="Ben",
            last_name="Wright",
            year_group=8,
            date_of_birth="2011-01-01",
            username="ben",
            password="pass",
        )
        student_two.total_points = 200
        student_two.save()
        student_two.classes.add(class_one)

        self.client.force_login(teacher)
        response = self.client.get(reverse("api_school_leaderboard"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["school"]["id"], school.id)
        self.assertEqual(data["top_students"][0]["total_points"], 200)
        grades = {entry["year_group"]: entry["total_points"] for entry in data["grade_totals"]}
        self.assertIn(7, grades)
        self.assertIn(8, grades)
        languages = {entry["language"]: entry["total_points"] for entry in data["language_totals"]}
        self.assertEqual(languages["Spanish"], 350)
