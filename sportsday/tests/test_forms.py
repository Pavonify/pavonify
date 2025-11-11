"""Tests for form behaviour in the Sports Day app."""

from __future__ import annotations

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
            "measure_unit": self.sport_type.default_unit,
            "capacity": self.sport_type.default_capacity,
            "attempts": self.sport_type.default_attempts,
            "rounds_total": 1,
        }

    def test_invalid_knockout_pattern_is_ignored(self) -> None:
        """Submitting a malformed qualifier pattern should not block the form."""

        form = forms.EventConfigForm(
            data={
                **self._base_form_data(),
                "knockout_qualifiers": "not a valid qualifier",
            }
        )

        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["knockout_qualifiers"], "")

