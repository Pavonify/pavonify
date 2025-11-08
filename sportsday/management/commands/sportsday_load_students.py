from __future__ import annotations

import pathlib

from django.core.management.base import BaseCommand, CommandError

from sportsday import models, services


class Command(BaseCommand):
    help = "Load students for a meet from a CSV file"

    def add_arguments(self, parser):
        parser.add_argument("--meet", required=True, help="Slug of the meet")
        parser.add_argument("--csv", required=True, help="Path to the CSV file")

    def handle(self, *args, **options):
        meet_slug = options["meet"]
        csv_path = pathlib.Path(options["csv"])
        meet = models.Meet.objects.filter(slug=meet_slug).first()
        if not meet:
            raise CommandError(f"Meet with slug '{meet_slug}' not found")
        if not csv_path.exists():
            raise CommandError(f"CSV file '{csv_path}' does not exist")
        with csv_path.open("r", encoding="utf-8") as handle:
            services.load_students_from_csv(meet, handle)
        self.stdout.write(self.style.SUCCESS("Students imported successfully."))
