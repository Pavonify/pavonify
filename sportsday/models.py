"""Database models for the Sports Day application."""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F


GRADE_ALIASES: dict[str, str] = {
    "NURSERY": "NUR",
    "NURS": "NUR",
    "NUR": "NUR",
    "UKG": "UKG",
    "KG": "UKG",
    "KINDERGARTEN": "UKG",
    "PAR": "PAR",
    "PARENT": "PAR",
    "PARENTS": "PAR",
    "ALL": "ALL",
}

GRADE_ORDER: list[str] = [
    "NUR",
    "UKG",
    *[f"G{i}" for i in range(1, 13)],
    "PAR",
    "ALL",
]

GRADE_RANK = {label: index for index, label in enumerate(GRADE_ORDER)}


def normalise_grade_label(value: str) -> str:
    """Normalise grade labels (e.g. nursery, UKG, numbered grades)."""

    text = (value or "").strip()
    if not text:
        return ""

    upper = text.upper()
    if upper in GRADE_ALIASES:
        upper = GRADE_ALIASES[upper]

    digits = "".join(ch for ch in upper if ch.isdigit())
    if digits:
        return f"G{int(digits)}"
    return upper


def _grade_key(value: str) -> tuple[int, str]:
    """Return a sortable key for grade strings such as G6 or nursery labels."""

    normalised = normalise_grade_label(value)
    rank = GRADE_RANK.get(normalised)
    if rank is not None:
        return (rank, normalised.lower())

    digits = "".join(ch for ch in normalised if ch.isdigit())
    if digits:
        return (int(digits), normalised.lower())
    return (0, normalised.lower())


class Student(models.Model):
    """Represents a student that can participate in a sports day."""

    external_id = models.CharField(max_length=64, blank=True)
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    dob = models.DateField()
    grade = models.CharField(max_length=10)
    house = models.CharField(max_length=64)
    gender = models.CharField(max_length=16)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("last_name", "first_name")

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def entries_for_meet(self, meet_id: int | str | models.Meet) -> models.QuerySet["Entry"]:
        """Return entries for this student filtered to a meet."""

        lookup = meet_id
        if isinstance(meet_id, models.Model):
            lookup = meet_id.pk
        return self.entries.filter(event__meet_id=lookup).select_related("event", "event__meet")


