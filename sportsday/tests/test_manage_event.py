import os
from decimal import Decimal

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lang_platform.settings")

import django

django.setup()

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from sportsday import models, services


class ManageEventViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="staff",
            email="staff@example.com",
            password="password123",
            is_staff=True,
        )
        self.client.force_login(self.user)
        self.meet = models.Meet.objects.create(
            name="Autumn Meet",
            slug="autumn-meet",
            date="2025-09-01",
        )
        self.track_type = models.SportType.objects.create(
            key="test-track",
            label="Test Track",
            archetype=models.SportType.Archetype.TRACK_TIME,
            default_unit=models.SportType.DefaultUnit.SECONDS,
            default_capacity=8,
            default_attempts=1,
        )
        self.field_type = models.SportType.objects.create(
            key="test-field",
            label="Test Long Jump",
            archetype=models.SportType.Archetype.FIELD_DISTANCE,
            default_unit=models.SportType.DefaultUnit.METRES,
            default_capacity=12,
            default_attempts=3,
        )

    def _create_student(self, first_name="Jamie", last_name="Lee", house="Blue"):
        return models.Student.objects.create(
            first_name=first_name,
            last_name=last_name,
            dob="2012-01-01",
            grade="6",
            house=house,
            gender=models.Event.GenderLimit.MIXED,
        )

    def test_track_results_post_creates_results_and_attempts(self):
        event = models.Event.objects.create(
            meet=self.meet,
            sport_type=self.track_type,
            name="100m Dash",
            grade_min="6",
            grade_max="6",
            gender_limit=models.Event.GenderLimit.MIXED,
            measure_unit=self.track_type.default_unit,
            capacity=8,
            attempts=1,
        )
        entry_one = models.Entry.objects.create(event=event, student=self._create_student("Alex", "Morgan"))
        entry_two = models.Entry.objects.create(event=event, student=self._create_student("Billie", "Chan", "Gold"))
        entry_three = models.Entry.objects.create(event=event, student=self._create_student("Casey", "Diaz", "Green"))

        url = reverse("sportsday:manage-event", args=[event.pk])
        response = self.client.post(
            url,
            {
                f"rank[{entry_one.pk}]": "1",
                f"time[{entry_one.pk}]": "12.345",
                f"rank[{entry_two.pk}]": "2",
                f"time[{entry_two.pk}]": "",
                f"dq[{entry_three.pk}]": "on",
            },
        )
        self.assertEqual(response.status_code, 302)

        entry_one.refresh_from_db()
        entry_two.refresh_from_db()
        entry_three.refresh_from_db()

        result_one = models.Result.objects.get(entry=entry_one)
        result_two = models.Result.objects.get(entry=entry_two)
        result_three = models.Result.objects.get(entry=entry_three)

        self.assertEqual(result_one.rank, 1)
        self.assertEqual(result_two.rank, 2)
        self.assertIsNone(result_three.rank)
        self.assertTrue(result_one.finalized)
        self.assertTrue(result_two.finalized)
        self.assertTrue(result_three.finalized)

        attempt = models.Attempt.objects.get(entry=entry_one, attempt_no=1)
        self.assertEqual(attempt.time_seconds, Decimal("12.345"))
        self.assertFalse(models.Attempt.objects.filter(entry=entry_two).exists())
        self.assertFalse(models.Attempt.objects.filter(entry=entry_three).exists())
        self.assertEqual(entry_three.status, models.Entry.Status.DQ)

    def test_field_attempts_rank_and_best(self):
        event = models.Event.objects.create(
            meet=self.meet,
            sport_type=self.field_type,
            name="Long Jump",
            grade_min="6",
            grade_max="6",
            gender_limit=models.Event.GenderLimit.MIXED,
            measure_unit=self.field_type.default_unit,
            capacity=12,
            attempts=3,
        )
        entry_one = models.Entry.objects.create(event=event, student=self._create_student("Alex", "Morgan"))
        entry_two = models.Entry.objects.create(event=event, student=self._create_student("Billie", "Chan", "Gold"))
        entry_three = models.Entry.objects.create(event=event, student=self._create_student("Casey", "Diaz", "Green"))

        url = reverse("sportsday:manage-event", args=[event.pk])
        response = self.client.post(
            url,
            {
                f"attempt[{entry_one.pk}][1]": "4.50",
                f"attempt[{entry_one.pk}][2]": "4.60",
                f"attempt[{entry_one.pk}][3]": "",
                f"attempt[{entry_two.pk}][1]": "4.60",
                f"attempt[{entry_two.pk}][2]": "4.50",
                f"attempt[{entry_two.pk}][3]": "",
                f"attempt[{entry_three.pk}][1]": "",
                f"attempt[{entry_three.pk}][2]": "",
                f"dq[{entry_three.pk}]": "on",
            },
        )
        self.assertEqual(response.status_code, 302)

        result_one = models.Result.objects.get(entry=entry_one)
        result_two = models.Result.objects.get(entry=entry_two)
        result_three = models.Result.objects.get(entry=entry_three)

        # Entry two should win on earliest best attempt (attempt 1)
        self.assertEqual(result_two.rank, 1)
        self.assertEqual(result_one.rank, 2)
        self.assertEqual(result_two.best_value, Decimal("4.600"))
        self.assertEqual(result_one.best_value, Decimal("4.600"))
        self.assertIsNone(result_three.rank)

        attempts_one = list(models.Attempt.objects.filter(entry=entry_one).order_by("attempt_no"))
        self.assertEqual(len(attempts_one), 3)
        self.assertEqual(attempts_one[0].distance_m, Decimal("4.500"))
        self.assertEqual(attempts_one[1].distance_m, Decimal("4.600"))
        self.assertFalse(attempts_one[2].valid)
        self.assertEqual(models.Attempt.objects.filter(entry=entry_three).count(), 3)
        entry_three.refresh_from_db()
        self.assertEqual(entry_three.status, models.Entry.Status.DQ)

    @override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
    def test_permissions_allow_public_access(self):
        event = models.Event.objects.create(
            meet=self.meet,
            sport_type=self.track_type,
            name="200m",
            grade_min="6",
            grade_max="6",
            gender_limit=models.Event.GenderLimit.MIXED,
            measure_unit=self.track_type.default_unit,
            capacity=8,
        )
        student = self._create_student()
        entry = models.Entry.objects.create(event=event, student=student)

        url = reverse("sportsday:manage-event", args=[event.pk])
        self.client.logout()
        response = self.client.post(url, {f"rank[{entry.pk}]": "1"})
        self.assertEqual(response.status_code, 302)

        get_response = self.client.get(url)
        self.assertEqual(get_response.status_code, 200)
        self.assertTrue(get_response.context["can_edit"])

    @override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
    def test_assigned_teacher_without_email_can_edit(self):
        event = models.Event.objects.create(
            meet=self.meet,
            sport_type=self.track_type,
            name="400m",
            grade_min="6",
            grade_max="6",
            gender_limit=models.Event.GenderLimit.MIXED,
            measure_unit=self.track_type.default_unit,
            capacity=8,
        )
        entry = models.Entry.objects.create(event=event, student=self._create_student())
        teacher = models.Teacher.objects.create(
            first_name="Jordan",
            last_name="Cole",
            email="",
            external_id="marshal-42",
        )
        event.assigned_teachers.add(teacher)

        teacher_user = get_user_model().objects.create_user(
            username="marshal-42",
            email="",
            password="secretpass",
        )

        self.client.logout()
        self.client.force_login(teacher_user)

        url = reverse("sportsday:manage-event", args=[event.pk])
        get_response = self.client.get(url)
        self.assertEqual(get_response.status_code, 200)
        self.assertTrue(get_response.context["can_edit"])
        self.assertNotIn(
            f'name="rank[{entry.pk}]" disabled',
            get_response.content.decode("utf-8"),
        )

        post_response = self.client.post(url, {f"rank[{entry.pk}]": "1"})
        self.assertEqual(post_response.status_code, 302)

    def test_event_delete_clears_entries_and_scoring(self):
        event = models.Event.objects.create(
            meet=self.meet,
            sport_type=self.track_type,
            name="Relay",
            grade_min="6",
            grade_max="6",
            gender_limit=models.Event.GenderLimit.MIXED,
            measure_unit=self.track_type.default_unit,
            capacity=8,
        )
        participants = [
            self._create_student("Alex", "Morgan"),
            self._create_student("Billie", "Chan", "Gold"),
            self._create_student("Casey", "Diaz", "Green"),
        ]
        entries = [
            models.Entry.objects.create(event=event, student=student, round_no=1, heat=1)
            for student in participants
        ]
        for index, entry in enumerate(entries, start=1):
            models.Result.objects.create(
                entry=entry,
                rank=index,
                best_value=Decimal("12.000"),
                finalized=True,
            )

        initial_records = services.compute_scoring_records(self.meet)
        self.assertEqual(len(initial_records), 3)

        event_id = event.pk
        response = self.client.post(reverse("sportsday:event-delete", args=[event_id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(models.Event.objects.filter(pk=event_id).exists())
        self.assertFalse(models.Entry.objects.filter(event_id=event_id).exists())
        self.assertFalse(models.Result.objects.filter(entry__event_id=event_id).exists())

        remaining_records = services.compute_scoring_records(self.meet)
        self.assertEqual(len(remaining_records), 0)
