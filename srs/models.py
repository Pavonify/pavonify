from django.db import models
from django.utils import timezone
from decimal import Decimal

from learning.models import Student, Word


class StudentWordProgress(models.Model):
    STATUS_CHOICES = [
        ('new', 'New'),
        ('learning', 'Learning'),
        ('reviewing', 'Reviewing'),
        ('mastered', 'Mastered'),
    ]

    ACTIVITY_CHOICES = [
        ('exposure', 'Exposure'),
        ('tapping', 'Tapping'),
        ('mcq', 'Multiple Choice'),
        ('typing', 'Typing'),
        ('listening', 'Listening'),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    word = models.ForeignKey(Word, on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='new')
    box_index = models.SmallIntegerField(default=0)
    strength = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    next_due_at = models.DateTimeField(null=True, blank=True)
    times_correct = models.IntegerField(default=0)
    times_incorrect = models.IntegerField(default=0)
    streak = models.SmallIntegerField(default=0)
    ease = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal('2.5'))
    last_activity_type = models.CharField(max_length=15, choices=ACTIVITY_CHOICES, null=True, blank=True)
    suggested_next_activity = models.CharField(max_length=15, choices=ACTIVITY_CHOICES, null=True, blank=True)
    is_difficult = models.BooleanField(default=False)

    class Meta:
        unique_together = ('student', 'word')
        indexes = [
            models.Index(fields=['student', 'next_due_at']),
            models.Index(fields=['student', 'is_difficult', 'next_due_at']),
        ]


class ActivityAttempt(models.Model):
    ACTIVITY_CHOICES = StudentWordProgress.ACTIVITY_CHOICES

    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    word = models.ForeignKey(Word, on_delete=models.CASCADE)
    activity_type = models.CharField(max_length=15, choices=ACTIVITY_CHOICES)
    is_correct = models.BooleanField()
    time_taken_ms = models.IntegerField(null=True, blank=True)
    hints_used = models.SmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
