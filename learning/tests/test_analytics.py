import os
from datetime import date, timedelta

import django
from django.test import TestCase
from django.utils import timezone

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lang_platform.settings")
django.setup()

from learning.analytics import mode_breakdown, student_mastery, word_stats
from learning.models import (
    Assignment,
    AssignmentAttempt,
    Class as Classroom,
    School,
    Student,
    User,
    VocabularyList,
    VocabularyWord,
)


class AnalyticsBaseTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name="Test School")
        cls.teacher = User.objects.create_user(
            username="teacher",
            password="password123",
            email="teacher@example.com",
            first_name="Teach",
            last_name="Er",
            is_teacher=True,
            school=cls.school,
        )
        cls.classroom = Classroom.objects.create(
            school=cls.school,
            name="Class A",
            language="Spanish",
        )
        cls.classroom.teachers.add(cls.teacher)
        cls.vocab_list = VocabularyList.objects.create(
            name="Core Words",
            source_language="English",
            target_language="Spanish",
            teacher=cls.teacher,
        )
        cls.assignment = Assignment.objects.create(
            name="Assignment 1",
            class_assigned=cls.classroom,
            vocab_list=cls.vocab_list,
            deadline=timezone.now() + timedelta(days=1),
            target_points=10,
            teacher=cls.teacher,
        )
        cls.word1 = VocabularyWord.objects.create(list=cls.vocab_list, word="hola", translation="hello")
        cls.word2 = VocabularyWord.objects.create(list=cls.vocab_list, word="adiós", translation="goodbye")
        cls.student1 = Student.objects.create(
            school=cls.school,
            first_name="Alex",
            last_name="One",
            year_group=8,
            date_of_birth=date(2010, 1, 1),
            username="alex1",
            password="pass",
        )
        cls.student1.classes.add(cls.classroom)
        cls.student2 = Student.objects.create(
            school=cls.school,
            first_name="Bailey",
            last_name="Two",
            year_group=8,
            date_of_birth=date(2010, 2, 2),
            username="bailey2",
            password="pass",
        )
        cls.student2.classes.add(cls.classroom)


class AnalyticsEmptyTests(AnalyticsBaseTestCase):
    def test_word_stats_empty(self):
        self.assertEqual(word_stats(self.assignment.id), [])

    def test_mode_breakdown_empty(self):
        self.assertEqual(mode_breakdown(self.assignment.id), [])


class AnalyticsWithAttemptsTests(AnalyticsBaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for _ in range(3):
            AssignmentAttempt.objects.create(
                student=cls.student1,
                assignment=cls.assignment,
                vocabulary_word=cls.word1,
                mode="flashcards",
                is_correct=True,
            )
        for _ in range(2):
            AssignmentAttempt.objects.create(
                student=cls.student2,
                assignment=cls.assignment,
                vocabulary_word=cls.word2,
                mode="matchup",
                is_correct=False,
            )
        AssignmentAttempt.objects.create(
            student=cls.student1,
            assignment=cls.assignment,
            vocabulary_word=cls.word2,
            mode="flashcards",
            is_correct=False,
        )

    def test_student_mastery_shapes(self):
        result = student_mastery(self.assignment.id)
        self.assertIsInstance(result, list)
        if result:
            first = result[0]
            self.assertTrue({"student_id", "name", "words_aced", "needs_practice"}.issubset(first.keys()))
