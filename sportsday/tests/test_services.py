import os
from decimal import Decimal
from types import SimpleNamespace

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lang_platform.settings")

import django

django.setup()

from django.core.exceptions import ValidationError
from django.test import TestCase

from sportsday import models, services


class SportsdayModelTests(TestCase):
    def setUp(self):
        self.meet = models.Meet.objects.create(
            name="Autumn Carnival",
            slug="autumn-carnival",
            date="2025-09-12",
        )
        self.sport_type = models.SportType.objects.get(key="long-jump")
        self.student = models.Student.objects.create(
            first_name="Morgan",
            last_name="Shaw",
            dob="2013-04-11",
            grade="6",
            house="Red",
            gender="F",
        )

    def test_entry_unique_per_round(self):
        event = models.Event.objects.create(
            meet=self.meet,
            sport_type=self.sport_type,
            name="Long Jump",
            grade_min="5",
            grade_max="6",
            gender_limit=models.Event.GenderLimit.FEMALE,
            measure_unit="m",
            capacity=12,
            attempts=3,
        )
        models.Entry.objects.create(event=event, student=self.student, round_no=1)
        with self.assertRaises(ValidationError):
            models.Entry.objects.create(event=event, student=self.student, round_no=1)

    def test_result_defaults(self):
        event = models.Event.objects.create(
            meet=self.meet,
            sport_type=self.sport_type,
            name="Long Jump Final",
            grade_min="5",
            grade_max="6",
            gender_limit=models.Event.GenderLimit.FEMALE,
            measure_unit="m",
            capacity=12,
        )
        entry = models.Entry.objects.create(event=event, student=self.student, round_no=1)
        models.Attempt.objects.create(entry=entry, attempt_no=1, distance_m=Decimal("3.250"))
        result = models.Result.objects.create(entry=entry, best_value=Decimal("3.250"))
        self.assertFalse(result.finalized)
        self.assertEqual(result.best_value, Decimal("3.250"))
        self.assertEqual(result.tiebreak, {})

    def test_seeded_sport_types_available(self):
        seeded_labels = {
            "100m",
            "200m",
            "400m",
            "800m",
            "1500m",
            "4x100m Relay",
            "Shot Put",
            "Javelin",
            "Discus",
            "Long Jump",
            "Triple Jump",
            "High Jump",
            "Pull-ups",
            "Sit-ups",
            "Cross Country",
        }
        available = set(models.SportType.objects.values_list("label", flat=True))
        self.assertTrue(seeded_labels.issubset(available))


