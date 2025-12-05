"""Tests for form behaviour in the Sports Day app."""

from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from sportsday import forms, models


class EventConfigFormTests(TestCase):
    """Behavioural tests for :class:`EventConfigForm`."""

    def setUp(self) -> None:
        self.sport_type = models.SportType.objects.create(
            key="sprint",
            label="100m Sprint",
            archetype=models.SportType.Archetype.TRACK_TIME,
            default_unit=models.SportType.DefaultUnit.SECONDS,
            default_capacity=8,
            default_attempts=1,
        )

    def _base_form_data(self) -> dict[str, object]:
        return {
            "sport_type": self.sport_type.pk,
            "name": "100m Sprint",
            "grade_min": "Year 7",
            "grade_max": "Year 7",
            "gender_limit": models.Event.GenderLimit.MIXED,
            "capacity": self.sport_type.default_capacity,
            "attempts": self.sport_type.default_attempts,
        }

    def test_measure_unit_is_set_from_sport_type(self) -> None:
        """The form automatically sets the measure unit based on the sport."""

        form = forms.EventConfigForm(data=self._base_form_data())

        self.assertTrue(form.is_valid())

        event = form.save(commit=False)

        self.assertEqual(event.measure_unit, self.sport_type.default_unit)


class FieldDistanceResultFormTests(TestCase):
    """Ensure field event distance entry honours configured units."""

    def setUp(self) -> None:
        self.meet = models.Meet.objects.create(name="Autumn", slug="autumn", date="2025-01-01")
        self.sport_type = models.SportType.objects.create(
            key="long-jump-ft",
            label="Long Jump",
            archetype=models.SportType.Archetype.FIELD_DISTANCE,
            default_unit=models.SportType.DefaultUnit.FEET_INCHES,
            default_capacity=8,
            default_attempts=1,
        )
        self.event = models.Event.objects.create(
            meet=self.meet,
            sport_type=self.sport_type,
            name="Long Jump",
            grade_min="5",
            grade_max="6",
            gender_limit=models.Event.GenderLimit.MIXED,
            measure_unit=self.sport_type.default_unit,
            attempts=1,
        )
        self.student = models.Student.objects.create(
            first_name="Alex",
            last_name="Smith",
            dob="2013-01-01",
            grade="5",
            house="Blue",
            gender="M",
        )
        self.entry = models.Entry.objects.create(event=self.event, student=self.student, round_no=1)

    def test_imperial_distances_are_parsed(self) -> None:
        prefix = "entry-test"
        form = forms.FieldDistanceResultForm(
            data={
                f"{prefix}-entry_id": self.entry.pk,
                f"{prefix}-distance_1": "15'7\"",
                f"{prefix}-valid_1": "on",
            },
            entry=self.entry,
            attempts=self.event.attempts,
            measure_unit=self.event.measure_unit,
            prefix=prefix,
        )

        self.assertTrue(form.is_valid(), form.errors)
        attempts = form.cleaned_data["attempts"]
        self.assertEqual(attempts[0]["value"], Decimal("4.750"))

