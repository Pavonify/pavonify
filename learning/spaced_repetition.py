from datetime import timedelta
import random
from django.db.models import Q
from django.utils import timezone
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
    words = [p.word for p in progress_qs[:limit]]
    if len(words) < limit:
        reviewed_ids = Progress.objects.filter(student=user).values_list("word_id", flat=True)
        remaining = (
            VocabularyWord.objects.filter(list=vocab_list)
            .exclude(id__in=reviewed_ids)
            [: limit - len(words)]
        )
        words.extend(list(remaining))
    random.shuffle(words)
    return words


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
