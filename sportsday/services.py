"""Domain services for the Sports Day module."""
from __future__ import annotations

import csv
import datetime as dt
import io
import math
import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, List, Optional, Sequence

from django.db import transaction

from . import models

TIME_PATTERN = re.compile(r"^(?:(?P<h>\d+):)?(?P<m>\d{1,2}):(?P<s>\d{1,2})(?:[\.,](?P<ms>\d{1,3}))?$")
DISTANCE_PATTERN = re.compile(r"^(?P<meters>\d+)(?:m(?P<cm>\d{1,2}))?(?:[\.,](?P<dec>\d{1,3}))?$")
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y")


class CSVImportError(Exception):
    """Raised when a CSV import cannot be processed."""


@dataclass
class ParsedStudentRow:
    raw: dict
    student: Optional[models.Student]
    is_update: bool


GENDER_ALIASES = {
    "m": "Male",
    "male": "Male",
    "f": "Female",
    "female": "Female",
    "mixed": "Mixed",
    "x": "Mixed",
    "other": "Other",
}


def parse_time_to_seconds(value: str) -> Decimal:
    """Parse a flexible time string into seconds with millisecond precision."""

    if value is None:
        raise ValueError("Time value cannot be None")
    value = value.strip()
    if not value:
        raise ValueError("Time value cannot be blank")
    value = value.replace(" ", "")
    if value.isdigit():
        return Decimal(value)
    match = TIME_PATTERN.match(value.replace(".", ".").replace(",", "."))
    if not match:
        raise ValueError(f"Unsupported time format: {value}")
    hours = int(match.group("h") or 0)
    minutes = int(match.group("m") or 0)
    seconds = int(match.group("s") or 0)
    milliseconds = match.group("ms")
    ms = Decimal(f"0.{milliseconds}") if milliseconds else Decimal("0")
    total_seconds = Decimal(hours * 3600 + minutes * 60 + seconds) + ms
    return total_seconds.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def normalize_distance(value: str) -> Decimal:
    """Convert a distance string to meters with centimeter support."""

    if value is None:
        raise ValueError("Distance value cannot be None")
    clean = value.strip().lower().replace(" ", "")
    clean = clean.replace(",", ".")
    match = DISTANCE_PATTERN.match(clean)
    if match:
        meters = Decimal(match.group("meters"))
        cm = match.group("cm")
        dec = match.group("dec")
        if cm and not dec:
            dec = cm
        fraction = Decimal(f"0.{dec}") if dec else Decimal("0")
        result = meters + fraction
        return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    try:
        return Decimal(clean).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception as exc:  # pragma: no cover - fallback path
        raise ValueError(f"Unsupported distance format: {value}") from exc


def parse_date(value: str) -> dt.date:
    for fmt in DATE_FORMATS:
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {value}")


def normalise_gender(value: str) -> str:
    key = value.strip().lower()
    if key not in GENDER_ALIASES:
        raise ValueError(f"Unsupported gender: {value}")
    return GENDER_ALIASES[key]


def rank_results(values: Sequence[Optional[Decimal]], event_type: str) -> List[Optional[int]]:
    """Return ranks for the given value list according to event type ordering."""

    ordering = []
    for idx, val in enumerate(values):
        if val is None or (isinstance(val, float) and math.isnan(val)):
            continue
        multiplier = 1
        if event_type == models.Event.EVENT_TIME:
            multiplier = 1
        elif event_type in {models.Event.EVENT_DISTANCE, models.Event.EVENT_COUNT}:
            multiplier = -1
        ordering.append((val * multiplier, idx))
    ordering.sort()
    ranks: List[Optional[int]] = [None] * len(values)
    if not ordering:
        return ranks
    current_rank = 1
    previous_value = None
    tied_indices: List[int] = []
    for position, (value, original_idx) in enumerate(ordering, start=1):
        if previous_value is None or value != previous_value:
            if tied_indices:
                _assign_ties(ranks, tied_indices, current_rank, position - 1)
                current_rank = position
                tied_indices = []
            previous_value = value
        tied_indices.append(original_idx)
    if tied_indices:
        _assign_ties(ranks, tied_indices, current_rank, len(ordering))
    return ranks


