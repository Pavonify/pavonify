"""Shared question generation and scoring utilities."""

from __future__ import annotations

import random
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from django.db.models import QuerySet

from learning.models import VocabularyList, VocabularyWord


QUESTION_TYPES = (
    "show_word",
    "flashcard",
    "typing",
    "fill_gaps",
    "multiple_choice",
    "true_false",
)


@dataclass
class NormalizedAnswer:
    is_correct: bool
    canonical_answer: Optional[str]


class QuestionFlowEngine:
    """Provides helpers for generating and validating question payloads."""

    def __init__(self, *, rng: Optional[random.Random] = None) -> None:
        self.rng = rng or random.Random()

    def build_question_payloads(
        self,
        vocab_lists: Sequence[VocabularyList],
        count: int,
    ) -> List[Dict[str, Any]]:
        """Generate a list of question payloads."""

        if not vocab_lists:
            return []

        words_qs: QuerySet[VocabularyWord] = VocabularyWord.objects.filter(
            list__in=vocab_lists
        ).select_related("list")
        words: List[VocabularyWord] = list(words_qs)

        if not words:
            return []

        payloads: List[Dict[str, Any]] = []
        for _ in range(count):
            word = self.rng.choice(words)
            activity = self.rng.choice(QUESTION_TYPES)
            payload = self.build_activity_payload(word, activity)
            payloads.append(payload)
        return payloads

    def build_activity_payload(
        self, word: VocabularyWord, activity: str
    ) -> Dict[str, Any]:
        if activity not in QUESTION_TYPES:
            activity = "typing"

        image_data = self._image_payload(word)

        if activity == "show_word":
            payload = {
                "type": "show_word",
                "word_id": word.id,
                "prompt": word.translation,
                "answer": word.word,
            }
        elif activity == "flashcard":
            payload = {
                "type": "flashcard",
                "word_id": word.id,
                "prompt": word.word,
                "answer": word.translation,
            }
        elif activity == "typing":
            if self.rng.choice([True, False]):
                prompt, answer = word.word, word.translation
                answer_language = "target"
            else:
                prompt, answer = word.translation, word.word
                answer_language = "source"
            payload = {
                "type": "typing",
                "word_id": word.id,
                "prompt": prompt,
                "answer": answer,
                "answer_language": answer_language,
            }
        elif activity == "fill_gaps":
            if self.rng.choice([True, False]):
                source, target = word.translation, word.word
                answer_language = "source"
            else:
                source, target = word.word, word.translation
                answer_language = "target"
            masked = list(target)
            indices = list(range(len(masked)))
            self.rng.shuffle(indices)
            for i in indices[: len(masked) // 2 or 1]:
                if masked[i].isalpha():
                    masked[i] = "_"
            payload = {
                "type": "fill_gaps",
                "word_id": word.id,
                "prompt": "".join(masked),
                "translation": source,
                "answer": target,
                "answer_language": answer_language,
            }
        elif activity == "multiple_choice":
            if self.rng.choice([True, False]):
                prompt = word.word
                answer = word.translation
                distractors = list(
                    VocabularyWord.objects.filter(list=word.list)
                    .exclude(id=word.id)
                    .values_list("translation", flat=True)
                )
            else:
                prompt = word.translation
                answer = word.word
                distractors = list(
                    VocabularyWord.objects.filter(list=word.list)
                    .exclude(id=word.id)
                    .values_list("word", flat=True)
                )
            self.rng.shuffle(distractors)
            options = distractors[:3] + [answer]
            self.rng.shuffle(options)
            payload = {
                "type": "multiple_choice",
                "word_id": word.id,
                "prompt": prompt,
                "options": options,
                "answer": answer,
            }
        else:  # true_false
            if self.rng.choice([True, False]):
                prompt, correct_answer = word.word, word.translation
                pool = VocabularyWord.objects.filter(list=word.list).exclude(id=word.id)
                values = list(pool.values_list("translation", flat=True))
            else:
                prompt, correct_answer = word.translation, word.word
                pool = VocabularyWord.objects.filter(list=word.list).exclude(id=word.id)
                values = list(pool.values_list("word", flat=True))
            shown = correct_answer
            if values and self.rng.choice([True, False]):
                shown = self.rng.choice(values)
            payload = {
                "type": "true_false",
                "word_id": word.id,
                "prompt": prompt,
                "shown_translation": shown,
                "answer": shown == correct_answer,
            }

        if image_data:
            payload["image"] = image_data
        return payload

    @staticmethod
    def _image_payload(word: VocabularyWord) -> Optional[Dict[str, str]]:
        if not word.image_url or not word.image_approved:
            return None
        return {
            "url": word.image_url,
            "thumb": word.image_thumb_url or word.image_url,
            "source": word.image_source or "",
            "attribution": word.image_attribution or "",
            "license": word.image_license or "",
            "alt": word.word,
        }

    @staticmethod
    def normalize_and_score(payload: Dict[str, Any], answer_payload: Any) -> NormalizedAnswer:
        """Normalize client answer for comparison."""

        qtype = payload.get("type")
        expected = payload.get("answer")

        if qtype == "true_false":
            expected_bool = bool(expected)
            actual = bool(answer_payload)
            return NormalizedAnswer(is_correct=actual == expected_bool, canonical_answer=str(expected_bool))

        if isinstance(expected, str):
            expected_normalized = _normalize_text(expected)
            actual_normalized = _normalize_text(str(answer_payload or ""))
            return NormalizedAnswer(
                is_correct=actual_normalized == expected_normalized,
                canonical_answer=expected,
            )

        if qtype == "multiple_choice":
            expected_str = str(expected)
            actual_str = str(answer_payload or "")
            return NormalizedAnswer(is_correct=expected_str == actual_str, canonical_answer=expected_str)

        return NormalizedAnswer(is_correct=False, canonical_answer=str(expected) if expected is not None else None)


def _normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKD", value).casefold().strip()
