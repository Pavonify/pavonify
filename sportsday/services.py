"""Domain helpers and result processing logic for the Sports Day app."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Iterable

from django.db import transaction
from django.db.models import F

from types import SimpleNamespace

from . import models

__all__ = [
    "parse_time",
    "parse_distance",
    "parse_count",
    "parse_time_to_seconds",
    "normalize_distance",
    "rank_track",
    "rank_field",
    "apply_qualifiers",
    "scoring_rule_for_meet",
    "compute_scoring_records",
    "compute_timetable_clashes",
    "generate_events",
]


@dataclass(frozen=True)
class ScoringRecord:
    """Container describing the scoring outcome for an entry."""

    entry: models.Entry
    event: models.Event
    student: models.Student
    rank: int | None
    best_value: Decimal | None
    points: Decimal
    participation: Decimal

    @property
    def house(self) -> str:
        return self.student.house or "Unaffiliated"

    @property
    def grade(self) -> str:
        return self.student.grade or "—"

    @property
    def total(self) -> Decimal:
        return (self.points or Decimal("0")) + (self.participation or Decimal("0"))


def parse_time(value: str | float | Decimal | None) -> Decimal | None:
    """Parse time strings such as ``mm:ss.SSS`` or ``ss.SSS`` into seconds."""

    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        candidate = value
    elif isinstance(value, (int, float)):
        candidate = Decimal(str(value))
    else:
        text = value.strip()
        if not text:
            return None
        if ":" in text:
            parts = text.split(":")
            if len(parts) != 2:
                raise ValueError("Use mm:ss.SSS or ss.SSS for times.")
            minutes, seconds = parts
            try:
                candidate = Decimal(minutes) * Decimal(60) + Decimal(seconds)
            except InvalidOperation as exc:  # pragma: no cover - defensive
                raise ValueError("Invalid time value supplied.") from exc
        else:
            try:
                candidate = Decimal(text)
            except InvalidOperation as exc:
                raise ValueError("Invalid time value supplied.") from exc
    if candidate < 0:
        raise ValueError("Time cannot be negative.")
    return candidate.quantize(Decimal("0.001"))


def parse_time_to_seconds(value: str | float | Decimal | None) -> Decimal | None:
    """Backward-compatible wrapper around :func:`parse_time`."""

    return parse_time(value)


def parse_distance(value: str | float | Decimal | None) -> Decimal | None:
    """Parse a decimal distance value in metres."""

    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        candidate = value
    elif isinstance(value, (int, float)):
        candidate = Decimal(str(value))
    else:
        text = value.strip()
        if not text:
            return None
        try:
            candidate = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError("Invalid distance supplied.") from exc
    if candidate < 0:
        raise ValueError("Distance cannot be negative.")
    return candidate.quantize(Decimal("0.001"))


def parse_count(value: str | float | Decimal | None) -> int | None:
    """Parse an integer-based attempt count."""

    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError("Invalid count supplied.")
    if isinstance(value, (int, Decimal)):
        candidate = int(value)
    elif isinstance(value, float):
        if value != int(value):
            raise ValueError("Counts must be whole numbers.")
        candidate = int(value)
    else:
        text = value.strip()
        if not text:
            return None
        try:
            candidate = int(text)
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid count supplied.") from exc
    if candidate < 0:
        raise ValueError("Count cannot be negative.")
    return candidate


def normalize_distance(value: str | float | Decimal | None) -> Decimal | None:
    """Normalise a distance/count entry into metres or integer counts."""

    if value in (None, ""):
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text.endswith("cm"):
            distance = parse_distance(text[:-2])
            if distance is None:
                return None
            return (distance / Decimal(100)).quantize(Decimal("0.001"))
        if text.endswith("m"):
            return parse_distance(text[:-1])
    return parse_distance(value)


def compute_timetable_clashes(
    *,
    student: models.Student,
    event: models.Event,
    window: timedelta = timedelta(minutes=20),
    exclude_entry_id: int | None = None,
) -> list[models.Entry]:
    """Return entries for the same meet that clash with the provided event schedule."""

    if not event.schedule_dt:
        return []
    meet = event.meet
    if not meet:
        return []
    span = abs(window)
    start = event.schedule_dt - span
    end = event.schedule_dt + span
    entries = (
        models.Entry.objects.filter(student=student, event__meet=meet)
        .select_related("event", "event__meet")
        .order_by("event__schedule_dt")
    )
    if exclude_entry_id:
        entries = entries.exclude(pk=exclude_entry_id)
    clashes: list[models.Entry] = []
    for candidate in entries:
        other_dt = candidate.event.schedule_dt
        if other_dt and start <= other_dt <= end:
            clashes.append(candidate)
    return clashes


def generate_events(
    *,
    meet: models.Meet,
    sport_types: Iterable[models.SportType],
    grades: Iterable[str],
    genders: Iterable[str],
    name_pattern: str,
    capacity_override: int | None = None,
    attempts_override: int | None = None,
    rounds_total: int = 1,
) -> dict[str, object]:
    """Create or update events for the provided meet and divisions."""

    summary = {"created": 0, "updated": 0, "skipped": 0, "events": []}
    for sport in sport_types:
        attempts_default = (
            1
            if sport.archetype == models.SportType.Archetype.TRACK_TIME
            else sport.default_attempts
        )
        attempts = attempts_override or attempts_default
        capacity = capacity_override or sport.default_capacity
        for grade in grades:
            for gender in genders:
                gender_label = {
                    models.Event.GenderLimit.FEMALE: "Girls",
                    models.Event.GenderLimit.MALE: "Boys",
                    models.Event.GenderLimit.MIXED: "Mixed",
                }.get(gender, gender)
                name = name_pattern.format(
                    grade=grade,
                    gender=gender,
                    gender_label=gender_label,
                    sport=sport.label,
                )
                defaults = {
                    "measure_unit": sport.default_unit,
                    "capacity": capacity,
                    "attempts": attempts,
                    "rounds_total": rounds_total or 1,
                    "notes": "",
                }
                lookup = {
                    "meet": meet,
                    "sport_type": sport,
                    "name": name,
                    "grade_min": grade,
                    "grade_max": grade,
                    "gender_limit": gender,
                }
                event, created = models.Event.objects.get_or_create(
                    defaults=defaults, **lookup
                )
                if created:
                    summary["created"] += 1
                    summary["events"].append(event)
                    continue
                changed = False
                for field, value in defaults.items():
                    if getattr(event, field) != value:
                        setattr(event, field, value)
                        changed = True
                if changed:
                    event.save()
                    summary["updated"] += 1
                else:
                    summary["skipped"] += 1
    return summary


def rank_track(entries: list[dict]) -> None:
    """Assign ranks on track events using ascending times."""

    for payload in entries:
        payload["rank"] = None
    confirmed = [
        payload
        for payload in entries
        if payload.get("status") == models.Entry.Status.CONFIRMED and payload.get("best_value") is not None
    ]
    missing_times = [
        payload
        for payload in entries
        if payload.get("status") == models.Entry.Status.CONFIRMED and payload.get("best_value") is None
    ]
    if missing_times and not confirmed:
        raise ValueError("First place requires a recorded time.")
    if not confirmed:
        return
    confirmed.sort(key=lambda item: item["best_value"])
    if confirmed[0]["best_value"] is None:
        raise ValueError("First place requires a recorded time.")
    running_rank = 0
    last_time: Decimal | None = None
    for idx, payload in enumerate(confirmed, start=1):
        time_value: Decimal | None = payload.get("best_value")
        if time_value is None:
            continue
        if last_time is None or time_value != last_time:
            running_rank = idx
            last_time = time_value
        payload["rank"] = running_rank


def rank_field(entries: list[dict]) -> None:
    """Assign ranks on field events using best attempts then tiebreak attempts."""

    for payload in entries:
        payload["rank"] = None
        series = payload.get("series") or []
        payload["_sort_key"] = tuple(
            Decimal("0") if attempt is None else -attempt for attempt in series
        )

    contenders = [
        payload
        for payload in entries
        if payload.get("status") == models.Entry.Status.CONFIRMED and payload.get("best_value") is not None
    ]
    contenders.sort(key=lambda item: item["_sort_key"])
    index = 1
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for payload in contenders:
        grouped[payload["_sort_key"]].append(payload)
    for key in sorted(grouped.keys()):
        cohort = grouped[key]
        for payload in cohort:
            payload["rank"] = index
        index += len(cohort)
    for payload in entries:
        payload.pop("_sort_key", None)


def apply_qualifiers(round_entries: Iterable[dict], pattern: str | None) -> list[models.Entry]:
    """Create entries for finalists based on knockout qualifier pattern."""

    if not pattern:
        return []
    segments = [segment.strip() for segment in pattern.split(";") if segment.strip()]
    if not segments:
        return []

    by_heat: dict[int, list[dict]] = defaultdict(list)
    ordered: list[dict] = []
    for payload in round_entries:
        entry: models.Entry = payload["entry"]
        if payload.get("rank") is None:
            continue
        by_heat[entry.heat].append(payload)
        ordered.append(payload)

    per_heat = 0
    extra_slots = 0
    for segment in segments:
        if segment.startswith("Q:"):
            try:
                per_heat = int(segment[2:])
            except ValueError as exc:
                raise ValueError("Invalid qualifier segment.") from exc
        elif segment.startswith("q:"):
            try:
                extra_slots = int(segment[2:])
            except ValueError as exc:
                raise ValueError("Invalid qualifier segment.") from exc
        else:
            raise ValueError("Unrecognised qualifier segment.")

    qualifiers: list[models.Entry] = []
    taken: set[int] = set()
    if per_heat:
        for heat, payloads in by_heat.items():
            ordered_heat = sorted(payloads, key=lambda item: item["rank"])
            for payload in ordered_heat[:per_heat]:
                qualifiers.append(payload["entry"])
                taken.add(payload["entry"].pk)

    ordered.sort(key=lambda item: item.get("best_value") or Decimal("999999"))
    if extra_slots:
        extra_added = 0
        for payload in ordered:
            if extra_added >= extra_slots:
                break
            entry = payload["entry"]
            if entry.pk in taken:
                continue
            if payload.get("best_value") is None:
                continue
            qualifiers.append(entry)
            taken.add(entry.pk)
            extra_added += 1

    if not qualifiers:
        return []

    created: list[models.Entry] = []
    next_round = qualifiers[0].round_no + 1
    with transaction.atomic():
        for finalist in qualifiers:
            event = finalist.event
            if next_round > event.rounds_total:
                continue
            entry, was_created = models.Entry.objects.get_or_create(
                event=event,
                student=finalist.student,
                round_no=next_round,
                defaults={"heat": 1},
            )
            if was_created:
                created.append(entry)
    return created


def scoring_rule_for_meet(meet: models.Meet) -> models.ScoringRule | SimpleNamespace:
    """Return the scoring rule for a meet, falling back to sensible defaults."""

    rule = meet.scoring_rules.order_by("id").first()
    if rule:
        return rule
    return SimpleNamespace(
        meet=meet,
        points_csv="10,8,6,5,4,3,2,1",
        participation_point=Decimal("0"),
        tie_method=models.ScoringRule.TieMethod.SHARE,
    )


def _parse_points_csv(points_csv: str) -> list[Decimal]:
    values: list[Decimal] = []
    for part in points_csv.split(","):
        chunk = part.strip()
        if not chunk:
            continue
        try:
            values.append(Decimal(chunk))
        except InvalidOperation:
            values.append(Decimal("0"))
    return values


def _points_for_position(schedule: list[Decimal], position: int) -> Decimal:
    if position <= 0:
        return Decimal("0")
    index = position - 1
    if index >= len(schedule):
        return Decimal("0")
    return schedule[index]


def compute_scoring_records(meet: models.Meet) -> list[ScoringRecord]:
    """Return scoring records for finalized results in the meet."""

    rule = scoring_rule_for_meet(meet)
    schedule = _parse_points_csv(rule.points_csv)
    participation_value = getattr(rule, "participation_point", Decimal("0")) or Decimal("0")
    participation_value = Decimal(participation_value)

    finalized_results = (
        models.Result.objects.filter(
            entry__event__meet=meet,
            finalized=True,
            entry__status=models.Entry.Status.CONFIRMED,
            entry__round_no=F("entry__event__rounds_total"),
        )
        .select_related("entry__student", "entry__event")
        .order_by("entry__event_id", "rank", "entry__pk")
    )

    per_event: dict[int, list[ScoringRecord]] = defaultdict(list)

    for result in finalized_results:
        entry = result.entry
        per_event[entry.event_id].append(
            ScoringRecord(
                entry=entry,
                event=entry.event,
                student=entry.student,
                rank=result.rank,
                best_value=result.best_value,
                points=Decimal("0"),
                participation=participation_value,
            )
        )

    records: list[ScoringRecord] = []
    for event_id, event_records in per_event.items():
        by_rank: dict[int, list[ScoringRecord]] = defaultdict(list)
        for record in event_records:
            if record.rank is None:
                continue
            by_rank[int(record.rank)].append(record)

        for rank in sorted(by_rank.keys()):
            cohort = by_rank[rank]
            if not cohort:
                continue
            tie_count = len(cohort)
            if getattr(rule, "tie_method", models.ScoringRule.TieMethod.SHARE) == models.ScoringRule.TieMethod.SHARE:
                total_points = Decimal("0")
                for offset in range(tie_count):
                    total_points += _points_for_position(schedule, rank + offset)
                award = total_points / tie_count if tie_count else Decimal("0")
            else:
                award = _points_for_position(schedule, rank)
            award = award.quantize(Decimal("0.01")) if award % 1 else award
            for record in cohort:
                object.__setattr__(record, "points", award)

        records.extend(event_records)

    return records