def _assign_ties(ranks: List[Optional[int]], indices: List[int], start_rank: int, end_position: int) -> None:
    average_rank = (start_rank + end_position) // 2 if len(indices) > 1 else start_rank
    for idx in indices:
        ranks[idx] = average_rank


def allocate_points(event: models.Event, scoring_rule: models.ScoringRule, ranks: Sequence[Optional[int]]) -> List[int]:
    points = scoring_rule.point_map()
    allocations: List[int] = [0] * len(ranks)
    if not any(ranks):
        return allocations

    rank_groups: dict[int, List[int]] = {}
    for idx, rank in enumerate(ranks):
        if rank is None or rank <= 0:
            continue
        rank_groups.setdefault(rank, []).append(idx)

    for rank, indices in rank_groups.items():
        point_index = rank - 1
        if point_index >= len(points):
            continue
        if scoring_rule.tie_method == models.ScoringRule.TIE_SKIP:
            for idx in indices:
                allocations[idx] = points[point_index]
            continue
        if len(indices) == 1:
            allocations[indices[0]] = points[point_index]
            continue
        # SHARE: average points for the tied places
        share_points = points[point_index : point_index + len(indices)]
        if not share_points:
            continue
        average = sum(share_points) / len(share_points)
        for idx in indices:
            allocations[idx] = int(Decimal(average).quantize(Decimal("0"), rounding=ROUND_HALF_UP))
    return allocations


def load_students_from_csv(meet: models.Meet, csv_file: io.TextIOBase, *, user=None) -> List[ParsedStudentRow]:
    """Parse and upsert students from a CSV file-like object."""

    reader = csv.DictReader(csv_file)
    required_headers = {"first_name", "last_name", "dob", "grade", "house", "gender", "external_id"}
    missing = required_headers - set(reader.fieldnames or [])
    if missing:
        raise CSVImportError(f"Missing required columns: {', '.join(sorted(missing))}")

    parsed_rows: List[ParsedStudentRow] = []
    for row in reader:
        if not any(row.values()):
            continue
        try:
            dob = parse_date(row["dob"].strip())
            grade = row["grade"].strip().upper()
            if grade not in {f"G{i}" for i in range(6, 13)}:
                raise ValueError("Grade must be within G6-G12")
            gender = normalise_gender(row["gender"])
        except ValueError as exc:
            raise CSVImportError(str(exc)) from exc
        defaults = {
            "first_name": row["first_name"].strip(),
            "last_name": row["last_name"].strip(),
            "dob": dob,
            "grade": grade,
            "house": row["house"].strip(),
            "gender": gender,
            "is_active": True,
        }
        external_id = row.get("external_id", "").strip()
        student: Optional[models.Student] = None
        is_update = False
        if external_id:
            student, created = models.Student.objects.update_or_create(
                external_id=external_id,
                defaults=defaults,
            )
            is_update = not created
        else:
            matches = models.Student.objects.filter(
                first_name__iexact=defaults["first_name"],
                last_name__iexact=defaults["last_name"],
                dob__range=(dob - dt.timedelta(days=3), dob + dt.timedelta(days=3)),
            )
            if matches.exists():
                student = matches.first()
                for attr, value in defaults.items():
                    setattr(student, attr, value)
                student.save()
                is_update = True
            else:
                student = models.Student.objects.create(**defaults)
        parsed_rows.append(ParsedStudentRow(raw=row, student=student, is_update=is_update))
    if user:
        models.AuditLog.objects.create(user=user, action="UPLOAD_STUDENTS", payload={"count": len(parsed_rows), "meet": meet.slug})
    return parsed_rows


@transaction.atomic
def seed_default_meet() -> models.Meet:
    meet, _ = models.Meet.objects.get_or_create(
        slug="harrow-2026",
        defaults={
            "name": "Harrow Sports Day 2026",
            "date": dt.date.today(),
            "max_events_per_student": 3,
        },
    )
    models.ScoringRule.objects.get_or_create(
        meet=meet,
        scope=models.ScoringRule.SCOPE_EVENT,
        defaults={"points_csv": "10,8,6,5,4,3,2,1", "per_house": True},
    )
    for house_name in ("Churchill", "Montgomery", "Nehru", "Attlee"):
        models.House.objects.get_or_create(name=house_name, defaults={"slug": house_name.lower().replace(" ", "-")})
    return meet
