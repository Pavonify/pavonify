from __future__ import annotations

import datetime
from typing import Any, List

from django.conf import settings
from django.core import signing
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
import hashlib

from django.utils.crypto import constant_time_compare, get_random_string


class TimestampedModel(models.Model):
    """Abstract base model that stores creation and update timestamps."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class House(TimestampedModel):
    """Simple model representing a house."""

    name = models.CharField(max_length=64, unique=True)
    slug = models.SlugField(max_length=64, unique=True)
    color = models.CharField(max_length=16, blank=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:  # pragma: no cover - simple repr
        return self.name


class Student(TimestampedModel):
    external_id = models.CharField(max_length=64, blank=True)
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    dob = models.DateField()
    grade = models.CharField(max_length=10)
    house = models.CharField(max_length=32)
    gender = models.CharField(max_length=16)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("last_name", "first_name")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self) -> str:  # pragma: no cover - simple repr
        return self.full_name


GRADE_LEVELS: list[tuple[str, str]] = [
    ("NURSERY", "Nursery"),
    ("KG", "KG"),
    ("G1", "G1"),
    ("G2", "G2"),
    ("G3", "G3"),
    ("G4", "G4"),
    ("G5", "G5"),
    ("G6", "G6"),
    ("G7", "G7"),
    ("G8", "G8"),
    ("G9", "G9"),
    ("G10", "G10"),
    ("G11", "G11"),
    ("G12", "G12"),
]


class Meet(TimestampedModel):
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    date = models.DateField()
    access_code_hash = models.CharField(max_length=128, blank=True)
    max_events_per_student = models.PositiveIntegerField(default=3)
    is_locked = models.BooleanField(default=False)
    allowed_grades = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ("-date", "name")

    def __str__(self) -> str:  # pragma: no cover - simple repr
        return self.name

    def set_access_code(self, code: str) -> None:
        self.access_code_hash = SportsdayAccessConfig.hash_code(code)

    def check_access_code(self, candidate: str) -> bool:
        if not self.access_code_hash:
            return False
        return SportsdayAccessConfig.verify_code(candidate, self.access_code_hash)

    @property
    def allowed_grades_display(self) -> str:
        """Return a human-readable representation of the allowed grade list."""

        if not self.allowed_grades:
            return "All grades"
        labels = dict(GRADE_LEVELS)
        return ", ".join(labels.get(code, code) for code in self.allowed_grades)


class Event(TimestampedModel):
    EVENT_TIME = "TIME"
    EVENT_DISTANCE = "DISTANCE"
    EVENT_COUNT = "COUNT"
    EVENT_RANK = "RANK"
    EVENT_TYPES = (
        (EVENT_TIME, "Time"),
        (EVENT_DISTANCE, "Distance"),
        (EVENT_COUNT, "Count"),
        (EVENT_RANK, "Rank"),
    )

    GENDER_MALE = "M"
    GENDER_FEMALE = "F"
    GENDER_MIXED = "X"
    GENDER_LIMITS = (
        (GENDER_MALE, "Male"),
        (GENDER_FEMALE, "Female"),
        (GENDER_MIXED, "Open"),
    )

    meet = models.ForeignKey(Meet, on_delete=models.CASCADE, related_name="events")
    name = models.CharField(max_length=120)
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    gender_limit = models.CharField(max_length=16, choices=GENDER_LIMITS, default=GENDER_MIXED)
    grade_min = models.CharField(max_length=10)
    grade_max = models.CharField(max_length=10)
    capacity = models.PositiveIntegerField(default=8, validators=[MinValueValidator(1), MaxValueValidator(128)])
    rounds = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(8)])
    measure_unit = models.CharField(max_length=16, default="sec")
    marshal_pin_hash = models.CharField(max_length=128, blank=True)
    schedule_block = models.CharField(max_length=32, blank=True)
    location = models.CharField(max_length=64, blank=True)
    notes = models.TextField(blank=True)
    is_locked = models.BooleanField(default=False)

    class Meta:
        ordering = ("schedule_block", "name")

    def __str__(self) -> str:  # pragma: no cover - simple repr
        return f"{self.meet.name}: {self.name}"

    def set_marshal_pin(self, pin: str) -> None:
        if pin:
            self.marshal_pin_hash = SportsdayAccessConfig.hash_code(pin)
        else:
            self.marshal_pin_hash = ""

    def verify_marshal_pin(self, candidate: str) -> bool:
        if not self.marshal_pin_hash:
            return True
        return SportsdayAccessConfig.verify_code(candidate, self.marshal_pin_hash)


class Entry(TimestampedModel):
    STATUS_CONFIRMED = "CONFIRMED"
    STATUS_DNS = "DNS"
    STATUS_DQ = "DQ"
    STATUS_CHOICES = (
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_DNS, "Did Not Start"),
        (STATUS_DQ, "Disqualified"),
    )

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="entries")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="entries")
    heat = models.PositiveIntegerField(default=1)
    lane_or_order = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_CONFIRMED)
    override_limits = models.BooleanField(default=False)

    class Meta:
        unique_together = ("event", "student")
        ordering = ("event", "heat", "lane_or_order")

    def __str__(self) -> str:  # pragma: no cover - simple repr
        return f"{self.student.full_name} - {self.event.name}"


class Result(TimestampedModel):
    entry = models.OneToOneField(Entry, on_delete=models.CASCADE, related_name="result")
    round_no = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(8)])
    time_seconds = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    distance_m = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    count = models.IntegerField(null=True, blank=True)
    rank = models.PositiveIntegerField(null=True, blank=True)
    wind = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    notes = models.CharField(max_length=120, blank=True)
    is_final = models.BooleanField(default=False)

    class Meta:
        ordering = ("round_no", "rank", "entry__lane_or_order")


class ScoringRule(TimestampedModel):
    SCOPE_EVENT = "EVENT"
    SCOPE_PARTICIPATION = "PARTICIPATION"
    SCOPE_CHOICES = (
        (SCOPE_EVENT, "Event"),
        (SCOPE_PARTICIPATION, "Participation"),
    )

    TIE_SHARE = "SHARE"
    TIE_SKIP = "SKIP"
    TIE_CHOICES = (
        (TIE_SHARE, "Share"),
        (TIE_SKIP, "Skip"),
    )

    meet = models.ForeignKey(Meet, on_delete=models.CASCADE, related_name="scoring_rules")
    scope = models.CharField(max_length=16, choices=SCOPE_CHOICES, default=SCOPE_EVENT)
    points_csv = models.CharField(max_length=120, default="10,8,6,5,4,3,2,1")
    per_house = models.BooleanField(default=True)
    tie_method = models.CharField(max_length=16, choices=TIE_CHOICES, default=TIE_SHARE)

    class Meta:
        ordering = ("scope", "-created_at")

    def point_map(self) -> List[int]:
        return [int(p.strip()) for p in self.points_csv.split(",") if p.strip()]


class AuditLog(models.Model):
    ts = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)

    class Meta:
        ordering = ("-ts",)

    def __str__(self) -> str:  # pragma: no cover - simple repr
        return f"{self.action} at {self.ts:%Y-%m-%d %H:%M:%S}"


class SportsdayAccessConfig(TimestampedModel):
    """Singleton style model storing global access control configuration."""

    code_hash = models.CharField(max_length=128, blank=True)
    is_enabled = models.BooleanField(default=True)
    cookie_name = models.CharField(max_length=32, default="sportsday_access")
    cookie_ttl_hours = models.PositiveIntegerField(default=12, validators=[MinValueValidator(1), MaxValueValidator(72)])

    class Meta:
        verbose_name = "Sports Day access configuration"

    @classmethod
    def get_solo(cls) -> "SportsdayAccessConfig":
        obj, _ = cls.objects.get_or_create(id=1)
        return obj

    @classmethod
    def hash_code(cls, code: str) -> str:
        if not code:
            return ""
        salt = get_random_string(12)
        digest = hashlib.sha256(f"{salt}:{code}".encode("utf-8")).hexdigest()
        return f"{salt}${digest}"

    @classmethod
    def verify_code(cls, code: str, stored_hash: str) -> bool:
        if not stored_hash:
            return False
        try:
            salt, digest = stored_hash.split("$", 1)
        except ValueError:
            return False
        expected = hashlib.sha256(f"{salt}:{code}".encode("utf-8")).hexdigest()
        return constant_time_compare(expected, digest)

    def set_code(self, code: str) -> None:
        self.code_hash = self.hash_code(code)
        self.save(update_fields=["code_hash", "updated_at"])

    def issue_cookie(self, response, user: Any = None) -> None:
        signer = signing.TimestampSigner()
        ttl_seconds = self.cookie_ttl_hours * 3600
        value = signer.sign(get_random_string(12))
        secure = not getattr(settings, "DEBUG", False)
        response.set_signed_cookie(
            self.cookie_name,
            value,
            max_age=ttl_seconds,
            secure=secure,
            httponly=True,
            samesite="Lax",
        )

    def cookie_valid(self, request) -> bool:
        if not self.is_enabled:
            return True
        signer = signing.TimestampSigner()
        cookie = request.get_signed_cookie(self.cookie_name, default=None)
        if not cookie:
            return False
        try:
            signer.unsign(cookie, max_age=datetime.timedelta(hours=self.cookie_ttl_hours))
            return True
        except signing.BadSignature:
            return False


class LeaderboardSnapshot(TimestampedModel):
    """Stores cached leaderboard JSON for quick retrieval and auditing."""

    meet = models.ForeignKey(Meet, on_delete=models.CASCADE, related_name="leaderboard_snapshots")
    scope = models.CharField(max_length=32)
    payload = models.JSONField(default=dict)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("meet", "scope", "created_at"))]
