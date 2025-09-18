from collections import defaultdict
import math
import random
import statistics

from django.db.models import Case, Count, F, Q, Sum, When
from django.db.models.functions import Coalesce

from .models import (
    Assignment,
    AssignmentAttempt,
    AssignmentProgress,
    VocabularyWord,
)


# ---------- Core Aggregations ----------

def _student_accuracy_map(assignment_id):
    """Return mapping of student_id -> overall accuracy for the assignment."""
    student_stats = (
        AssignmentAttempt.objects
        .filter(assignment_id=assignment_id)
        .values("student_id")
        .annotate(
            total_attempts=Count("id"),
            total_correct=Coalesce(Sum(Case(When(is_correct=True, then=1), default=0)), 0),
        )
    )
    scores = {}
    for row in student_stats:
        attempts = row["total_attempts"] or 0
        correct = row["total_correct"] or 0
        scores[row["student_id"]] = (correct / attempts) if attempts else 0.0
    return scores


def _point_biserial_for_words(assignment_id, student_scores):
    """Compute point-biserial discrimination per word based on student scores."""
    # Prepare accumulator for each word keyed by vocabulary_word_id
    per_word = defaultdict(lambda: {
        "correct_score_sum": 0.0,
        "correct_count": 0,
        "incorrect_score_sum": 0.0,
        "incorrect_count": 0,
    })

    # Aggregate attempts per student per word to determine success grouping
    per_word_student = (
        AssignmentAttempt.objects
        .filter(assignment_id=assignment_id)
        .values("vocabulary_word_id", "student_id")
        .annotate(
            attempts=Count("id"),
            correct=Coalesce(Sum(Case(When(is_correct=True, then=1), default=0)), 0),
        )
    )

    for row in per_word_student:
        student_id = row["student_id"]
        word_id = row["vocabulary_word_id"]
        attempts = row["attempts"] or 0
        correct = row["correct"] or 0
        if attempts == 0:
            continue
        score = student_scores.get(student_id, 0.0)
        accuracy = correct / attempts
        bucket = per_word[word_id]
        if accuracy >= 0.5:
            bucket["correct_score_sum"] += score
            bucket["correct_count"] += 1
        else:
            bucket["incorrect_score_sum"] += score
            bucket["incorrect_count"] += 1

    score_values = list(student_scores.values())
    if len(score_values) > 1:
        sd_total = statistics.pstdev(score_values)
    else:
        sd_total = 0.0

    results = {}
    for word_id, bucket in per_word.items():
        correct_count = bucket["correct_count"]
        incorrect_count = bucket["incorrect_count"]
        total_students = correct_count + incorrect_count
        if not total_students or sd_total == 0:
            results[word_id] = 0.0
            continue
        p = correct_count / total_students
        q = 1 - p
        if p == 0 or q == 0:
            results[word_id] = 0.0
            continue
        mean_correct = bucket["correct_score_sum"] / correct_count if correct_count else 0.0
        mean_incorrect = bucket["incorrect_score_sum"] / incorrect_count if incorrect_count else 0.0
        discrimination = ((mean_correct - mean_incorrect) / sd_total) * math.sqrt(p * q)
        results[word_id] = float(discrimination)
    return results


def word_stats(assignment_id):
    """
    Returns list of dicts:
    [{
      'vocabulary_word': <id>,
      'word': 'Bibliothek',
      'attempts': 12,
      'correct': 7,
      'students_total': 9,
      'students_struggling': 5,
      'facility': 0.58,
      'difficulty': 0.42,
      'discrimination': 0.19
    }, ...] (sorted hardest first)
    """
    qs = (
        AssignmentAttempt.objects
        .filter(assignment_id=assignment_id)
        .values("vocabulary_word", "vocabulary_word__word")
        .annotate(
            attempts=Count("id"),
            correct=Coalesce(Sum(Case(When(is_correct=True, then=1), default=0)), 0),
            students_total=Count("student", distinct=True),
            students_struggling=Count("student", filter=Q(is_correct=False), distinct=True),
        )
        .annotate(
            facility=(F("correct") * 1.0) / F("attempts"),
            difficulty=1.0 - (F("correct") * 1.0) / F("attempts"),
        )
        .order_by("-difficulty", "-attempts")
    )

    student_scores = _student_accuracy_map(assignment_id)
    discrimination_map = _point_biserial_for_words(assignment_id, student_scores)

    results = []
    for row in qs:
        word_id = row["vocabulary_word"]
        results.append({
            "vocabulary_word": word_id,
            "word": row["vocabulary_word__word"],
            "attempts": row["attempts"],
            "correct": row["correct"],
            "students_total": row["students_total"],
            "students_struggling": row["students_struggling"],
            "facility": float(row["facility"]),
            "difficulty": float(row["difficulty"]),
            "discrimination": float(discrimination_map.get(word_id, 0.0)),
        })
    return results


