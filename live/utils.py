"""Utility helpers for the live practice app."""

from __future__ import annotations

import random
import string

from django.conf import settings

from .models import LiveGameSession


def generate_unique_pin() -> str:
    """Return a numeric pin that is unique for existing sessions."""
    length = getattr(settings, "GAME_PIN_LENGTH", 6)
    while True:
        pin = "".join(random.choices(string.digits, k=length))
        if not LiveGameSession.objects.filter(pin=pin).exists():
            return pin
