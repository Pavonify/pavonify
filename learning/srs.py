from datetime import timedelta
from django.utils import timezone
from typing import List

from .models import Progress, VocabularyWord, VocabularyList, Student, User


def schedule_review(progress: Progress, correct: bool) -> Progress:
    """Update spaced repetition metadata for a progress record.

    Args:
        progress: Progress instance to update.
        correct: Whether the student's answer was correct.
    Returns:
        The updated Progress instance.
    """
    # Update review stats
    progress.last_seen = timezone.now()
    progress.review_count = (progress.review_count or 0) + 1

    # Simple interval adjustment: double on success, reset on failure
    if correct:
        progress.interval = max(1, progress.interval * 2)
    else:
        progress.interval = 1

    # Schedule next review
    progress.next_due = progress.last_seen + timedelta(days=progress.interval)
    progress.save()
    return progress


def get_due_words(student: Student, limit: int = 10) -> List[VocabularyWord]:
    """Return vocabulary words due for review for a student.

    Looks up vocabulary lists assigned to the student's classes and returns
    words whose review is due (or has not been attempted yet).

    Args:
        student: Student instance whose words are being queried.
        limit: Maximum number of words to return.
    Returns:
        A list of due VocabularyWord instances.
    """
    try:
        user = User.objects.get(username=student.username)
    except User.DoesNotExist:
        return []

    lists = VocabularyList.objects.filter(linked_classes__students=student).distinct()
    words = VocabularyWord.objects.filter(list__in=lists).distinct()

    now = timezone.now()
    due: List[VocabularyWord] = []
    for word in words:
        progress = Progress.objects.filter(student=user, word=word).first()
        if not progress or not progress.next_due or progress.next_due <= now:
            due.append(word)
        if len(due) >= limit:
            break
    return due
