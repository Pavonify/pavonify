from datetime import datetime, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from django.urls import reverse
from django.utils import timezone

from sportsday import models


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class SportsdayViewsTests(TestCase):
    def setUp(self):
        self.meet = models.Meet.objects.create(
            name="Spring Meet",
            slug="spring-meet",
            date="2025-05-01",
            location="Main Oval",
        )
        sprint = models.SportType.objects.get(key="100m")
        self.teacher = models.Teacher.objects.create(
            first_name="Jamie",
            last_name="Lee",
            email="teacher@example.com",
        )
        models.ScoringRule.objects.create(
            meet=self.meet,
            points_csv="10,8,6",
            participation_point=Decimal("1.00"),
        )
        self.event = models.Event.objects.create(
            meet=self.meet,
            sport_type=sprint,
            name="100m Dash",
            grade_min="5",
            grade_max="6",
            gender_limit=models.Event.GenderLimit.MIXED,
            measure_unit="sec",
            capacity=8,
            rounds_total=2,
            knockout_qualifiers="Q:1;q:1",
        )
        self.event.assigned_teachers.add(self.teacher)
        self.student = models.Student.objects.create(
            first_name="Alex",
            last_name="Morgan",
            dob="2012-03-05",
            grade="6",
            house="Blue",
            gender="X",
        )
        self.entry = models.Entry.objects.create(event=self.event, student=self.student, round_no=1, heat=1)
        self.other_student = models.Student.objects.create(
            first_name="Billie",
            last_name="Chan",
            dob="2012-07-12",
            grade="6",
            house="Gold",
            gender="X",
        )

    def test_event_list_shows_all_events_to_teachers(self):
        teacher_user = get_user_model().objects.create_user(
            username="teacher",
            email="teacher@example.com",
            password="password123",
        )
        self.client.force_login(teacher_user)

        unassigned_event = models.Event.objects.create(
            meet=self.meet,
            sport_type=self.event.sport_type,
            name="200m Dash",
            grade_min="5",
            grade_max="6",
            gender_limit=models.Event.GenderLimit.MIXED,
            measure_unit="sec",
            capacity=8,
        )

        response = self.client.get(reverse("sportsday:events"), {"meet": self.meet.slug})

        self.assertContains(response, self.event.name)
        self.assertContains(response, unassigned_event.name)

    def test_dashboard_renders_tiles(self):
        response = self.client.get(reverse("sportsday:dashboard"))
        self.assertContains(response, "Command Center")
        self.assertContains(response, "Meets")

    def test_meet_detail_page_loads(self):
        response = self.client.get(reverse("sportsday:meet-detail", kwargs={"slug": self.meet.slug}))
        self.assertContains(response, "Meet hub")
        self.assertContains(response, self.meet.name)

    def test_sync_event_dates_aligns_schedule(self):
        scheduled_dt = timezone.make_aware(datetime(2025, 5, 2, 10, 30))
        self.event.schedule_dt = scheduled_dt
        self.event.save(update_fields=["schedule_dt"])

        response = self.client.post(reverse("sportsday:meet-sync-events"))

        self.assertRedirects(response, reverse("sportsday:meet-list"))
        self.event.refresh_from_db()
        meet_date = (
            self.meet.date
            if hasattr(self.meet.date, "year")
            else datetime.fromisoformat(str(self.meet.date)).date()
        )
        self.assertEqual(self.event.schedule_dt.date(), meet_date)
        self.assertEqual(self.event.schedule_dt.timetz(), time(10, 30, tzinfo=scheduled_dt.tzinfo))

    def test_event_start_list_fragment(self):
        response = self.client.get(reverse("sportsday:event-start-list-fragment", kwargs={"pk": self.event.pk}))
        self.assertContains(response, "Start Lists")
        self.assertContains(response, self.student.first_name)

    def test_event_results_fragment_get(self):
        response = self.client.get(reverse("sportsday:event-results-fragment", kwargs={"pk": self.event.pk}))
        self.assertContains(response, "Enter Results")
        self.assertContains(response, "Save Draft")

    def test_event_results_submit_records_time_and_rank(self):
        second_entry = models.Entry.objects.create(event=self.event, student=self.other_student, round_no=1, heat=1)
        url = reverse("sportsday:event-results-fragment", kwargs={"pk": self.event.pk})
        response = self.client.post(
            url,
            {
                "round_no": 1,
                "heat": 1,
                f"entry-{self.entry.pk}-entry_id": self.entry.pk,
                f"entry-{self.entry.pk}-time_display": "12.345",
                f"entry-{second_entry.pk}-entry_id": second_entry.pk,
                f"entry-{second_entry.pk}-time_display": "12.890",
                "action": "submit",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.entry.refresh_from_db()
        second_entry.refresh_from_db()
        self.assertTrue(models.Result.objects.filter(entry=self.entry, best_value=Decimal("12.345"), rank=1, finalized=True).exists())
        self.assertTrue(models.Result.objects.filter(entry=second_entry, rank=2, finalized=True).exists())
        self.assertEqual(self.event.entries.filter(round_no=2).count(), 2)

    def test_event_start_list_add_student(self):
        response = self.client.post(
            reverse("sportsday:event-start-list-add", kwargs={"pk": self.event.pk}),
            {"student": self.other_student.pk, "round_no": 1},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        entry = models.Entry.objects.get(event=self.event, student=self.other_student)
        self.assertEqual(entry.round_no, 1)
        self.assertEqual(entry.heat, 1)
        self.assertEqual(entry.lane_or_order, 2)

    def test_event_start_list_remove_student(self):
        entry = models.Entry.objects.create(event=self.event, student=self.other_student, round_no=1, heat=1, lane_or_order=2)
        response = self.client.post(
            reverse("sportsday:event-start-list-remove", kwargs={"pk": self.event.pk, "entry_id": entry.pk}),
            {"round_no": 1},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(models.Entry.objects.filter(pk=entry.pk).exists())

    def test_event_results_qr_serves_png(self):
        response = self.client.get(reverse("sportsday:event-results-qr", kwargs={"pk": self.event.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/svg+xml")
        self.assertIn("<svg", response.content.decode("utf-8"))

    def test_event_start_list_reorder(self):
        second = models.Entry.objects.create(
            event=self.event,
            student=self.other_student,
            round_no=1,
            heat=1,
            lane_or_order=2,
        )
        response = self.client.post(
            reverse("sportsday:event-start-list-reorder", kwargs={"pk": self.event.pk}),
            {"entry[]": [second.pk, self.entry.pk], "round_no": 1},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.entry.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(second.lane_or_order, 1)
        self.assertEqual(self.entry.lane_or_order, 2)

    def test_export_students_csv(self):
        response = self.client.get(reverse("sportsday:export-students-csv"), {"meet": self.meet.slug})
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn(self.student.first_name, content)

    def test_export_teachers_csv(self):
        response = self.client.get(reverse("sportsday:export-teachers-csv"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.teacher.first_name, response.content.decode("utf-8"))

    def test_export_startlists_csv(self):
        response = self.client.get(reverse("sportsday:export-startlists-csv"), {"event": self.event.pk})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.student.last_name, response.content.decode("utf-8"))

    def test_export_results_csv_includes_finalists(self):
        final_entry = models.Entry.objects.create(
            event=self.event,
            student=self.other_student,
            round_no=self.event.rounds_total,
            heat=1,
        )
        models.Result.objects.create(entry=final_entry, rank=1, best_value=Decimal("12.345"), finalized=True)
        response = self.client.get(reverse("sportsday:export-results-csv"), {"meet": self.meet.slug})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.other_student.last_name, response.content.decode("utf-8"))

    def test_export_leaderboard_csv_contains_header(self):
        final_entry = models.Entry.objects.create(
            event=self.event,
            student=self.other_student,
            round_no=self.event.rounds_total,
            heat=1,
        )
        models.Result.objects.create(entry=final_entry, rank=1, best_value=Decimal("12.345"), finalized=True)
        response = self.client.get(reverse("sportsday:export-leaderboard-csv"), {"meet": self.meet.slug})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Overall house points", response.content.decode("utf-8"))

    def test_students_table_fragment_filters_by_meet(self):
        response = self.client.get(reverse("sportsday:students-table-fragment"), {"meet": self.meet.slug})
        self.assertContains(response, self.student.last_name)

    def test_meet_create_creates_scoring_rule(self):
        response = self.client.post(
            reverse("sportsday:meet-create"),
            {
                "name": "Winter Carnival",
                "slug": "",
                "date": "2025-09-01",
                "start_time": "09:00",
                "end_time": "15:00",
                "location": "Main Oval",
                "max_events_per_student": 3,
                "notes": "",
                "scoring_preset": "standard",
                "points_csv": "10,8,6,5,4,3,2,1",
                "participation_point": "0.00",
                "tie_method": models.ScoringRule.TieMethod.SHARE,
            },
        )
        self.assertEqual(response.status_code, 302)
        meet = models.Meet.objects.get(name="Winter Carnival")
        rule = meet.scoring_rules.first()
        self.assertIsNotNone(rule)
        self.assertEqual(rule.points_csv, "10,8,6,5,4,3,2,1")

    def test_event_create_creates_event(self):
        sport = models.SportType.objects.first()
        response = self.client.post(
            reverse("sportsday:event-create"),
            {
                "meet": self.meet.pk,
                "sport_type": sport.pk,
                "name": "200m Sprint",
                "grade_min": "5",
                "grade_max": "6",
                "gender_limit": models.Event.GenderLimit.MIXED,
                "capacity": 8,
                "attempts": 1,
                "schedule_dt": "2025-05-01T10:30",
                "location": "Track",
                "assigned_teachers": [str(self.teacher.pk)],
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        new_event = models.Event.objects.get(name="200m Sprint")
        self.assertEqual(new_event.meet, self.meet)
        self.assertEqual(new_event.assigned_teachers.first(), self.teacher)

    def test_event_participants_updates_entries(self):
        eligible_student = models.Student.objects.create(
            first_name="Charlie",
            last_name="Ng",
            dob="2012-11-20",
            grade="5",
            house="Green",
            gender="X",
        )
        response = self.client.post(
            reverse("sportsday:event-participants", kwargs={"pk": self.event.pk}),
            {"participants": [self.student.pk, eligible_student.pk]},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(models.Entry.objects.filter(event=self.event, student=eligible_student).exists())
        remaining = self.event.entries.filter(round_no=1)
        self.assertEqual(remaining.count(), 2)

    def test_event_participants_handles_validation_error(self):
        conflict_time = timezone.make_aware(datetime(2025, 5, 1, 12, 30))
        self.event.schedule_dt = conflict_time
        self.event.save(update_fields=["schedule_dt"])

        conflict_event = models.Event.objects.create(
            meet=self.meet,
            sport_type=self.event.sport_type,
            name="Long Jump",
            grade_min="5",
            grade_max="6",
            gender_limit=models.Event.GenderLimit.MIXED,
            measure_unit="cm",
            capacity=8,
            schedule_dt=conflict_time,
        )

        conflicting_student = models.Student.objects.create(
            first_name="Dana",
            last_name="Smith",
            dob="2012-09-15",
            grade="6",
            house="Red",
            gender="X",
        )
        models.Entry.objects.create(
            event=conflict_event,
            student=conflicting_student,
            round_no=1,
            heat=1,
        )

        response = self.client.post(
            reverse("sportsday:event-participants", kwargs={"pk": self.event.pk}),
            {"participants": [self.student.pk, conflicting_student.pk]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Student already has an entry")
        self.assertFalse(
            models.Entry.objects.filter(event=self.event, student=conflicting_student).exists()
        )


