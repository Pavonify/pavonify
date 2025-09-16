from django.core.management.base import BaseCommand
from learning.services.gemini_facts import get_fact


class Command(BaseCommand):
    help = "Generate a test fact for a given word using Gemini"

    def add_arguments(self, parser):
        parser.add_argument(
            "word",
            type=str,
            help="The word you want a Gemini fact for (e.g. 'Dog')",
        )

    def handle(self, *args, **options):
        word = options["word"]
        self.stdout.write(self.style.NOTICE(f"Requesting Gemini fact for: {word}"))
        fact = get_fact(word)
        if not fact["text"]:
            self.stdout.write(self.style.WARNING("❌ No fact returned"))
        else:
            self.stdout.write(self.style.SUCCESS("✅ Fact generated:"))
            self.stdout.write(f"  text: {fact['text']}")
            self.stdout.write(f"  type: {fact['type']}")
            self.stdout.write(f"  confidence: {fact['confidence']}")
