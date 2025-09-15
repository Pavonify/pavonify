from datetime import timedelta
import random
from django.db.models import Q
from django.utils import timezone

from .memory import calculate_memory_strength
from .models import Progress, VocabularyWord, User


def _get_user_from_student(student):
    """Ensure a User object exists for the given Student instance."""
    user, _ = User.objects.get_or_create(
        username=student.username,
        defaults={
            "is_student": True,
            "first_name": student.first_name,
            "last_name": student.last_name,
            "password": student.password,
        },
    )
    return user


def get_due_words(student, vocab_list, limit=20):
    """Return up to ``limit`` words due for review for a student and vocab list."""

    user = _get_user_from_student(student)
    now = timezone.now()

    progress_qs = (
        Progress.objects.filter(student=user, word__list=vocab_list)
        .filter(Q(next_due__lte=now) | Q(next_due__isnull=True))
        .select_related("word")
        .order_by("next_due")
    )

    due_progresses = list(progress_qs[:limit])
    words = [p.word for p in due_progresses]
    word_ids = {word.id for word in words}

    if len(words) < limit:
        reviewed_ids = Progress.objects.filter(student=user).values_list(
            "word_id", flat=True
        )
        remaining_new = (
            VocabularyWord.objects.filter(list=vocab_list)
            .exclude(id__in=reviewed_ids)
            [: limit - len(words)]
        )
        for word in remaining_new:
            if word.id not in word_ids:
                words.append(word)
                word_ids.add(word.id)

    if len(words) < limit:
        weak_progresses = (
            Progress.objects.filter(student=user, word__list=vocab_list)
            .exclude(word_id__in=word_ids)
            .select_related("word")
        )
        sorted_by_strength = sorted(
            weak_progresses,
            key=lambda prog: calculate_memory_strength(prog, now=now),
        )
        for prog in sorted_by_strength:
            if prog.word_id in word_ids:
                continue
            words.append(prog.word)
            word_ids.add(prog.word_id)
            if len(words) >= limit:
                break

    random.shuffle(words)
    return words[:limit]


def schedule_review(student, word_id, correct):
    """Update review schedule and attempt counters for a word."""
    user = _get_user_from_student(student)
    word = VocabularyWord.objects.get(id=word_id)
    progress, _ = Progress.objects.get_or_create(student=user, word=word)

    now = timezone.now()
    progress.last_seen = now
    progress.review_count = (progress.review_count or 0) + 1

    if correct:
        progress.correct_attempts += 1
        progress.interval = max(progress.interval * 2, 1)
    else:
        progress.incorrect_attempts += 1
        progress.interval = 1

    progress.next_due = now + timedelta(days=progress.interval)
    progress.save()
