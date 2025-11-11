from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from sportsday import models, views


class Command(BaseCommand):
    """Assign meet entries from a CSV file."""

    help = "Populate entries for a meet from a CSV containing student and event identifiers."

    def add_arguments(self, parser):
        parser.add_argument("--meet-slug", required=True, help="Slug of the meet to update")
        parser.add_argument("--path", required=True, help="Path to the CSV file")

    def handle(self, *args, **options):
        slug = options["meet_slug"]
        meet = models.Meet.objects.filter(slug=slug).first()
        if not meet:
            raise CommandError(f"No meet found with slug '{slug}'.")

        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"CSV file not found at {path}.")

        with path.open("rb") as handle:
            result = views._bulk_assign_entries_from_csv(meet, handle)

        created = result.get("created", 0)
        updated = result.get("updated", 0)
        errors = result.get("errors", [])

        self.stdout.write(self.style.SUCCESS(f"Created {created} entries; updated {updated}."))
        if errors:
            for error in errors:
                self.stderr.write(f"ERROR: {error}")
            raise CommandError(f"Completed with {len(errors)} errors.")
