from datetime import date, timedelta
import json
from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse
from django.db import connection
from django.test.utils import CaptureQueriesContext

from .models import (
    User,
    School,
    Class,
    Student,
    VocabularyList,
    VocabularyWord,
    Progress,
    Assignment,
    AssignmentAttempt,
    AssignmentProgress,
    Trophy,
    StudentTrophy,
)
from .srs import schedule_review, get_due_words as legacy_get_due_words
from .spaced_repetition import get_due_words as practice_get_due_words
from .memory import memory_meter
from achievements.models import Trophy as AchievementTrophy, TrophyUnlock


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

        due_words = legacy_get_due_words(self.student, limit=5)
        self.assertIn(self.word1, due_words)
        self.assertIn(word3, due_words)
        self.assertNotIn(word2, due_words)

        limited = legacy_get_due_words(self.student, limit=1)
        self.assertEqual(len(limited), 1)
        self.assertEqual(limited[0], self.word1)

    def test_practice_due_words_prioritize_new_and_weak(self):
        now = timezone.now()
        Progress.objects.filter(pk=self.progress1.pk).update(
            next_due=now - timedelta(days=1),
            review_count=3,
            correct_attempts=3,
            incorrect_attempts=2,
            interval=1,
        )
        self.progress1.refresh_from_db()

        strong_word = VocabularyWord.objects.create(
            word="strong", translation="fuerte", list=self.vocab_list
        )
        Progress.objects.create(
            student=self.student_user,
            word=strong_word,
            correct_attempts=6,
            incorrect_attempts=0,
            review_count=6,
            interval=6,
            last_seen=now - timedelta(days=1),
            next_due=now + timedelta(days=6),
        )

        weak_word = VocabularyWord.objects.create(
            word="weak", translation="debil", list=self.vocab_list
        )
        Progress.objects.create(
            student=self.student_user,
            word=weak_word,
            correct_attempts=1,
            incorrect_attempts=4,
            review_count=4,
            interval=3,
            last_seen=now - timedelta(days=5),
            next_due=now + timedelta(days=3),
        )

        new_word = VocabularyWord.objects.create(
            word="fresh", translation="fresco", list=self.vocab_list
        )

        due_words = practice_get_due_words(self.student, self.vocab_list, limit=3)

        self.assertIn(self.word1, due_words)
        self.assertIn(new_word, due_words)
        self.assertIn(weak_word, due_words)
        self.assertNotIn(strong_word, due_words)

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

    def test_memory_meter_rewards_consistent_practice(self):
        now = timezone.now()
        Progress.objects.filter(pk=self.progress1.pk).update(
            correct_attempts=8,
            incorrect_attempts=3,
            review_count=11,
            interval=4,
            last_seen=now - timedelta(days=1),
            next_due=now + timedelta(days=3),
        )
        self.progress1.refresh_from_db()

        word_quick = VocabularyWord.objects.create(
            word="quick", translation="rapido", list=self.vocab_list
        )
        quick_progress = Progress.objects.create(
            student=self.student_user,
            word=word_quick,
            correct_attempts=2,
            incorrect_attempts=0,
            review_count=2,
            interval=2,
            last_seen=now - timedelta(hours=12),
            next_due=now + timedelta(days=2),
        )

        seasoned_percent, _ = memory_meter(self.progress1, now=now)
        quick_percent, _ = memory_meter(quick_progress, now=now)

        self.assertGreater(seasoned_percent, quick_percent)


class ProgressDashboardViewTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Test School")
        self.student = Student.objects.create(
            school=self.school,
            first_name="Test",
            last_name="Student",
            year_group=1,
            date_of_birth=date(2010, 1, 1),
            username="student1",
            password="pass",
        )

    def test_requires_login(self):
        response = self.client.get(reverse("progress_dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_progress_dashboard_context(self):
        session = self.client.session
        session["student_id"] = str(self.student.id)
        session.save()

        response = self.client.get(reverse("progress_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_points"], self.student.total_points)
        self.assertEqual(response.context["trophy_count"], 0)


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class StudentTrophyViewTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Trophy School")
        self.student = Student.objects.create(
            school=self.school,
            first_name="Tina",
            last_name="Trophy",
            year_group=5,
            date_of_birth=date(2011, 5, 5),
            username="tina",
            password="pass",
        )
        self.user = User.objects.create_user(
            username=self.student.username,
            password="pass",
            is_student=True,
            first_name=self.student.first_name,
            last_name=self.student.last_name,
            email="tina@example.com",
            country="US",
        )

        self.trophies = []
        for index in range(6):
            trophy = AchievementTrophy.objects.create(
                id=f"trophy-{index}",
                name=f"Trophy {index}",
                category="Progress",
                trigger_type="event",
                metric="practice_sessions",
                comparator="gte",
                threshold=1,
                window="none",
                subject_scope="any",
                repeatable=False,
                cooldown="none",
                points=10,
                icon="trophy",
                rarity="common",
                description=f"Earn trophy {index}",
                constraints={},
            )
            unlock = TrophyUnlock.objects.create(user=self.user, trophy=trophy)
            TrophyUnlock.objects.filter(pk=unlock.pk).update(
                earned_at=timezone.now() + timedelta(minutes=index)
            )
            self.trophies.append(trophy)

        session = self.client.session
        session["student_id"] = str(self.student.id)
        session.save()

    def test_dashboard_recent_trophies_shows_latest_five(self):
        response = self.client.get(reverse("student_dashboard"))
        self.assertEqual(response.status_code, 200)
        recent = response.context["recent_trophies"]
        self.assertEqual(len(recent), 5)
        self.assertEqual(recent[0]["name"], "Trophy 5")
        self.assertEqual(recent[-1]["name"], "Trophy 1")
        self.assertEqual(response.context["unlocked_trophy_count"], 6)

        popup_payload = json.loads(response.context["new_trophies_json"])
        self.assertEqual(len(popup_payload), 6)
        self.assertTrue(any(item["name"] == "Trophy 0" for item in popup_payload))

    def test_student_trophies_page_lists_all_definitions(self):
        response = self.client.get(reverse("student_trophies"))
        self.assertEqual(response.status_code, 200)
        trophy_rows = response.context["trophies"]
        self.assertEqual(len(trophy_rows), 6)
        self.assertEqual(response.context["total_count"], 6)
        self.assertTrue(all(row["unlocked"] for row in trophy_rows))
        self.assertTrue(all(row["progress"]["percentage"] == 100.0 for row in trophy_rows))


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class StudentTrophyFallbackTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Legacy School")
        self.student = Student.objects.create(
            school=self.school,
            first_name="Legacy",
            last_name="Learner",
            year_group=4,
            date_of_birth=date(2012, 2, 2),
            username="legacy",
            password="pass",
        )
        self.user = User.objects.create_user(
            username=self.student.username,
            password="pass",
            is_student=True,
            first_name=self.student.first_name,
            last_name=self.student.last_name,
            email="legacy@example.com",
            country="US",
        )
        trophy = Trophy.objects.create(name="Legacy Trophy", description="Legacy reward")
        StudentTrophy.objects.create(student=self.student, trophy=trophy)

        session = self.client.session
        session["student_id"] = str(self.student.id)
        session.save()

    def test_trophy_page_falls_back_to_legacy_data(self):
        response = self.client.get(reverse("student_trophies"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["achievements_available"])
        self.assertEqual(response.context["total_count"], 1)
        row = response.context["trophies"][0]
        self.assertEqual(row["name"], "Legacy Trophy")
        self.assertTrue(row["unlocked"])

class AssignmentAnalyticsQueryTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Test School")
        self.teacher = User.objects.create_user(
            username="teacher2",
            password="pass",
            is_teacher=True,
            email="teacher2@example.com",
        )
        self.classroom = Class.objects.create(
            school=self.school, name="Class A", language="Spanish"
        )
        self.classroom.teachers.add(self.teacher)

        self.student1 = Student.objects.create(
            school=self.school,
            first_name="Stu1",
            last_name="Dent",
            year_group=1,
            date_of_birth=date(2010, 1, 1),
            username="s1",
            password="pass",
        )
        self.student2 = Student.objects.create(
            school=self.school,
            first_name="Stu2",
            last_name="Dent",
            year_group=1,
            date_of_birth=date(2010, 1, 1),
            username="s2",
            password="pass",
        )
        self.student1.classes.add(self.classroom)
        self.student2.classes.add(self.classroom)

        self.vocab_list = VocabularyList.objects.create(
            name="Basics",
            source_language="en",
            target_language="es",
            teacher=self.teacher,
        )
        self.classroom.vocabulary_lists.add(self.vocab_list)
        self.word = VocabularyWord.objects.create(
            word="hello", translation="hola", list=self.vocab_list
        )
        self.assignment = Assignment.objects.create(
            name="Assignment",
            class_assigned=self.classroom,
            vocab_list=self.vocab_list,
            deadline=timezone.now(),
            target_points=10,
            teacher=self.teacher,
        )
        AssignmentProgress.objects.create(
            student=self.student1, assignment=self.assignment
        )
        AssignmentProgress.objects.create(
            student=self.student2, assignment=self.assignment
        )

    def test_assignment_analytics_query_efficiency(self):
        self.client.force_login(self.teacher)
        url = reverse("assignment_analytics", args=[self.assignment.id])

        AssignmentAttempt.objects.create(
            student=self.student1,
            assignment=self.assignment,
            vocabulary_word=self.word,
            mode="flashcards",
            is_correct=True,
        )
        with CaptureQueriesContext(connection) as ctx1:
            self.client.get(url)

        AssignmentAttempt.objects.create(
            student=self.student2,
            assignment=self.assignment,
            vocabulary_word=self.word,
            mode="flashcards",
            is_correct=False,
        )
        with CaptureQueriesContext(connection) as ctx2:
            self.client.get(url)

        self.assertEqual(len(ctx2), len(ctx1))
