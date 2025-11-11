"""Forms for the sportsday application."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re

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


class EventConfigForm(forms.ModelForm):
    """Form used in the wizard to configure a single event."""

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
            "measure_unit",
            "capacity",
            "attempts",
            "rounds_total",
            "knockout_qualifiers",
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
        self.fields["knockout_qualifiers"].required = False
        self.fields["notes"].required = False

    def clean(self):
        cleaned_data = super().clean()
        sport_type: models.SportType | None = cleaned_data.get("sport_type")
        attempts = cleaned_data.get("attempts")
        if sport_type and sport_type.archetype == models.SportType.Archetype.TRACK_TIME:
            cleaned_data["attempts"] = 1
        if attempts and attempts < 1:
            self.add_error("attempts", "Attempts must be at least 1.")
        rounds_total = cleaned_data.get("rounds_total")
        if rounds_total and rounds_total < 1:
            self.add_error("rounds_total", "Rounds must be at least 1.")
        grade_min = cleaned_data.get("grade_min")
        grade_max = cleaned_data.get("grade_max")
        if grade_min and grade_max and self._normalise_grade(grade_min) > self._normalise_grade(grade_max):
            self.add_error("grade_max", "Maximum grade must be greater than or equal to the minimum grade.")
        return cleaned_data

    def clean_knockout_qualifiers(self):
        value = self.cleaned_data.get("knockout_qualifiers", "")
        if not value:
            return ""
        pattern = re.compile(r"^(?:[Qq]:\d+)(?:;[Qq]:\d+)*$")
        if not pattern.match(value.strip()):
            raise ValidationError("Use the format Q:2;q:2 to describe qualifiers.")
        return value.strip()

    def _normalise_grade(self, grade: str) -> tuple[int, str]:
        digits = "".join(char for char in grade if char.isdigit())
        if digits:
            return (int(digits), "")
        return (0, grade.lower())


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
        minimum_key = self._normalise_grade(minimum)
        maximum_key = self._normalise_grade(maximum)
        candidate_key = self._normalise_grade(grade)
        return minimum_key <= candidate_key <= maximum_key

    def _normalise_grade(self, grade: str) -> tuple[int, str]:
        digits = "".join(char for char in grade if char.isdigit())
        if digits:
            return (int(digits), "")
        return (0, grade.lower())


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
                "class": "h-5 w-5 rounded border-slate-600 text-rose-500 focus:ring-rose-500",
            }
        )
        self.fields["dq"].widget.attrs.update(
            {
                "class": "h-5 w-5 rounded border-slate-600 text-amber-500 focus:ring-amber-500",
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
                "class": "mt-2 w-full rounded-xl border border-slate-700 bg-slate-900/70 px-3 py-3 text-lg font-semibold tracking-wide text-slate-100 focus:border-sky-400 focus:outline-none focus:ring-2 focus:ring-sky-500",
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

    def __init__(self, *args, entry: models.Entry, attempts: int, **kwargs) -> None:
        super().__init__(*args, entry=entry, **kwargs)
        attempt_records = {attempt.attempt_no: attempt for attempt in entry.attempts.all()}
        self.distance_fields: list[str] = []
        self.valid_fields: list[str] = []
        self.attempt_field_pairs: list[tuple[str, str, int]] = []
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
            self.fields[distance_field].widget.attrs.update(
                {
                    "class": "mt-2 w-full rounded-xl border border-slate-700 bg-slate-900/70 px-3 py-3 text-lg font-semibold text-slate-100 focus:border-emerald-400 focus:outline-none focus:ring-2 focus:ring-emerald-500",
                    "placeholder": "0.000",
                    "autocomplete": "off",
                    "inputmode": "decimal",
                }
            )
            self.fields[valid_field].widget.attrs.update(
                {
                    "class": "h-5 w-5 rounded border-slate-600 text-emerald-500 focus:ring-emerald-500",
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
                    parsed = services.normalize_distance(distance_value)
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
                "class": "mt-2 w-full rounded-xl border border-slate-700 bg-slate-900/70 px-3 py-3 text-lg font-semibold text-slate-100 focus:border-amber-400 focus:outline-none focus:ring-2 focus:ring-amber-500",
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
                "class": "mt-2 w-full rounded-xl border border-slate-700 bg-slate-900/70 px-3 py-3 text-lg font-semibold text-slate-100 focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-500",
                "autocomplete": "off",
                "inputmode": "numeric",
            }
        )
        self.fields["time_display"].widget.attrs.update(
            {
                "class": "mt-2 w-full rounded-xl border border-slate-700 bg-slate-900/70 px-3 py-3 text-lg font-semibold text-slate-100 focus:border-sky-400 focus:outline-none focus:ring-2 focus:ring-sky-500",
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
