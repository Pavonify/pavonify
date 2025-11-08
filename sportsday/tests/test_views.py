from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from sportsday import models


class AccessViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="teacher", password="pass", is_staff=True)
        self.meet = models.Meet.objects.create(name="Meet", slug="meet", date="2026-05-01")
        config = models.SportsdayAccessConfig.get_solo()
        config.set_code("harrow123")
        config.save()

    def test_access_denied_without_cookie(self):
        client = Client()
        client.login(username="teacher", password="pass")
        response = client.get(reverse("sportsday:meet_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("sportsday:access"), response.url)

    def test_access_granted_with_code(self):
        client = Client()
        client.login(username="teacher", password="pass")
        response = client.post(reverse("sportsday:access"), {"code": "harrow123"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("sportsday:meet_list"))
        # Subsequent request should succeed
        response = client.get(reverse("sportsday:meet_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Available Meets")
