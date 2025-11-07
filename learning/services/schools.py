"""Utility functions for managing school-based features."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from django.contrib.auth import get_user_model
from django.db.models import QuerySet, Sum

from learning.models import Class, School, Student

User = get_user_model()


@dataclass(frozen=True)
class AggregatedLeaderboard:
    """Container for aggregated leaderboard data used by templates and APIs."""

    top_students: List[dict]
    grade_totals: List[dict]
    language_totals: List[dict]


def _student_queryset_for_school(school: School) -> QuerySet:
    return Student.objects.filter(school=school)


def build_school_leaderboard(school: School, *, limit: int = 50) -> AggregatedLeaderboard:
    """Aggregate leaderboard information for a school."""

    students = _student_queryset_for_school(school)

    top_students = list(
        students.order_by("-total_points").values("id", "first_name", "last_name", "total_points")[:limit]
    )

    grade_totals = list(
        students.values("year_group")
        .annotate(total_points=Sum("total_points"))
        .order_by("-total_points")
    )

    language_totals = list(
        Class.objects.filter(school=school)
        .values("language")
        .annotate(total_points=Sum("students__total_points"))
        .order_by("-total_points")
    )

    return AggregatedLeaderboard(
        top_students=top_students,
        grade_totals=grade_totals,
        language_totals=language_totals,
    )


def school_teachers(school: School) -> Iterable[User]:
    return User.objects.filter(school=school, is_teacher=True).order_by("first_name", "last_name", "username")
