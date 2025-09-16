from __future__ import annotations

from unittest import mock

from django.test import SimpleTestCase

from learning.services import enrichment


class EnrichmentServiceTests(SimpleTestCase):
    @mock.patch("learning.services.enrichment.search_images", return_value=[])
    @mock.patch(
        "learning.services.enrichment.get_fact",
        return_value={"text": "", "type": "trivia", "confidence": 0.4},
    )
    def test_enrich_one_uses_fallback_fact_when_empty(
        self,
        mock_get_fact: mock.Mock,
        mock_search_images: mock.Mock,
    ) -> None:
        result = enrichment.enrich_one(
            {"word": "avion", "translation": "plane"},
            source_language="en",
            target_language="fr",
        )

        self.assertEqual(result["word"], "avion")
        self.assertEqual(result["translation"], "plane")
        self.assertIn("avion", result["fact"]["text"])
        self.assertIn("plane", result["fact"]["text"])
        self.assertEqual(result["fact"]["type"], "trivia")
        self.assertGreaterEqual(result["fact"]["confidence"], 0)

        mock_get_fact.assert_called_once()
        called_kwargs = mock_get_fact.call_args.kwargs
        self.assertEqual(called_kwargs.get("word"), "avion")
        self.assertEqual(called_kwargs.get("translation"), "plane")

        mock_search_images.assert_called_once()
        args, kwargs = mock_search_images.call_args
        self.assertEqual(args[0], "plane")
        self.assertEqual(kwargs.get("exclude_urls"), [])
