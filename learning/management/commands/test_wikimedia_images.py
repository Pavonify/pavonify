from django.core.management.base import BaseCommand
from learning.services.wikimedia_images import search_images


class Command(BaseCommand):
    help = "Fetch candidate images for a given word from Wikimedia Commons"

    def add_arguments(self, parser):
        parser.add_argument(
            "word",
            type=str,
            help="The word you want to search for (e.g. 'Dog')",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=3,
            help="Number of images to fetch (default 3)",
        )

    def handle(self, *args, **options):
        word = options["word"]
        limit = options["limit"]
        self.stdout.write(self.style.NOTICE(f"Searching Wikimedia images for: {word}"))
        images = search_images(word, limit=limit)
        if not images:
            self.stdout.write(self.style.WARNING("❌ No images returned"))
        else:
            self.stdout.write(self.style.SUCCESS(f"✅ Found {len(images)} image(s):"))
            for i, img in enumerate(images, start=1):
                self.stdout.write(f"{i}. {img['url']}")
                self.stdout.write(f"   thumb: {img['thumb']}")
                self.stdout.write(f"   attribution: {img['attribution']}")
                self.stdout.write(f"   license: {img['license']}")