def mode_breakdown(assignment_id):
    """
    Returns list of dicts per mode:
    [{'mode':'flashcards','attempts':20,'correct':13,'facility':0.65}, ...]
    """
    qs = (
        AssignmentAttempt.objects
        .filter(assignment_id=assignment_id)
        .values("mode")
        .annotate(
            attempts=Count("id"),
            correct=Coalesce(Sum(Case(When(is_correct=True, then=1), default=0)), 0),
        )
        .annotate(
            facility=(F("correct") * 1.0) / F("attempts")
        )
        .order_by("mode")
    )
    return [
        {
            "mode": row["mode"],
            "attempts": row["attempts"],
            "correct": row["correct"],
            "facility": float(row["facility"]),
        }
        for row in qs
    ]


def student_mastery(assignment_id):
    """
    Returns per student lists of 'words_aced' and 'needs_practice'.
    Aced: >=3 attempts and >=80% correct
    Needs practice: >=2 attempts and <=50% correct
    """
    base = (
        AssignmentAttempt.objects
        .filter(assignment_id=assignment_id)
        .values("student_id", "student__first_name", "student__last_name", "vocabulary_word__word")
        .annotate(
            attempts=Count("id"),
            correct=Coalesce(Sum(Case(When(is_correct=True, then=1), default=0)), 0),
        )
    )

    by_student = {}
    for row in base:
        sid = row["student_id"]
        name = f"{row['student__first_name']} {row['student__last_name']}".strip()
        student_bucket = by_student.setdefault(sid, {
            "student_id": sid,
            "name": name,
            "words_aced": [],
            "needs_practice": [],
        })
        attempts = row["attempts"] or 0
        acc = (row["correct"] * 1.0) / attempts if attempts else 0.0
        word = row["vocabulary_word__word"]
        if attempts >= 3 and acc >= 0.8:
            student_bucket["words_aced"].append(word)
        if attempts >= 2 and acc <= 0.5:
            student_bucket["needs_practice"].append(word)

    return list(by_student.values())


def heatmap_data(assignment_id):
    """
    Returns JSON-serialisable mapping for heatmap grid.
    {
        'students': {sid: 'Name', ...},
        'words': {wid: 'word', ...},
        'cells': [
            {'student': sid, 'word': wid, 'attempts': 3, 'correct': 1, 'accuracy': 0.33},
            ...
        ]
    }
    """
    grid = (
        AssignmentAttempt.objects
        .filter(assignment_id=assignment_id)
        .values(
            "student_id",
            "student__first_name",
            "student__last_name",
            "vocabulary_word_id",
            "vocabulary_word__word",
        )
        .annotate(
            attempts=Count("id"),
            correct=Coalesce(Sum(Case(When(is_correct=True, then=1), default=0)), 0),
        )
    )

    students, words, cells = {}, {}, []
    for row in grid:
        sid = str(row["student_id"])
        wid = str(row["vocabulary_word_id"])
        attempts = row["attempts"] or 0
        correct = row["correct"] or 0
        students[sid] = f"{row['student__first_name']} {row['student__last_name']}".strip()
        words[wid] = row["vocabulary_word__word"]
        accuracy = (correct * 1.0) / attempts if attempts else 0.0
        cells.append({
            "student": sid,
            "word": wid,
            "attempts": attempts,
            "correct": correct,
            "accuracy": round(accuracy, 2),
        })
    return {"students": students, "words": words, "cells": cells}


def assignment_overview(assignment_id):
    """
    Returns list of dicts: username, points_earned, completed, time_spent
    """
    qs = (
        AssignmentProgress.objects
        .filter(assignment_id=assignment_id)
        .select_related("student")
        .values("student__username", "points_earned", "completed", "time_spent")
        .order_by("-points_earned")
    )
    output = []
    for row in qs:
        output.append({
            "username": row["student__username"],
            "points_earned": row["points_earned"],
            "completed": row["completed"],
            "time_spent": str(row["time_spent"]) if row["time_spent"] is not None else "0:00:00",
        })
    return output


