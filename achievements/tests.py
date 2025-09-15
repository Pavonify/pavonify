from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from achievements.models import Trophy


class TrophySeedTests(TestCase):
    def test_seed_trophies(self) -> None:
        call_command("seed_trophies")
        self.assertEqual(Trophy.objects.count(), 100)


class TrophyAPITests(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user(username="u", password="p")
        call_command("seed_trophies")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_list_trophies(self) -> None:
        resp = self.client.get("/api/achievements/trophies/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 100)

    def test_list_unlocks(self) -> None:
        resp = self.client.get("/api/achievements/unlocks/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])
