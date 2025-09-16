from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from learning.models import VocabularyList, VocabularyWord


class EnrichmentAPITests(TestCase):
    def setUp(self) -> None:
        User = get_user_model()
        self.teacher = User.objects.create_user(
            username="teacher",
            email="teacher@example.com",
            password="password123",
            is_teacher=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.teacher)

    def test_preview_returns_enrichment_payload(self) -> None:
        vocab_list = VocabularyList.objects.create(
            name="Test List",
            source_language="en",
            target_language="de",
            teacher=self.teacher,
        )
        payload = [
            {
                "word": "apple",
                "translation": "Apfel",
                "images": [
                    {
                        "url": "https://example.com/apple.jpg",
                        "thumb": "https://example.com/apple-thumb.jpg",
                        "source": "Wikimedia",
                        "attribution": "Test",
                        "license": "CC",
                    }
                ],
                "fact": {"text": "Apples are pomaceous fruits.", "type": "trivia", "confidence": 0.9},
            }
        ]
        with mock.patch("learning.api.enrichment.get_enrichments", return_value=payload) as mocked:
            resp = self.client.post(
                "/api/vocab/enrichment/preview",
                {
                    "list_id": vocab_list.id,
                    "entries": [
                        {"word": "apple", "translation": "Apfel"},
                    ],
                },
                format="json",
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data, payload)
        mocked.assert_called_once()
        args, kwargs = mocked.call_args
        self.assertEqual(args[0], [{"word": "apple", "translation": "Apfel"}])
        self.assertEqual(
            kwargs,
            {"source_language": "en", "target_language": "de"},
        )

    def test_confirm_updates_vocabulary_word(self) -> None:
        vocab_list = VocabularyList.objects.create(
            name="Test List",
            source_language="en",
            target_language="es",
            teacher=self.teacher,
        )
        word = VocabularyWord.objects.create(
            list=vocab_list,
            word="apple",
            translation="manzana",
        )

        resp = self.client.post(
            "/api/vocab/enrichment/confirm",
            {
                "list_id": vocab_list.id,
                "items": [
                    {
                        "word": "apple",
                        "image": {
                            "url": "https://example.com/apple.jpg",
                            "thumb": "https://example.com/apple-thumb.jpg",
                            "source": "Wikimedia",
                            "attribution": "Photographer",
                            "license": "CC-BY",
                        },
                        "fact": {
                            "text": "Apple comes from Old English 'æppel'.",
                            "type": "etymology",
                            "confidence": 0.85,
                        },
                        "approveImage": True,
                        "approveFact": True,
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"created": 0, "updated": 1})

        word.refresh_from_db()
        self.assertTrue(word.image_approved)
        self.assertEqual(word.image_url, "https://example.com/apple.jpg")
        self.assertEqual(word.image_thumb_url, "https://example.com/apple-thumb.jpg")
        self.assertEqual(word.image_source, "Wikimedia")
        self.assertEqual(word.image_attribution, "Photographer")
        self.assertEqual(word.image_license, "CC-BY")
        self.assertTrue(word.word_fact_approved)
        self.assertEqual(word.word_fact_text, "Apple comes from Old English 'æppel'.")
        self.assertEqual(word.word_fact_type, "etymology")
        self.assertAlmostEqual(word.word_fact_confidence, 0.85)
