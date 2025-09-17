from __future__ import annotations

from unittest import mock

from django.test import SimpleTestCase

from learning.services import enrichment


class EnrichmentServiceTests(SimpleTestCase):
    @mock.patch("learning.services.enrichment.search_images", return_value=[])
    def test_enrich_one_returns_placeholder_fact_when_generation_disabled(
        self,
        mock_search_images: mock.Mock,
    ) -> None:
        result = enrichment.enrich_one(
            {"word": "plane", "translation": "avion"},
            source_language="en",
            target_language="fr",
        )

        self.assertEqual(result["word"], "plane")
        self.assertEqual(result["translation"], "avion")
        self.assertEqual(result["fact"]["type"], "trivia")
        self.assertEqual(result["fact"]["text"], "")
        self.assertEqual(result["fact"]["confidence"], 0.0)

        mock_search_images.assert_called_once()
        args, kwargs = mock_search_images.call_args
        self.assertEqual(args[0], "plane")
        self.assertEqual(kwargs.get("exclude_urls"), [])