class ServicesLogicTests(TestCase):
    def test_parse_time_to_seconds_variants(self):
        self.assertEqual(services.parse_time_to_seconds("60.123"), Decimal("60.123"))
        self.assertEqual(services.parse_time_to_seconds("1:00.500"), Decimal("60.500"))
        self.assertIsNone(services.parse_time_to_seconds(""))
        with self.assertRaises(ValueError):
            services.parse_time_to_seconds("invalid")

    def test_normalize_distance_parses_units(self):
        self.assertEqual(services.normalize_distance("5.250"), Decimal("5.250"))
        self.assertEqual(services.normalize_distance("525cm"), Decimal("5.250"))
        with self.assertRaises(ValueError):
            services.normalize_distance("-3")

    def test_rank_track_assigns_positions(self):
        meet = models.Meet.objects.create(name="Test", slug="test", date="2025-01-01")
        sport = models.SportType.objects.get(key="100m")
        event = models.Event.objects.create(
            meet=meet,
            sport_type=sport,
            name="Dash",
            grade_min="5",
            grade_max="6",
            gender_limit=models.Event.GenderLimit.MIXED,
            measure_unit="sec",
        )
        student = models.Student.objects.create(
            first_name="Alex",
            last_name="Lee",
            dob="2012-03-05",
            grade="6",
            house="Blue",
            gender="X",
        )
        entry = models.Entry.objects.create(event=event, student=student, round_no=1)
        payloads = [
            {
                "entry": entry,
                "status": models.Entry.Status.CONFIRMED,
                "best_value": Decimal("12.345"),
            }
        ]
        services.rank_track(payloads)
        self.assertEqual(payloads[0]["rank"], 1)

    def test_rank_track_requires_winner_time(self):
        payloads = [
            {"entry": SimpleNamespace(), "status": models.Entry.Status.CONFIRMED, "best_value": None}
        ]
        with self.assertRaises(ValueError):
            services.rank_track(payloads)

    def test_rank_field_uses_tiebreak(self):
        payloads = [
            {
                "entry": SimpleNamespace(),
                "status": models.Entry.Status.CONFIRMED,
                "best_value": Decimal("5.00"),
                "series": [Decimal("5.00"), Decimal("4.90")],
            },
            {
                "entry": SimpleNamespace(),
                "status": models.Entry.Status.CONFIRMED,
                "best_value": Decimal("5.00"),
                "series": [Decimal("5.00"), Decimal("4.80")],
            },
        ]
        services.rank_field(payloads)
        self.assertEqual(payloads[0]["rank"], 1)
        self.assertEqual(payloads[1]["rank"], 2)

    def test_apply_qualifiers_creates_entries(self):
        meet = models.Meet.objects.create(name="Qualifier", slug="qualifier", date="2025-02-01")
        sport = models.SportType.objects.get(key="100m")
        event = models.Event.objects.create(
            meet=meet,
            sport_type=sport,
            name="Sprint",
            grade_min="5",
            grade_max="6",
            gender_limit=models.Event.GenderLimit.MIXED,
            measure_unit="sec",
            rounds_total=2,
        )
        students = [
            models.Student.objects.create(
                first_name=f"Runner {idx}",
                last_name="Test",
                dob="2012-01-01",
                grade="6",
                house="Blue",
                gender="X",
            )
            for idx in range(1, 5)
        ]
        payloads = []
        for idx, student in enumerate(students, start=1):
            entry = models.Entry.objects.create(event=event, student=student, round_no=1, heat=1)
            payloads.append(
                {
                    "entry": entry,
                    "status": models.Entry.Status.CONFIRMED,
                    "best_value": Decimal(f"{12 + idx / 10:.3f}"),
                    "rank": idx,
                }
            )
        finalists = services.apply_qualifiers(payloads, "Q:2;q:1")
        self.assertEqual(len(finalists), 3)
        self.assertTrue(
            models.Entry.objects.filter(event=event, round_no=2, student__in=[p.student for p in finalists]).exists()
        )

    def test_compute_scoring_records_assigns_shared_points(self):
        meet = models.Meet.objects.create(name="Scoring", slug="scoring", date="2025-03-10")
        models.ScoringRule.objects.create(
            meet=meet,
            points_csv="10,8,6",
            participation_point=Decimal("0.50"),
            tie_method=models.ScoringRule.TieMethod.SHARE,
        )
        sport = models.SportType.objects.get(key="100m")
        event = models.Event.objects.create(
            meet=meet,
            sport_type=sport,
            name="Sprint Final",
            grade_min="5",
            grade_max="6",
            gender_limit=models.Event.GenderLimit.MIXED,
            measure_unit="sec",
        )
        runner1 = models.Student.objects.create(
            first_name="Jordan",
            last_name="Lane",
            dob="2012-05-01",
            grade="6",
            house="Blue",
            gender="X",
        )
        runner2 = models.Student.objects.create(
            first_name="Sky",
            last_name="Nguyen",
            dob="2012-08-01",
            grade="6",
            house="Gold",
            gender="X",
        )
        entry1 = models.Entry.objects.create(event=event, student=runner1, round_no=1, heat=1)
        entry2 = models.Entry.objects.create(event=event, student=runner2, round_no=1, heat=1)
        models.Result.objects.create(entry=entry1, rank=1, best_value=Decimal("12.100"), finalized=True)
        models.Result.objects.create(entry=entry2, rank=1, best_value=Decimal("12.100"), finalized=True)

        records = services.compute_scoring_records(meet)
        self.assertEqual(len(records), 2)
        self.assertTrue(all(record.points == Decimal("1.5") for record in records))
        self.assertTrue(all(record.participation == Decimal("0.50") for record in records))

    def test_compute_scoring_records_respects_skip_tie_method(self):
        meet = models.Meet.objects.create(name="Skip", slug="skip", date="2025-04-01")
        models.ScoringRule.objects.create(
            meet=meet,
            points_csv="10,8,6",
            tie_method=models.ScoringRule.TieMethod.SKIP,
        )
        sport = models.SportType.objects.get(key="long-jump")
        event = models.Event.objects.create(
            meet=meet,
            sport_type=sport,
            name="Long Jump",
            grade_min="7",
            grade_max="8",
            gender_limit=models.Event.GenderLimit.MIXED,
            measure_unit="m",
        )
        athletes = [
            models.Student.objects.create(
                first_name="Athlete",
                last_name=str(idx),
                dob="2011-01-01",
                grade="7",
                house="Crimson" if idx % 2 else "Gold",
                gender="X",
            )
            for idx in range(1, 3)
        ]
        for athlete in athletes:
            entry = models.Entry.objects.create(event=event, student=athlete, round_no=1)
            models.Result.objects.create(
                entry=entry,
                rank=1,
                best_value=Decimal("5.500"),
                finalized=True,
            )

        records = services.compute_scoring_records(meet)
        self.assertEqual(len(records), 2)
        self.assertTrue(all(record.points == Decimal("2") for record in records))
