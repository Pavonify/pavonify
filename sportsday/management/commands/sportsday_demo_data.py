from __future__ import annotations

from django.core.management.base import BaseCommand

from sportsday import services


class Command(BaseCommand):
    help = "Seed demo data for Harrow Sports Day"

    def add_arguments(self, parser):
        parser.add_argument("--no-output", action="store_true", help="Suppress success output")

    def handle(self, *args, **options):
        meet = services.seed_default_meet()
        if not options["no_output"]:
            self.stdout.write(self.style.SUCCESS(f"Seeded meet: {meet.name} ({meet.slug})"))
