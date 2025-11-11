from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from sportsday import models, services


class Command(BaseCommand):
    """Create multiple events for a meet using command-line arguments."""

    help = "Generate meet events for combinations of sport, grade, and gender."

    def add_arguments(self, parser):
        parser.add_argument("--meet-slug", required=True, help="Slug of the meet to target")
        parser.add_argument("--sports", required=True, help="Comma-separated sport type keys (e.g. 100m,long-jump)")
        parser.add_argument(
            "--grades",
            required=True,
            help="Comma separated grade labels or ranges (e.g. G6,G7 or G6-G8)",
        )
        parser.add_argument(
            "--genders",
            default="M,F",
            help="Comma separated gender codes (M,F,X). Defaults to M,F",
        )
        parser.add_argument("--capacity", type=int, help="Capacity override for generated events")
        parser.add_argument("--attempts", type=int, help="Attempts override for generated events")
        parser.add_argument("--rounds", type=int, default=1, help="Rounds per event")
        parser.add_argument(
            "--pattern",
            default="{grade} {gender_label} {sport}",
            help="Naming pattern supporting {grade}, {gender}, {gender_label}, {sport}",
        )

    def handle(self, *args, **options):
        slug = options["meet_slug"]
        meet = models.Meet.objects.filter(slug=slug).first()
        if not meet:
            raise CommandError(f"No meet found with slug '{slug}'.")

        sport_keys = [key.strip() for key in options["sports"].split(",") if key.strip()]
        sports = list(models.SportType.objects.filter(key__in=sport_keys))
        missing = sorted(set(sport_keys) - {sport.key for sport in sports})
        if missing:
            raise CommandError(f"Unknown sport type keys: {', '.join(missing)}")

        grades = self._expand_grades(options["grades"])
        if not grades:
            raise CommandError("No valid grades supplied.")

        genders = [code.strip().upper() for code in options["genders"].split(",") if code.strip()]
        if not genders:
            raise CommandError("Provide at least one gender code (M,F,X).")

        summary = services.generate_events(
            meet=meet,
            sport_types=sports,
            grades=grades,
            genders=genders,
            name_pattern=options["pattern"],
            capacity_override=options.get("capacity"),
            attempts_override=options.get("attempts"),
            rounds_total=options.get("rounds") or 1,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Created {summary['created']} events, updated {summary['updated']}, skipped {summary['skipped']}."
            )
        )

    def _expand_grades(self, spec: str) -> list[str]:
        values: list[str] = []
        for chunk in spec.split(","):
            token = chunk.strip()
            if not token:
                continue
            if "-" in token:
                start, end = token.split("-", 1)
                expanded = self._expand_range(start.strip(), end.strip())
                if expanded:
                    values.extend(expanded)
                    continue
            values.append(token)
        return values

    def _expand_range(self, start: str, end: str) -> list[str]:
        start_prefix = "".join(filter(str.isalpha, start))
        end_prefix = "".join(filter(str.isalpha, end))
        start_digits = "".join(filter(str.isdigit, start))
        end_digits = "".join(filter(str.isdigit, end))
        if start_digits.isdigit() and end_digits.isdigit():
            if start_prefix != end_prefix:
                return []
            start_num = int(start_digits)
            end_num = int(end_digits)
            if end_num < start_num:
                start_num, end_num = end_num, start_num
            prefix = start_prefix
            return [f"{prefix}{number}" if prefix else str(number) for number in range(start_num, end_num + 1)]
        return []
