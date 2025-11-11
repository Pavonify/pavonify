from __future__ import annotations

import io
from datetime import datetime, timedelta
from importlib import import_module
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lang_platform.settings")

import django

django.setup()

from django.apps import apps
from django.test import TestCase
from django.utils import timezone

from sportsday import models, services, views


class StudentImportTests(TestCase):
    def test_student_import_global_scope(self):
        csv_content = "first_name,last_name,dob,grade,house,gender,external_id\n" "Ada,Lovelace,2010-12-10,G6,Red,F,S001\n"
        upload = io.BytesIO(csv_content.encode("utf-8"))
        result = views._import_students(upload)
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["updated"], 0)
        self.assertFalse(result["errors"])
        student = models.Student.objects.get(external_id="S001")
        self.assertEqual(student.first_name, "Ada")
        self.assertEqual(student.grade, "G6")


class EventGenerationTests(TestCase):
    def setUp(self):
        self.meet = models.Meet.objects.create(
            name="Autumn Carnival",
            slug="autumn",
            date="2025-09-12",
        )
        self.sport = models.SportType.objects.get(key="100m")

    def test_generate_events_uses_pattern(self):
        summary = services.generate_events(
            meet=self.meet,
            sport_types=[self.sport],
            grades=["G6", "G7"],
            genders=[models.Event.GenderLimit.FEMALE],
            name_pattern="{grade} {gender_label} {sport}",
            capacity_override=10,
            rounds_total=2,
        )
        self.assertEqual(summary["created"], 2)
        events = list(models.Event.objects.filter(meet=self.meet).order_by("name"))
        self.assertEqual(events[0].name, f"G6 Girls {self.sport.label}")
        self.assertEqual(events[0].grade_min, "G6")
        self.assertEqual(events[0].grade_max, "G6")
        self.assertEqual(events[0].capacity, 10)
        self.assertEqual(events[0].rounds_total, 2)


class BulkAssignmentTests(TestCase):
    def setUp(self):
        self.meet = models.Meet.objects.create(
            name="Winter Games",
            slug="winter",
            date="2025-08-01",
            max_events_per_student=2,
        )
        self.sport = models.SportType.objects.get(key="100m")
        base_dt = timezone.make_aware(datetime(2025, 8, 1, 9, 0))
        self.event_a = models.Event.objects.create(
            meet=self.meet,
            sport_type=self.sport,
            name="G6 Girls 100m",
            grade_min="G6",
            grade_max="G6",
            gender_limit=models.Event.GenderLimit.FEMALE,
            measure_unit="sec",
            capacity=2,
            schedule_dt=base_dt,
        )
        self.event_b = models.Event.objects.create(
            meet=self.meet,
            sport_type=self.sport,
            name="G6 Girls 200m",
            grade_min="G6",
            grade_max="G6",
            gender_limit=models.Event.GenderLimit.FEMALE,
            measure_unit="sec",
            capacity=2,
            schedule_dt=base_dt + timedelta(minutes=10),
        )
        self.students = [
            models.Student.objects.create(
                first_name="Ava",
                last_name="Lee",
                dob="2012-04-10",
                grade="G6",
                house="Red",
                gender="F",
            ),
            models.Student.objects.create(
                first_name="Bella",
                last_name="Ng",
                dob="2012-06-12",
                grade="G6",
                house="Blue",
                gender="F",
            ),
            models.Student.objects.create(
                first_name="Chloe",
                last_name="Kim",
                dob="2012-01-02",
                grade="G6",
                house="Red",
                gender="F",
            ),
            models.Student.objects.create(
                first_name="Dana",
                last_name="Fox",
                dob="2012-08-08",
                grade="G7",
                house="Green",
                gender="F",
            ),
            models.Student.objects.create(
                first_name="Eden",
                last_name="Wong",
                dob="2012-05-05",
                grade="G6",
                house="Gold",
                gender="M",
            ),
        ]

    def test_rule_based_assignment_respects_limits(self):
        queryset = models.Event.objects.filter(pk__in=[self.event_a.pk, self.event_b.pk])
        result = views._bulk_assign_entries_from_rules(self.meet, queryset)
        self.assertEqual(result["created"], 3)
        self.assertFalse(result["errors"])
        for event in (self.event_a, self.event_b):
            event.refresh_from_db()
            self.assertLessEqual(event.entries.count(), event.capacity)
            for entry in event.entries.select_related("student"):
                self.assertTrue(event.grade_allows(entry.student.grade))
                self.assertTrue(event.gender_allows(entry.student.gender))
        for student in self.students:
            total = models.Entry.objects.filter(event__meet=self.meet, student=student).count()
            self.assertLessEqual(total, 1)


class SeedMigrationTests(TestCase):
    def test_seed_is_idempotent(self):
        module = import_module("sportsday.migrations.0002_seed_sport_types")
        seed_sport_types = module.seed_sport_types
        initial = models.SportType.objects.count()
        seed_sport_types(apps, None)
        mid = models.SportType.objects.count()
        seed_sport_types(apps, None)
        final = models.SportType.objects.count()
        self.assertEqual(mid, final)
        self.assertGreaterEqual(mid, initial)
