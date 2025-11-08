from __future__ import annotations

import io
from decimal import Decimal

from django.test import TestCase

from sportsday import models, services


class ServiceTests(TestCase):
    def setUp(self):
        self.meet = models.Meet.objects.create(name="Meet", slug="meet", date="2026-05-01")
        self.rule = models.ScoringRule.objects.create(meet=self.meet, scope=models.ScoringRule.SCOPE_EVENT, points_csv="10,8,6,5", per_house=True)

    def test_parse_time_to_seconds(self):
        self.assertEqual(services.parse_time_to_seconds("1:02.345"), Decimal("62.345"))
        self.assertEqual(services.parse_time_to_seconds("59"), Decimal("59"))
        with self.assertRaises(ValueError):
            services.parse_time_to_seconds("bad")

    def test_normalize_distance(self):
        self.assertEqual(services.normalize_distance("4m56"), Decimal("4.56"))
        self.assertEqual(services.normalize_distance("5.123"), Decimal("5.12"))
        with self.assertRaises(ValueError):
            services.normalize_distance("abc")

    def test_rank_results(self):
        ranks = services.rank_results([Decimal("12.0"), Decimal("11.0"), None], models.Event.EVENT_TIME)
        self.assertEqual(ranks, [2, 1, None])
        ranks = services.rank_results([Decimal("4.5"), Decimal("4.5"), Decimal("4.0")], models.Event.EVENT_DISTANCE)
        self.assertEqual(ranks, [1, 1, 3])

    def test_allocate_points_share(self):
        ranks = [1, 1, 3]
        allocations = services.allocate_points(None, self.rule, ranks)  # type: ignore[arg-type]
        self.assertEqual(allocations[0], allocations[1])
        self.assertGreater(allocations[0], allocations[2])

    def test_load_students_from_csv(self):
        csv_content = """first_name,last_name,dob,grade,house,gender,external_id\nJane,Doe,2010-03-01,G6,Churchill,F,123\n"""
        buffer = io.StringIO(csv_content)
        rows = services.load_students_from_csv(self.meet, buffer)
        self.assertEqual(len(rows), 1)
        self.assertEqual(models.Student.objects.count(), 1)
        student = models.Student.objects.get()
        self.assertEqual(student.gender, "Female")
        # Import again to ensure update
        buffer.seek(0)
        services.load_students_from_csv(self.meet, buffer)
        self.assertEqual(models.Student.objects.count(), 1)

    def test_access_config_hash(self):
        config = models.SportsdayAccessConfig.get_solo()
        config.set_code("harrow123")
        self.assertTrue(models.SportsdayAccessConfig.verify_code("harrow123", config.code_hash))
        self.assertFalse(models.SportsdayAccessConfig.verify_code("wrong", config.code_hash))
