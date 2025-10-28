"""Tests for the live practice API."""

from __future__ import annotations

import random

from django.test import Client, TestCase
from django.urls import reverse
from learning.models import Class, School, Student, User, VocabularyList, VocabularyWord

from .models import LiveGameParticipant, LiveGameSession
from .views import LiveGameSessionViewSet
from learning.services.question_flow import QuestionFlowEngine


class LiveGameSessionAPITest(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Test High", location="Test")
        self.teacher = User.objects.create_user(
            username="teacher",
            password="password",
            is_teacher=True,
            first_name="T",
            last_name="One",
            school=self.school,
        )
        self.client.force_login(self.teacher)

        self.school_class = Class.objects.create(
            school=self.school,
            name="Level 1",
            language="Spanish",
        )
        self.school_class.teachers.add(self.teacher)

        self.vocab_list = VocabularyList.objects.create(
            name="Basics",
            source_language="en",
            target_language="es",
            teacher=self.teacher,
        )
        self.vocab_list.classes.add(self.school_class)
        VocabularyWord.objects.create(list=self.vocab_list, word="hola", translation="hello")
        VocabularyWord.objects.create(list=self.vocab_list, word="adios", translation="goodbye")

        LiveGameSessionViewSet.question_engine = QuestionFlowEngine(rng=random.Random(42))
        LiveGameSessionViewSet._broadcast_class_announcement = lambda *args, **kwargs: None
        LiveGameSessionViewSet._broadcast_to_game = lambda *args, **kwargs: None

    def test_session_lifecycle(self):
        response = self.client.post(
            "/api/live-games/",
            {
                "class_id": str(self.school_class.id),
                "vocab_list_ids": [self.vocab_list.id],
                "total_questions": 1,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        session_id = response.json()["id"]

        start_response = self.client.post(f"/api/live-games/{session_id}/start/")
        self.assertEqual(start_response.status_code, 200)

        next_response = self.client.post(f"/api/live-games/{session_id}/next/")
        self.assertEqual(next_response.status_code, 200)

        session = LiveGameSession.objects.get(id=session_id)
        question = session.questions.get(index=1)

        student = Student.objects.create(
            school=self.school,
            first_name="Sally",
            last_name="Student",
            year_group=5,
            date_of_birth="2012-01-01",
            username="sally",
            password="pass",
        )
        student.classes.add(self.school_class)

        student_client = Client()
        session_store = student_client.session
        session_store["student_id"] = str(student.id)
        session_store.save()

        join_response = student_client.post(f"/api/live-games/{session_id}/join/")
        self.assertEqual(join_response.status_code, 200)

        answer_response = student_client.post(
            f"/api/live-games/{session_id}/answer/",
            {
                "questionIndex": 1,
                "answerPayload": question.payload.get("answer"),
            },
            content_type="application/json",
        )
        self.assertEqual(answer_response.status_code, 200)

        participant = LiveGameParticipant.objects.get(session=session)
        self.assertGreater(participant.score, 0)

    def test_teacher_console_page_renders(self):
        response = self.client.get(reverse("live_teacher_console"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Live Practice Competition")
        self.assertContains(response, self.school_class.name)

    def test_teacher_console_requires_teacher(self):
        self.client.logout()
        non_teacher = User.objects.create_user(username="nonteacher", password="pass")
        self.client.force_login(non_teacher)
        response = self.client.get(reverse("live_teacher_console"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("teacher_dashboard"), response["Location"])
