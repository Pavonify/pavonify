from __future__ import annotations

from unittest import mock

from django.test import SimpleTestCase

from learning.services import wikimedia_images


class FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception("HTTP error")


class WikimediaImageSearchTests(SimpleTestCase):
    @mock.patch("learning.services.wikimedia_images.SESSION.get")
    def test_primary_query_returns_images(self, mock_get: mock.Mock) -> None:
        mock_get.return_value = FakeResponse(
            {
                "query": {
                    "pages": {
                        "1": {
                            "imageinfo": [
                                {
                                    "url": "https://example.com/dog.jpg",
                                    "thumburl": "https://example.com/dog-thumb.jpg",
                                    "extmetadata": {
                                        "LicenseShortName": {"value": "CC-BY"},
                                        "Artist": {"value": "Photographer"},
                                    },
                                }
                            ]
                        }
                    }
                }
            }
        )

        results = wikimedia_images.search_images("dog", limit=2)
        self.assertEqual(
            results,
            [
                {
                    "url": "https://example.com/dog.jpg",
                    "thumb": "https://example.com/dog-thumb.jpg",
                    "source": "Wikimedia",
                    "attribution": "Photographer",
                    "attribution_text": "Photographer",
                    "license": "CC-BY",
                }
            ],
        )
        mock_get.assert_called_once()

    @mock.patch("learning.services.wikimedia_images.SESSION.get")
    def test_fallback_query_uses_search_titles(self, mock_get: mock.Mock) -> None:
        mock_get.side_effect = [
            FakeResponse({"query": {"pages": {}}}),
            FakeResponse({"query": {"search": [{"title": "File:Dog.jpg"}]}}),
            FakeResponse(
                {
                    "query": {
                        "pages": {
                            "2": {
                                "imageinfo": [
                                    {
                                        "url": "https://example.com/dog-2.jpg",
                                        "extmetadata": {
                                            "Credit": {"value": "Wikimedia"},
                                            "LicenseShortName": {"value": "CC0"},
                                        },
                                    }
                                ]
                            }
                        }
                    }
                }
            ),
        ]

        results = wikimedia_images.search_images("dog", limit=1)
        self.assertEqual(
            results,
            [
                {
                    "url": "https://example.com/dog-2.jpg",
                    "thumb": "https://example.com/dog-2.jpg",
                    "source": "Wikimedia",
                    "attribution": "Wikimedia",
                    "attribution_text": "Wikimedia",
                    "license": "CC0",
                }
            ],
        )
        self.assertEqual(mock_get.call_count, 3)

    @mock.patch("learning.services.wikimedia_images.SESSION.get")
    def test_exclude_urls_filters_previous_results(self, mock_get: mock.Mock) -> None:
        mock_get.return_value = FakeResponse(
            {
                "query": {
                    "pages": {
                        "1": {
                            "imageinfo": [
                                {
                                    "url": "https://example.com/dog-old.jpg",
                                    "thumburl": "https://example.com/dog-old-thumb.jpg",
                                    "extmetadata": {"Artist": {"value": "Old"}},
                                }
                            ]
                        },
                        "2": {
                            "imageinfo": [
                                {
                                    "url": "https://example.com/dog-new.jpg",
                                    "thumburl": "https://example.com/dog-new-thumb.jpg",
                                    "extmetadata": {"Artist": {"value": "New"}},
                                }
                            ]
                        },
                    }
                }
            }
        )

        results = wikimedia_images.search_images(
            "dog",
            limit=2,
            exclude_urls=["https://example.com/dog-old.jpg"],
        )

        self.assertEqual(
            results,
            [
                {
                    "url": "https://example.com/dog-new.jpg",
                    "thumb": "https://example.com/dog-new-thumb.jpg",
                    "source": "Wikimedia",
                    "attribution": "New",
                    "attribution_text": "New",
                    "license": "",
                }
            ],
        )
        self.assertEqual(mock_get.call_count, 1)

    @mock.patch("learning.services.wikimedia_images.SESSION.get", side_effect=Exception("boom"))
    def test_request_error_returns_empty_list(self, mock_get: mock.Mock) -> None:  # noqa: ARG002
        self.assertEqual(wikimedia_images.search_images("cat"), [])
