from datetime import date, timedelta
from django.test import TestCase
from django.utils import timezone

from .models import (
    User,
    School,
    Class,
    Student,
    VocabularyList,
    VocabularyWord,
    Progress,
)
from .srs import schedule_review, get_due_words


class SRSTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Test School")
        self.teacher = User.objects.create_user(
            username="teacher",
            password="pass",
            is_teacher=True,
            first_name="Teach",
            last_name="Er",
            email="t@example.com",
            country="US",
        )
        self.student_user = User.objects.create_user(
            username="student",
            password="pass",
            is_student=True,
            first_name="Stu",
            last_name="Dent",
            email="s@example.com",
            country="US",
        )
        self.classroom = Class.objects.create(
            school=self.school, name="Class A", language="Spanish"
        )
        self.vocab_list = VocabularyList.objects.create(
            name="Basics",
            source_language="en",
            target_language="es",
            teacher=self.teacher,
        )
        self.classroom.vocabulary_lists.add(self.vocab_list)
        self.student = Student.objects.create(
            school=self.school,
            first_name="Stu",
            last_name="Dent",
            year_group=1,
            date_of_birth=date(2010, 1, 1),
            username="student",
            password="pass",
        )
        self.student.classes.add(self.classroom)
        self.word1 = VocabularyWord.objects.create(
            word="hello", translation="hola", list=self.vocab_list
        )
        self.progress1 = Progress.objects.create(
            student=self.student_user, word=self.word1
        )

    def test_schedule_review_updates_progress(self):
        schedule_review(self.progress1, True)
        self.progress1.refresh_from_db()
        self.assertIsNotNone(self.progress1.last_seen)
        self.assertEqual(self.progress1.review_count, 1)
        self.assertEqual(self.progress1.interval, 2)
        self.assertAlmostEqual(
            self.progress1.next_due.date(),
            (timezone.now() + timedelta(days=2)).date(),
        )

        schedule_review(self.progress1, False)
        self.progress1.refresh_from_db()
        self.assertEqual(self.progress1.review_count, 2)
        self.assertEqual(self.progress1.interval, 1)

    def test_get_due_words(self):
        # word1 overdue
        self.progress1.next_due = timezone.now() - timedelta(days=1)
        self.progress1.save()
        # word2 future
        word2 = VocabularyWord.objects.create(
            word="bye", translation="adios", list=self.vocab_list
        )
        Progress.objects.create(
            student=self.student_user,
            word=word2,
            next_due=timezone.now() + timedelta(days=1),
        )
        # word3 no progress
        word3 = VocabularyWord.objects.create(
            word="thanks", translation="gracias", list=self.vocab_list
        )

        due_words = get_due_words(self.student, limit=5)
        self.assertIn(self.word1, due_words)
        self.assertIn(word3, due_words)
        self.assertNotIn(word2, due_words)

        limited = get_due_words(self.student, limit=1)
        self.assertEqual(len(limited), 1)
        self.assertEqual(limited[0], self.word1)

    def test_memory_score(self):
        # fresh progress should be cold when not seen
        self.assertEqual(self.progress1.memory_score(), "cold")

        # simulate recent review within interval -> hot
        Progress.objects.filter(pk=self.progress1.pk).update(
            last_seen=timezone.now() - timedelta(days=1), interval=2, review_count=1
        )
        self.progress1.refresh_from_db()
        self.assertEqual(self.progress1.memory_score(), "hot")

        # simulate overdue review -> cold
        Progress.objects.filter(pk=self.progress1.pk).update(
            last_seen=timezone.now() - timedelta(days=3), review_count=1
        )
        self.progress1.refresh_from_db()
        self.assertEqual(self.progress1.memory_score(), "cold")
