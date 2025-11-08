"""Forms for the Sports Day module."""
from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError

from . import models


class AccessCodeForm(forms.Form):
    code = forms.CharField(label="Event Access Code", widget=forms.PasswordInput)

    def clean_code(self) -> str:
        value = self.cleaned_data["code"].strip()
        if not value:
            raise ValidationError("Please enter the access code")
        return value


class MarshalPinForm(forms.Form):
    pin = forms.CharField(label="Marshal PIN", min_length=4, max_length=6, widget=forms.PasswordInput)


class StudentUploadForm(forms.Form):
    file = forms.FileField(help_text="Upload a CSV with the required headers.")

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        if uploaded.size > 5 * 1024 * 1024:
            raise ValidationError("The uploaded file is too large.")
        return uploaded


class EventForm(forms.ModelForm):
    class Meta:
        model = models.Event
        fields = (
            "name",
            "event_type",
            "gender_limit",
            "grade_min",
            "grade_max",
            "capacity",
            "rounds",
            "measure_unit",
            "schedule_block",
            "location",
            "notes",
        )


class ResultEntryForm(forms.Form):
    def __init__(self, event: models.Event, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.event = event

    def clean(self):
        cleaned = super().clean()
        return cleaned
