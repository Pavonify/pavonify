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
        parser.add_argument(
            "--translation",
            type=str,
            default="",
            help="Optional translation of the word in the teacher's source language.",
        )
        parser.add_argument(
            "--source-lang",
            type=str,
            default="",
            help="Source language code (e.g. en).",
        )
        parser.add_argument(
            "--target-lang",
            type=str,
            default="",
            help="Target language code (e.g. de).",
        )
        parser.add_argument(
            "--fact-type",
            type=str,
            default="",
            choices=["", "etymology", "idiom", "trivia"],
            help="Optional fact type to request.",
        )

    def handle(self, *args, **options):
        word = options["word"]
        translation = options.get("translation") or ""
        source_lang = options.get("source_lang") or ""
        target_lang = options.get("target_lang") or ""
        fact_type = options.get("fact_type") or ""

        self.stdout.write(self.style.NOTICE(f"Requesting Gemini fact for: {word}"))
        fact = get_fact(
            word,
            translation=translation,
            source_language=source_lang or None,
            target_language=target_lang or None,
            preferred_type=fact_type or None,
        )
        if not fact["text"]:
            self.stdout.write(self.style.WARNING("❌ No fact returned"))
        else:
            self.stdout.write(self.style.SUCCESS("✅ Fact generated:"))
            self.stdout.write(f"  text: {fact['text']}")
            self.stdout.write(f"  type: {fact['type']}")
            self.stdout.write(f"  confidence: {fact['confidence']}")
