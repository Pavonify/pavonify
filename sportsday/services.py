"""Domain helpers and result processing logic for the Sports Day app."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable

from django.db import transaction
from django.db.models import F

from types import SimpleNamespace

from . import models

__all__ = [
    "parse_time_to_seconds",
    "normalize_distance",
    "rank_track",
    "rank_field",
    "apply_qualifiers",
    "scoring_rule_for_meet",
    "compute_scoring_records",
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


def parse_time_to_seconds(value: str | float | Decimal | None) -> Decimal | None:
    """Parse a human-friendly time string (mm:ss.mmm or ss.mmm) into seconds."""

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
                raise ValueError("Use mm:ss.mmm or ss.mmm format for times.")
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


def normalize_distance(value: str | float | Decimal | None) -> Decimal | None:
    """Normalise a distance/count entry into metres or integer counts."""

    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        candidate = value
    elif isinstance(value, (int, float)):
        candidate = Decimal(str(value))
    else:
        text = value.strip().lower()
        if not text:
            return None
        if text.endswith("cm"):
            text = text[:-2].strip()
            try:
                candidate = Decimal(text) / Decimal(100)
            except InvalidOperation as exc:
                raise ValueError("Invalid distance supplied.") from exc
        elif text.endswith("m"):
            text = text[:-1].strip()
            try:
                candidate = Decimal(text)
            except InvalidOperation as exc:
                raise ValueError("Invalid distance supplied.") from exc
        else:
            try:
                candidate = Decimal(text)
            except InvalidOperation as exc:
                raise ValueError("Invalid distance supplied.") from exc
    if candidate < 0:
        raise ValueError("Distance/count cannot be negative.")
    return candidate.quantize(Decimal("0.001"))


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
