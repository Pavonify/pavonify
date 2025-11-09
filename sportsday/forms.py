"""Forms for the Sports Day module."""
from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError
from django.utils.text import slugify

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


class MeetForm(forms.ModelForm):
    """Form used for creating and editing meets."""

    allowed_grades = forms.MultipleChoiceField(
        label="Eligible grades",
        choices=models.GRADE_LEVELS,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Tick the grade levels that are allowed to participate in this meet.",
    )
    access_code = forms.CharField(
        label="Access code",
        required=False,
        help_text="Optional code required for coordinators to access the meet dashboard.",
        widget=forms.PasswordInput(render_value=True),
    )
    clear_access_code = forms.BooleanField(
        label="Remove existing access code",
        required=False,
    )

    class Meta:
        model = models.Meet
        fields = (
            "name",
            "slug",
            "date",
            "allowed_grades",
            "max_events_per_student",
            "is_locked",
        )
        help_texts = {
            "slug": "Unique identifier used in URLs. Letters, numbers, hyphens only.",
        }
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "max_events_per_student": forms.NumberInput(attrs={"min": 1}),
            "slug": forms.TextInput(attrs={"placeholder": "e.g. harrow-sports-day"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            if self.instance and self.instance.pk and self.instance.allowed_grades:
                self.fields["allowed_grades"].initial = self.instance.allowed_grades
            else:
                self.fields["allowed_grades"].initial = [choice[0] for choice in models.GRADE_LEVELS]
        if self.instance and self.instance.pk and self.instance.access_code_hash:
            self.fields["access_code"].help_text = (
                "Leave blank to keep the existing code or enter a new one."
            )
        else:
            self.fields["clear_access_code"].widget = forms.HiddenInput()

    def clean_allowed_grades(self) -> list[str]:
        selected = self.cleaned_data.get("allowed_grades") or []
        return list(dict.fromkeys(selected))

    def clean_slug(self) -> str:
        slug = self.cleaned_data.get("slug", "")
        if not slug:
            name = self.cleaned_data.get("name", "")
            slug = name
        slug = slugify(slug)
        slug = forms.fields.SlugField().clean(slug)
        return slug

    def save(self, commit: bool = True):
        instance: models.Meet = super().save(commit=False)
        instance.allowed_grades = self.cleaned_data.get("allowed_grades", [])
        access_code = self.cleaned_data.get("access_code")
        if access_code:
            instance.set_access_code(access_code)
        elif self.cleaned_data.get("clear_access_code"):
            instance.access_code_hash = ""
        if commit:
            instance.save()
            self.save_m2m()
        return instance


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