class Teacher(models.Model):
    """Represents a staff member who can be assigned to events."""

    external_id = models.CharField(max_length=64, blank=True)
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    email = models.EmailField(blank=True)

    class Meta:
        ordering = ("last_name", "first_name")

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class Meet(models.Model):
    """A sports day meet containing a collection of events."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    date = models.DateField()
    start_time = models.TimeField(blank=True, null=True)
    end_time = models.TimeField(blank=True, null=True)
    location = models.CharField(max_length=120, blank=True)
    max_events_per_student = models.PositiveIntegerField(default=3)
    notes = models.TextField(blank=True)
    is_locked = models.BooleanField(default=False)

    class Meta:
        ordering = ("-date", "name")

    def __str__(self) -> str:
        return self.name

    def participating_students(self) -> models.QuerySet[Student]:
        """Return distinct students that have entries for this meet."""

        return (
            Student.objects.filter(entries__event__meet=self)
            .distinct()
            .order_by("last_name", "first_name")
        )


class SportType(models.Model):
    """Defines the different types of sports that can be configured."""

    class Archetype(models.TextChoices):
        TRACK_TIME = "TRACK_TIME", "Track (timed)"
        FIELD_DISTANCE = "FIELD_DISTANCE", "Field (distance)"
        FIELD_COUNT = "FIELD_COUNT", "Field (count)"
        RANK_ONLY = "RANK_ONLY", "Rank only"

    class DefaultUnit(models.TextChoices):
        SECONDS = "sec", "Seconds"
        METRES = "m", "Metres"
        CENTIMETRES = "cm", "Centimetres"
        COUNT = "count", "Count"

    key = models.SlugField(unique=True)
    label = models.CharField(max_length=80)
    archetype = models.CharField(max_length=20, choices=Archetype.choices)
    default_unit = models.CharField(max_length=8, choices=DefaultUnit.choices)
    default_capacity = models.PositiveIntegerField(default=8)
    default_attempts = models.PositiveIntegerField(default=1)
    supports_heats = models.BooleanField(default=True)
    supports_finals = models.BooleanField(default=True)
    requires_time_for_first_place = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("label",)

    def __str__(self) -> str:
        return self.label


class Event(models.Model):
    """An individual event within a meet."""

    class GenderLimit(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"
        MIXED = "X", "Mixed/Open"

    meet = models.ForeignKey(Meet, on_delete=models.CASCADE, related_name="events")
    sport_type = models.ForeignKey(SportType, on_delete=models.PROTECT, related_name="events")
    name = models.CharField(max_length=120)
    grade_min = models.CharField(max_length=10)
    grade_max = models.CharField(max_length=10)
    gender_limit = models.CharField(max_length=1, choices=GenderLimit.choices)
    measure_unit = models.CharField(max_length=8)
    capacity = models.PositiveIntegerField(default=8)
    attempts = models.PositiveIntegerField(default=1)
    rounds_total = models.PositiveIntegerField(default=1)
    knockout_qualifiers = models.CharField(max_length=120, blank=True)
    schedule_dt = models.DateTimeField(blank=True, null=True)
    location = models.CharField(max_length=120, blank=True)
    assigned_teachers = models.ManyToManyField(Teacher, blank=True, related_name="events")
    notes = models.TextField(blank=True)
    is_locked = models.BooleanField(default=False)

    class Meta:
        ordering = (F("schedule_dt").asc(nulls_last=True), "pk")

    def __str__(self) -> str:
        return f"{self.meet.name}: {self.name}"

    @property
    def entries_count(self) -> int:
        """Return the number of entries currently attached."""

        return self.entries.count()

    def grade_allows(self, grade: str) -> bool:
        """Return True when the provided grade is within the event division."""

        if any(normalise_grade_label(value) == "ALL" for value in (self.grade_min, self.grade_max)):
            return True

        minimum = _grade_key(self.grade_min)
        maximum = _grade_key(self.grade_max)
        candidate = _grade_key(grade)
        if minimum > maximum:
            minimum, maximum = maximum, minimum
        return minimum <= candidate <= maximum

    def gender_allows(self, gender: str) -> bool:
        if self.gender_limit == self.GenderLimit.MIXED:
            return True
        return (gender or "").upper() == self.gender_limit

    def division_label(self) -> str:
        """Human readable string for grade/gender division."""

        gender_map = dict(self.GenderLimit.choices)
        grades = self.grade_min if self.grade_min == self.grade_max else f"{self.grade_min}–{self.grade_max}"
        return f"{grades} {gender_map.get(self.gender_limit, self.gender_limit)}"


class Entry(models.Model):
    """Represents a student's entry into an event for a specific round."""

    class Status(models.TextChoices):
        CONFIRMED = "CONFIRMED", "Confirmed"
        DNS = "DNS", "Did Not Start"
        DQ = "DQ", "Disqualified"

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="entries")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="entries")
    round_no = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    heat = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    lane_or_order = models.PositiveIntegerField(blank=True, null=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.CONFIRMED)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event", "student", "round_no"], name="unique_entry_per_round"),
        ]
        ordering = ("event", "round_no", "heat", "lane_or_order")

    def __str__(self) -> str:
        return f"{self.student} - {self.event} (Round {self.round_no})"

    def clean(self) -> None:  # pragma: no cover - exercised via save()
        super().clean()
        event = self.event
        student = self.student
        if not event or not student:
            return

        if not event.grade_allows(student.grade):
            raise ValidationError(
                {
                    "student": (
                        "Student is outside the allowed grade range for this event."
                    )
                }
            )
        if not event.gender_allows(student.gender):
            raise ValidationError(
                {
                    "student": "Student does not match the gender limit for this event.",
                }
            )

        meet = event.meet
        if meet and meet.max_events_per_student:
            existing = Entry.objects.filter(event__meet=meet, student=student)
            if self.pk:
                existing = existing.exclude(pk=self.pk)
            if existing.count() >= meet.max_events_per_student:
                raise ValidationError(
                    {
                        "student": (
                            "Student has reached the maximum number of events for this meet."
                        )
                    }
                )

        if event.schedule_dt and not (event.is_locked or event.meet.is_locked):
            from . import services

            clashes = services.compute_timetable_clashes(
                student=student,
                event=event,
                exclude_entry_id=self.pk,
            )
            if clashes:
                conflicting = clashes[0].event
                when = (
                    conflicting.schedule_dt.strftime("%H:%M")
                    if conflicting.schedule_dt
                    else "the same session"
                )
                raise ValidationError(
                    {
                        "student": (
                            f"Student already has an entry in {conflicting.name} at {when}."
                        )
                    }
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Attempt(models.Model):
    """Stores attempt data for a particular entry."""

    entry = models.ForeignKey(Entry, on_delete=models.CASCADE, related_name="attempts")
    attempt_no = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    time_seconds = models.DecimalField(max_digits=8, decimal_places=3, blank=True, null=True)
    distance_m = models.DecimalField(max_digits=8, decimal_places=3, blank=True, null=True)
    count = models.IntegerField(blank=True, null=True)
    valid = models.BooleanField(default=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("entry", "attempt_no")

    def __str__(self) -> str:
        return f"Attempt {self.attempt_no} for {self.entry}"


class Result(models.Model):
    """Finalised result for an entry."""

    entry = models.OneToOneField(Entry, on_delete=models.CASCADE, related_name="result")
    best_value = models.DecimalField(max_digits=8, decimal_places=3, blank=True, null=True)
    rank = models.PositiveIntegerField(blank=True, null=True)
    tiebreak = models.JSONField(default=dict, blank=True)
    finalized = models.BooleanField(default=False)

    class Meta:
        ordering = ("rank", "entry__event__name")

    def __str__(self) -> str:
        return f"Result for {self.entry}"


class ScoringRule(models.Model):
    """Configurable scoring rules for a meet."""

    class TieMethod(models.TextChoices):
        SHARE = "SHARE", "Share points"
        SKIP = "SKIP", "Skip points"

    meet = models.ForeignKey(Meet, on_delete=models.CASCADE, related_name="scoring_rules")
    points_csv = models.CharField(max_length=120, default="10,8,6,5,4,3,2,1")
    participation_point = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    tie_method = models.CharField(max_length=8, choices=TieMethod.choices, default=TieMethod.SHARE)

    class Meta:
        ordering = ("meet", "id")

    def __str__(self) -> str:
        return f"Scoring rules for {self.meet}"


class AuditLog(models.Model):
    """Simple audit trail for user actions."""

    ts = models.DateTimeField(auto_now_add=True)
    action = models.CharField(max_length=64)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-ts",)

    def __str__(self) -> str:
        return f"{self.action} at {self.ts:%Y-%m-%d %H:%M:%S}"