# ---------- Activity Generators (no schema changes) ----------

def _get_vocab_dict(assignment_id):
    assignment = Assignment.objects.select_related("vocab_list").get(id=assignment_id)
    vocab = VocabularyWord.objects.filter(list=assignment.vocab_list).values("word", "translation")
    return assignment, {entry["word"]: entry["translation"] for entry in vocab}


def build_do_now(assignment_id, hard_limit=6):
    stats = word_stats(assignment_id)
    hardest = [row["word"] for row in stats[:hard_limit]]
    assignment, vocab_dict = _get_vocab_dict(assignment_id)
    pool = list(vocab_dict.keys())

    questions = []
    for word in hardest:
        distractors_pool = [candidate for candidate in pool if candidate != word]
        if distractors_pool:
            distractors = random.sample(distractors_pool, k=min(3, len(distractors_pool)))
        else:
            distractors = []
        options = [word] + distractors
        random.shuffle(options)
        questions.append({
            "stem": f"Choose the correct {assignment.vocab_list.source_language} word for: “{vocab_dict.get(word, word)}”.",
            "options": options,
            "answer": word,
        })
    return {"title": "Do-Now: Tricky Words (3–5 mins)", "questions": questions}


def build_exit_tickets(assignment_id):
    mastery = student_mastery(assignment_id)
    tickets = []
    for entry in mastery:
        weak = entry["needs_practice"][:2]
        confident = entry["words_aced"][:1]
        items = []
        if weak:
            items.append({"type": "short", "prompt": f"Translate and type: {weak[0]}."})
        if len(weak) > 1:
            items.append({"type": "short", "prompt": f"Translate and type: {weak[1]}."})
        if confident:
            items.append({"type": "confidence", "prompt": f"Quick win: use “{confident[0]}” in a short sentence."})
        if not items:
            items.append({"type": "short", "prompt": "Write any 2 words you learned and translate them."})
        tickets.append({"student": entry["name"], "items": items})
    return {"title": "Exit Tickets (Personalised)", "tickets": tickets}


def pick_hinge_question(assignment_id):
    stats = word_stats(assignment_id)
    if not stats:
        return {"title": "Hinge Question", "question": "No data yet."}
    top = max(stats, key=lambda row: (row["difficulty"], row["attempts"]))
    return {
        "title": "Hinge Question",
        "question": f"Everyone: type the translation for “{top['word']}”.",
        "note": f"Chosen due to high difficulty ({round(top['difficulty'] * 100)}%) with {top['attempts']} attempts.",
    }


def build_sentence_builders(assignment_id, per_word=4, total_words=8):
    stats = word_stats(assignment_id)
    words = [row["word"] for row in stats[:total_words]] if stats else []
    frames = [
        "Write a sentence using “{w}” in the past tense.",
        "Write a question using “{w}”.",
        "Use “{w}” with an adjective.",
        "Connect “{w}” with because/aber/et/pero.",
    ]
    prompts = []
    for word in words:
        for frame in frames[:per_word]:
            prompts.append({"prompt": frame.format(w=word)})
    return {"title": "Sentence Builders", "prompts": prompts}


def build_game_seed(assignment_id, limit=10):
    stats = word_stats(assignment_id)
    words = [row["word"] for row in stats[:limit]]
    return {
        "title": "Mini-Game Seed",
        "game": "conveyor_sorter",
        "words": words,
    }


def as_plaintext(payload):
    lines = [payload.get("title", "Activity"), ""]
    if "questions" in payload:
        for index, question in enumerate(payload["questions"], 1):
            lines.append(f"{index}) {question['stem']}")
            for opt_idx, option in enumerate(question.get("options", []), 1):
                lines.append(f"   {opt_idx}. {option}")
    if "prompts" in payload:
        for index, prompt in enumerate(payload["prompts"], 1):
            lines.append(f"{index}) {prompt['prompt']}")
    if "tickets" in payload:
        for ticket in payload["tickets"]:
            lines.append(f"- {ticket['student']}")
            for item in ticket["items"]:
                lines.append(f"   • {item['prompt']}")
    if "question" in payload:
        lines.append(payload["question"])
    return "\n".join(lines)
