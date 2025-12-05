"""Forms for the sportsday application."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils.text import slugify

from . import models, services


@dataclass(frozen=True)
class ScoringPreset:
    """Simple structure used to render scoring presets."""

    key: str
    label: str
    points_csv: str
    participation_point: Decimal


SCORING_PRESETS: tuple[ScoringPreset, ...] = (
    ScoringPreset(
        key="standard",
        label="Standard podium (10,8,6,5,4,3,2,1)",
        points_csv="10,8,6,5,4,3,2,1",
        participation_point=Decimal("0.00"),
    ),
    ScoringPreset(
        key="extended",
        label="Extended finals (12,10,8,6,5,4,3,2,1)",
        points_csv="12,10,8,6,5,4,3,2,1",
        participation_point=Decimal("0.00"),
    ),
    ScoringPreset(
        key="participation",
        label="Participation bonus (+0.50 per start)",
        points_csv="10,8,6,5,4,3,2,1",
        participation_point=Decimal("0.50"),
    ),
)


LIGHT_TEXT_INPUT_CLASSES = (
    "mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 "
    "shadow-sm focus:border-sky-500 focus:ring focus:ring-sky-200/60 focus:outline-none"
)
LIGHT_CHECKBOX_CLASSES = (
    "h-4 w-4 rounded border-slate-300 text-sky-600 focus:ring-sky-500 focus:ring-offset-0"
)
LARGE_TEXT_INPUT_CLASSES = (
    "mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-3 text-lg font-semibold text-slate-900 "
    "shadow-sm focus:border-sky-500 focus:ring-2 focus:ring-sky-200/60 focus:outline-none"
)
LARGE_CHECKBOX_CLASSES = "h-5 w-5 rounded border-slate-300 focus:ring-offset-0"


class MeetBasicsForm(forms.ModelForm):
    """Collects the fields required to create a meet."""

    scoring_preset = forms.ChoiceField(
        choices=[("", "Choose preset…")] + [(preset.key, preset.label) for preset in SCORING_PRESETS]
        + [("custom", "Custom scoring")],
        required=False,
        label="Scoring preset",
    )
    points_csv = forms.CharField(label="Points per placing", max_length=120)
    participation_point = forms.DecimalField(
        label="Participation points",
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0.00"),
    )
    tie_method = forms.ChoiceField(
        label="Tie handling",
        choices=models.ScoringRule.TieMethod.choices,
        initial=models.ScoringRule.TieMethod.SHARE,
    )

    class Meta:
        model = models.Meet
        fields = (
            "name",
            "slug",
            "date",
            "start_time",
            "end_time",
            "location",
            "max_events_per_student",
            "notes",
        )
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, scoring_rule: models.ScoringRule | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        if scoring_rule:
            self.initial.setdefault("points_csv", scoring_rule.points_csv)
            self.initial.setdefault("participation_point", scoring_rule.participation_point)
            self.initial.setdefault("tie_method", scoring_rule.tie_method)
            self.initial.setdefault("scoring_preset", self._match_preset(scoring_rule))
        else:
            default_preset = SCORING_PRESETS[0]
            self.initial.setdefault("scoring_preset", default_preset.key)
            self.initial.setdefault("points_csv", default_preset.points_csv)
            self.initial.setdefault("participation_point", default_preset.participation_point)
            self.initial.setdefault("tie_method", models.ScoringRule.TieMethod.SHARE)

        text_widgets = (
            forms.TextInput,
            forms.NumberInput,
            forms.Select,
            forms.Textarea,
            forms.DateInput,
            forms.TimeInput,
        )
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} {LIGHT_CHECKBOX_CLASSES}".strip()
            elif isinstance(widget, text_widgets):
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} {LIGHT_TEXT_INPUT_CLASSES}".strip()

        number_fields = ("max_events_per_student", "participation_point")
        for name in number_fields:
            widget = self.fields[name].widget
            if isinstance(widget, forms.NumberInput):
                widget.attrs.setdefault("min", "0")

        for name in ("start_time", "end_time"):
            widget = self.fields[name].widget
            if isinstance(widget, forms.TimeInput):
                widget.attrs.setdefault("step", "60")

    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get("name", "")
        slug = cleaned_data.get("slug")
        if not slug:
            slug = slugify(name)
        else:
            slug = slugify(slug)
        if not slug:
            self.add_error("slug", "Enter a short identifier or adjust the meet name to auto-generate one.")
        else:
            cleaned_data["slug"] = self._build_unique_slug(slug)
        start, end = cleaned_data.get("start_time"), cleaned_data.get("end_time")
        if start and end and start >= end:
            self.add_error("end_time", "End time must be after the start time.")
        preset = cleaned_data.get("scoring_preset")
        if preset and preset != "custom":
            match = next((item for item in SCORING_PRESETS if item.key == preset), None)
            if match:
                cleaned_data["points_csv"] = match.points_csv
                cleaned_data["participation_point"] = match.participation_point
        return cleaned_data

    def _build_unique_slug(self, candidate: str) -> str:
        """Ensure the provided slug is unique."""

        base = candidate or slugify(self.cleaned_data.get("name", "")) or "meet"
        slug = base
        index = 2
        queryset = models.Meet.objects.all()
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        while queryset.filter(slug=slug).exists():
            slug = f"{base}-{index}"
            index += 1
        return slug

    def _match_preset(self, scoring_rule: models.ScoringRule) -> str:
        for preset in SCORING_PRESETS:
            if (
                scoring_rule.points_csv == preset.points_csv
                and scoring_rule.participation_point == preset.participation_point
            ):
                return preset.key
        return "custom"


class SportTypeForm(forms.ModelForm):
    """Create or update a sport type exposed to event builders."""

    _INPUT_CLASS = (
        "w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 "
        "text-sm text-slate-100"
    )

    _CHECKBOX_CLASS = "h-4 w-4 rounded border-slate-600 text-sky-500"

    class Meta:
        model = models.SportType
        fields = (
            "key",
            "label",
            "archetype",
            "default_unit",
            "default_capacity",
            "default_attempts",
            "supports_heats",
            "supports_finals",
            "requires_time_for_first_place",
            "notes",
        )
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._apply_input_styling()

    def clean_key(self) -> str:
        key = slugify(self.cleaned_data.get("key", ""))
        if not key:
            raise ValidationError("Enter a short unique key for this sport.")
        return key

    def _apply_input_styling(self) -> None:
        """Apply consistent Tailwind styling to form widgets."""

        standard_inputs = (
            "key",
            "label",
            "archetype",
            "default_unit",
            "default_capacity",
            "default_attempts",
            "notes",
        )
        checkbox_fields = (
            "supports_heats",
            "supports_finals",
            "requires_time_for_first_place",
        )

        for field_name in standard_inputs:
            widget = self.fields[field_name].widget
            widget.attrs["class"] = self._merge_classes(
                widget.attrs.get("class", ""), self._INPUT_CLASS
            )

        for field_name in ("default_capacity", "default_attempts"):
            widget = self.fields[field_name].widget
            if "min" not in widget.attrs:
                widget.attrs["min"] = "1"

        for field_name in checkbox_fields:
            widget = self.fields[field_name].widget
            widget.attrs["class"] = self._merge_classes(
                widget.attrs.get("class", ""), self._CHECKBOX_CLASS
            )

    @staticmethod
    def _merge_classes(existing: str, new: str) -> str:
        existing_classes = existing.split()
        new_classes = new.split()
        combined = existing_classes + [cls for cls in new_classes if cls not in existing_classes]
        return " ".join(filter(None, combined))


class EventConfigForm(forms.ModelForm):
    """Form used to configure a single event."""

    schedule_dt = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        label="Schedule",
    )

    class Meta:
        model = models.Event
        fields = (
            "sport_type",
            "name",
            "grade_min",
            "grade_max",
            "gender_limit",
            "capacity",
            "attempts",
            "schedule_dt",
            "location",
            "assigned_teachers",
            "notes",
        )
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, teacher_queryset=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if teacher_queryset is not None:
            self.fields["assigned_teachers"].queryset = teacher_queryset
        self.fields["assigned_teachers"].required = False
        self.fields["notes"].required = False

        text_widgets = (
            forms.TextInput,
            forms.NumberInput,
            forms.Select,
            forms.Textarea,
            forms.DateTimeInput,
        )
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} {LIGHT_CHECKBOX_CLASSES}".strip()
            elif isinstance(widget, text_widgets):
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} {LIGHT_TEXT_INPUT_CLASSES}".strip()

        for name in ("capacity", "attempts"):
            widget = self.fields[name].widget
            if isinstance(widget, forms.NumberInput):
                widget.attrs.setdefault("min", "1")

        self.fields["assigned_teachers"].widget.attrs.setdefault("size", "6")

    def clean(self):
        cleaned_data = super().clean()
        sport_type: models.SportType | None = cleaned_data.get("sport_type")
        attempts = cleaned_data.get("attempts")
        if sport_type and sport_type.archetype == models.SportType.Archetype.TRACK_TIME:
            cleaned_data["attempts"] = 1
        if attempts and attempts < 1:
            self.add_error("attempts", "Attempts must be at least 1.")
        grade_min = cleaned_data.get("grade_min")
        grade_max = cleaned_data.get("grade_max")
        if grade_min and grade_max and self._normalise_grade(grade_min) > self._normalise_grade(grade_max):
            self.add_error("grade_max", "Maximum grade must be greater than or equal to the minimum grade.")
        return cleaned_data

    def save(self, commit: bool = True):
        event: models.Event = super().save(commit=False)
        sport_type: models.SportType = event.sport_type
        if sport_type:
            event.measure_unit = sport_type.default_unit
        if commit:
            event.save()
            self.save_m2m()
        return event

    def _normalise_grade(self, grade: str) -> tuple[int, str]:
        return models._grade_key(grade)


class StudentUploadForm(forms.Form):
    """Handles CSV uploads for students."""

    file = forms.FileField()

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        if not uploaded.name.lower().endswith(".csv"):
            raise ValidationError("Upload a CSV file.")
        return uploaded


class TeacherUploadForm(forms.Form):
    """Handles CSV uploads for teachers."""

    file = forms.FileField()

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        if not uploaded.name.lower().endswith(".csv"):
            raise ValidationError("Upload a CSV file.")
        return uploaded


class StudentForm(forms.ModelForm):
    """Collect core student details for manual entry."""

    class Meta:
        model = models.Student
        fields = (
            "first_name",
            "last_name",
            "dob",
            "grade",
            "house",
            "gender",
            "external_id",
            "is_active",
        )
        widgets = {
            "dob": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            existing = widget.attrs.get("class", "")
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = f"{existing} {LIGHT_CHECKBOX_CLASSES}".strip()
            else:
                widget.attrs["class"] = f"{existing} {LIGHT_TEXT_INPUT_CLASSES}".strip()


class TeacherForm(forms.ModelForm):
    """Collect teacher details for manual entry."""

    class Meta:
        model = models.Teacher
        fields = (
            "first_name",
            "last_name",
            "email",
            "external_id",
        )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{existing} {LIGHT_TEXT_INPUT_CLASSES}".strip()


class EventGenerationForm(forms.Form):
    """Bulk create events for a meet using division presets."""

    sport_types = forms.ModelMultipleChoiceField(
        queryset=models.SportType.objects.none(),
        label="Sport types",
        required=True,
    )
    grades = forms.MultipleChoiceField(
        label="Grades",
        required=True,
        choices=(),
    )
    genders = forms.MultipleChoiceField(
        label="Genders",
        required=True,
        choices=models.Event.GenderLimit.choices,
    )
    name_pattern = forms.CharField(
        label="Naming pattern",
        initial="{grade} {gender_label} {sport}",
        help_text="Use placeholders {grade}, {gender}, {gender_label}, and {sport}.",
    )
    capacity_override = forms.IntegerField(
        label="Capacity override",
        min_value=1,
        required=False,
    )
    attempts_override = forms.IntegerField(
        label="Attempts override",
        min_value=1,
        required=False,
    )
    rounds_total = forms.IntegerField(
        label="Rounds",
        min_value=1,
        required=False,
    )

    def __init__(self, *args, grades: list[str] | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["sport_types"].queryset = models.SportType.objects.order_by("label")
        grade_options = grades or list(
            models.Student.objects.values_list("grade", flat=True).distinct().order_by("grade")
        )
        if not grade_options:
            grade_options = ["NUR", "UKG", *[f"G{i}" for i in range(1, 13)]]
        grade_options = sorted(grade_options, key=models._grade_key)
        self.fields["grades"].choices = [(grade, grade) for grade in grade_options]
        self.fields["genders"].choices = models.Event.GenderLimit.choices
        select_class = LIGHT_TEXT_INPUT_CLASSES
        for key in ("sport_types", "grades", "genders"):
            self.fields[key].widget.attrs.update({"class": select_class, "size": "6"})
        text_class = LIGHT_TEXT_INPUT_CLASSES
        for key in ("name_pattern", "capacity_override", "attempts_override", "rounds_total"):
            self.fields[key].widget.attrs.update({"class": text_class})

    def clean_name_pattern(self):
        pattern = self.cleaned_data["name_pattern"].strip()
        if not pattern:
            raise ValidationError("Provide a naming pattern for generated events.")
        return pattern


class BulkEntryAssignmentForm(forms.Form):
    """Bulk add entries to a meet via CSV or automated rules."""

    MODE_CSV = "csv"
    MODE_RULES = "rules"

    mode = forms.ChoiceField(
        label="Assignment mode",
        choices=((MODE_CSV, "CSV upload"), (MODE_RULES, "Rule-based")),
        initial=MODE_CSV,
    )
    csv_file = forms.FileField(label="Entries CSV", required=False)
    events = forms.ModelMultipleChoiceField(
        queryset=models.Event.objects.none(),
        label="Target events",
        required=False,
        help_text="Select the events/divisions to populate when using rule-based assignment.",
    )

    def __init__(self, *args, meet: models.Meet, **kwargs) -> None:
        self.meet = meet
        super().__init__(*args, **kwargs)
        self.fields["events"].queryset = meet.events.order_by("name")
        control_class = LIGHT_TEXT_INPUT_CLASSES
        self.fields["mode"].widget.attrs.update({"class": control_class})
        self.fields["csv_file"].widget.attrs.update({"class": control_class})
        self.fields["events"].widget.attrs.update({"class": control_class, "size": "8"})

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get("mode")
        if mode == self.MODE_CSV:
            uploaded = cleaned.get("csv_file")
            if not uploaded:
                self.add_error("csv_file", "Upload a CSV file containing entries.")
            elif not uploaded.name.lower().endswith(".csv"):
                self.add_error("csv_file", "Only CSV uploads are supported.")
        elif mode == self.MODE_RULES:
            events = cleaned.get("events")
            if not events:
                self.add_error("events", "Select at least one event to populate.")
        return cleaned


class EventImportForm(forms.Form):
    """Upload CSV files for automated event creation."""

    csv_file = forms.FileField(label="Events CSV")
    capacity_override = forms.IntegerField(
        label="Max competitors per event (optional)", required=False, min_value=1
    )

    def clean_csv_file(self):
        upload = self.cleaned_data["csv_file"]
        if upload and not upload.name.lower().endswith(".csv"):
            raise ValidationError("Please upload a CSV file.")
        return upload

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        text_class = LIGHT_TEXT_INPUT_CLASSES
        for field_name in self.fields:
            widget = self.fields[field_name].widget
            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{existing} {text_class}".strip()


class EventBackupUploadForm(forms.Form):
    """Upload a full-meet backup to recreate events and results."""

    csv_file = forms.FileField(label="Backup CSV")

    def clean_csv_file(self):
        upload = self.cleaned_data["csv_file"]
        if upload and not upload.name.lower().endswith(".csv"):
            raise ValidationError("Please upload a CSV file.")
        return upload

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        text_class = LIGHT_TEXT_INPUT_CLASSES
        for field_name in self.fields:
            widget = self.fields[field_name].widget
            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{existing} {text_class}".strip()

class StartListAddForm(forms.Form):
    """Allow coordinators to add a student to an event start list."""

    student = forms.ModelChoiceField(queryset=models.Student.objects.none(), label="Student")
    round_no = forms.TypedChoiceField(
        label="Round",
        coerce=int,
        choices=(),
    )

    def __init__(self, *args, event: models.Event, queryset=None, initial_round: int = 1, **kwargs) -> None:
        self.event = event
        super().__init__(*args, **kwargs)
        if queryset is None:
            queryset = models.Student.objects.order_by("last_name", "first_name")
        self.fields["student"].queryset = queryset

        rounds = [(str(number), f"Round {number}") for number in range(1, event.rounds_total + 1)]
        self.fields["round_no"].choices = rounds
        self.fields["round_no"].initial = str(initial_round)
        if event.rounds_total == 1:
            self.fields["round_no"].widget = forms.HiddenInput()

        for field_name in ("student", "round_no"):
            widget = self.fields[field_name].widget
            if isinstance(widget, forms.HiddenInput):
                continue
            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{existing} {LIGHT_TEXT_INPUT_CLASSES}".strip()

    def clean_student(self):
        student: models.Student = self.cleaned_data["student"]
        if not student.is_active:
            raise ValidationError("Student is inactive.")
        return student

    def clean(self):
        cleaned_data = super().clean()
        student: models.Student | None = cleaned_data.get("student")
        round_no: int | None = cleaned_data.get("round_no")
        if not student or not round_no:
            return cleaned_data

        event = self.event
        if event.entries.filter(student=student, round_no=round_no).exists():
            self.add_error("student", "Student is already entered for this round.")

        if not self._grade_in_range(student.grade, event.grade_min, event.grade_max):
            self.add_error("student", "Student is outside the allowed grade range for this event.")

        if event.gender_limit != models.Event.GenderLimit.MIXED and student.gender != event.gender_limit:
            self.add_error("student", "Student does not match the gender limit for this event.")

        meet_limit = event.meet.max_events_per_student
        if meet_limit:
            total_entries = models.Entry.objects.filter(event__meet=event.meet, student=student).count()
            if total_entries >= meet_limit:
                self.add_error("student", "Student has reached the maximum events for this meet.")

        if not event.sport_type.supports_heats:
            current_count = event.entries.filter(round_no=round_no).count()
            if current_count >= event.capacity:
                self.add_error("student", "This event is already at capacity for the selected round.")

        return cleaned_data

    def _grade_in_range(self, grade: str, minimum: str, maximum: str) -> bool:
        if any(models.normalise_grade_label(value) == "ALL" for value in (minimum, maximum)):
            return True

        minimum_key = self._normalise_grade(minimum)
        maximum_key = self._normalise_grade(maximum)
        candidate_key = self._normalise_grade(grade)
        if minimum_key > maximum_key:
            minimum_key, maximum_key = maximum_key, minimum_key
        return minimum_key <= candidate_key <= maximum_key

    def _normalise_grade(self, grade: str) -> tuple[int, str]:
        return models._grade_key(grade)


class BaseResultForm(forms.Form):
    """Common fields for result capture regardless of archetype."""

    entry_id = forms.IntegerField(widget=forms.HiddenInput())
    dns = forms.BooleanField(required=False, label="DNS")
    dq = forms.BooleanField(required=False, label="DQ")

    def __init__(self, *args, entry: models.Entry, **kwargs) -> None:
        self.entry = entry
        super().__init__(*args, **kwargs)
        self.fields["entry_id"].initial = entry.pk
        self.initial.setdefault("dns", entry.status == models.Entry.Status.DNS)
        self.initial.setdefault("dq", entry.status == models.Entry.Status.DQ)
        self.fields["dns"].widget.attrs.update(
            {
                "class": f"{LARGE_CHECKBOX_CLASSES} text-rose-500 focus:ring-rose-400",
            }
        )
        self.fields["dq"].widget.attrs.update(
            {
                "class": f"{LARGE_CHECKBOX_CLASSES} text-amber-500 focus:ring-amber-400",
            }
        )

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("dns") and cleaned_data.get("dq"):
            raise ValidationError("Choose either DNS or DQ, not both.")
        if cleaned_data.get("dns"):
            cleaned_data["status"] = models.Entry.Status.DNS
        elif cleaned_data.get("dq"):
            cleaned_data["status"] = models.Entry.Status.DQ
        else:
            cleaned_data["status"] = models.Entry.Status.CONFIRMED
        entry_id = cleaned_data.get("entry_id")
        if entry_id != self.entry.pk:
            raise ValidationError("Entry mismatch.")
        return cleaned_data


class TrackResultForm(BaseResultForm):
    """Capture finish times for track events."""

    time_display = forms.CharField(required=False, label="Time")

    def __init__(self, *args, entry: models.Entry, **kwargs) -> None:
        super().__init__(*args, entry=entry, **kwargs)
        attempt = entry.attempts.filter(attempt_no=1).first()
        if attempt and attempt.time_seconds is not None:
            self.initial.setdefault("time_display", _format_time(attempt.time_seconds))
        self.fields["time_display"].widget.attrs.update(
            {
                "class": f"{LARGE_TEXT_INPUT_CLASSES} tracking-wide",
                "placeholder": "mm:ss.mmm",
                "autocomplete": "off",
            }
        )

    def clean_time_display(self):
        value = self.cleaned_data.get("time_display")
        try:
            return services.parse_time_to_seconds(value)
        except ValueError as exc:
            raise ValidationError(str(exc))


class FieldDistanceResultForm(BaseResultForm):
    """Capture distances for field events where attempts are measured in metres."""

    def __init__(
        self,
        *args,
        entry: models.Entry,
        attempts: int,
        measure_unit: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, entry=entry, **kwargs)
        attempt_records = {attempt.attempt_no: attempt for attempt in entry.attempts.all()}
        self.distance_fields: list[str] = []
        self.valid_fields: list[str] = []
        self.attempt_field_pairs: list[tuple[str, str, int]] = []
        self.measure_unit = measure_unit or models.SportType.DefaultUnit.METRES
        for attempt_no in range(1, attempts + 1):
            distance_field = f"distance_{attempt_no}"
            valid_field = f"valid_{attempt_no}"
            self.fields[distance_field] = forms.CharField(required=False, label=f"Attempt {attempt_no}")
            self.fields[valid_field] = forms.BooleanField(required=False, initial=True, label="Valid")
            record = attempt_records.get(attempt_no)
            if record:
                if record.distance_m is not None:
                    self.initial.setdefault(distance_field, f"{record.distance_m}")
                self.initial.setdefault(valid_field, record.valid)
            placeholder = "0.000"
            widget_attrs = {
                "class": LARGE_TEXT_INPUT_CLASSES,
                "placeholder": placeholder,
                "autocomplete": "off",
                "inputmode": "decimal",
            }
            if self.measure_unit == models.SportType.DefaultUnit.FEET_INCHES:
                widget_attrs.update({"placeholder": "5'11\"", "inputmode": "text"})
            self.fields[distance_field].widget.attrs.update(
                widget_attrs
            )
            self.fields[valid_field].widget.attrs.update(
                {
                    "class": f"{LARGE_CHECKBOX_CLASSES} text-emerald-600 focus:ring-emerald-400",
                }
            )
            self.distance_fields.append(distance_field)
            self.valid_fields.append(valid_field)
            self.attempt_field_pairs.append((distance_field, valid_field, attempt_no))
        self.attempt_numbers = list(range(1, attempts + 1))
        self.attempt_bound_fields = [
            (self[distance_field], self[valid_field], attempt_no)
            for distance_field, valid_field, attempt_no in self.attempt_field_pairs
        ]

    def clean(self):
        cleaned = super().clean()
        attempts: list[dict[str, object]] = []
        for field_name in list(self.fields.keys()):
            if not field_name.startswith("distance_"):
                continue
            attempt_no = int(field_name.split("_")[1])
            valid = bool(self.cleaned_data.get(f"valid_{attempt_no}", True))
            distance_value = self.cleaned_data.get(field_name)
            if distance_value in (None, ""):
                parsed = None
            else:
                try:
                    parsed = services.normalize_distance(distance_value, unit=self.measure_unit)
                except ValueError as exc:
                    self.add_error(field_name, str(exc))
                    parsed = None
            attempts.append({"attempt_no": attempt_no, "value": parsed, "valid": valid})
        cleaned["attempts"] = sorted(attempts, key=lambda item: item["attempt_no"])
        return cleaned


class FieldCountResultForm(BaseResultForm):
    """Capture integer counts for strength-based field events."""

    count = forms.IntegerField(required=False, min_value=0, label="Count")

    def __init__(self, *args, entry: models.Entry, **kwargs) -> None:
        super().__init__(*args, entry=entry, **kwargs)
        attempt = entry.attempts.filter(attempt_no=1).first()
        if attempt and attempt.count is not None:
            self.initial.setdefault("count", attempt.count)
        self.fields["count"].widget.attrs.update(
            {
                "class": LARGE_TEXT_INPUT_CLASSES,
                "autocomplete": "off",
                "inputmode": "numeric",
            }
        )


class RankOnlyResultForm(BaseResultForm):
    """Capture manual ranking data for events scored by placing only."""

    rank = forms.IntegerField(required=False, min_value=1, label="Rank")
    time_display = forms.CharField(required=False, label="Time (optional)")

    def __init__(self, *args, entry: models.Entry, field_size: int, **kwargs) -> None:
        super().__init__(*args, entry=entry, **kwargs)
        result = getattr(entry, "result", None)
        if result and result.rank:
            self.initial.setdefault("rank", result.rank)
        attempt = entry.attempts.filter(attempt_no=1).first()
        if attempt and attempt.time_seconds is not None:
            self.initial.setdefault("time_display", _format_time(attempt.time_seconds))
        self.fields["rank"].widget.attrs.update({"max": field_size})
        self.fields["rank"].widget.attrs.update(
            {
                "class": LARGE_TEXT_INPUT_CLASSES,
                "autocomplete": "off",
                "inputmode": "numeric",
            }
        )
        self.fields["time_display"].widget.attrs.update(
            {
                "class": LARGE_TEXT_INPUT_CLASSES,
                "placeholder": "mm:ss.mmm",
                "autocomplete": "off",
            }
        )

    def clean_time_display(self):
        value = self.cleaned_data.get("time_display")
        try:
            return services.parse_time_to_seconds(value)
        except ValueError as exc:
            raise ValidationError(str(exc))


def _format_time(value: Decimal) -> str:
    minutes = int(value // Decimal(60))
    seconds = value - minutes * Decimal(60)
    if minutes:
        return f"{minutes}:{seconds:.3f}".replace(" ", "")
    return f"{seconds:.3f}".replace(" ", "")


__all__ = [
    "EventConfigForm",
    "FieldCountResultForm",
    "FieldDistanceResultForm",
    "MeetBasicsForm",
    "RankOnlyResultForm",
    "SCORING_PRESETS",
    "StartListAddForm",
    "StudentUploadForm",
    "TeacherUploadForm",
    "TrackResultForm",
]
