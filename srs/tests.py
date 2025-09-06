from django.test import TestCase
from django.utils import timezone
from learning.models import Student, School, Word
from .models import StudentWordProgress
from .scheduler import update_progress, INTERVALS, compute_strength


class SchedulerTests(TestCase):
    def setUp(self):
        school = School.objects.create(name="Test School")
        self.student = Student.objects.create(
            school=school,
            first_name="A",
            last_name="B",
            year_group=1,
            date_of_birth=timezone.now().date(),
            username="s1",
            password="pw",
        )
        self.word = Word.objects.create(source="a", target="b")
        self.progress = StudentWordProgress.objects.create(
            student=self.student,
            word=self.word,
            status="new",
            next_due_at=timezone.now(),
        )

    def test_correct_answer_advances_box(self):
        update_progress(self.progress, True)
        self.progress.refresh_from_db()
        self.assertEqual(self.progress.box_index, 1)
        self.assertEqual(self.progress.streak, 1)

    def test_wrong_answer_resets_box(self):
        self.progress.box_index = 3
        self.progress.save()
        update_progress(self.progress, False)
        self.progress.refresh_from_db()
        self.assertEqual(self.progress.box_index, 0)
        self.assertTrue(self.progress.is_difficult)

    def test_strength_overdue(self):
        self.progress.box_index = 7
        self.progress.next_due_at = timezone.now() - timezone.timedelta(days=5)
        self.progress.save()
        strength = compute_strength(self.progress)
        self.assertLess(strength, 100)

    def test_attempt_endpoint(self):
        from django.test import Client
        client = Client()
        response = client.post(
            "/api/srs/attempt/",
            data={
                "word_id": self.word.id,
                "activity_type": "typing",
                "is_correct": True,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
