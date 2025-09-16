from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional, TypedDict

from django.conf import settings
from django.utils.translation import get_language_info

try:
    import google.generativeai as genai
except Exception:  # pragma: no cover
    genai = None

logger = logging.getLogger(__name__)

class FactResult(TypedDict):
    text: str
    type: str
    confidence: float

_VALID_TYPES = {"etymology", "idiom", "trivia"}

# NOTE: double the JSON braces so .format() only substitutes {word}
def _language_label(code: Optional[str]) -> str:
    if not code:
        return ""
    try:
        info = get_language_info(code)
    except Exception:
        info = None
    if not info:
        return code or ""
    return info.get("name_local") or info.get("name") or (code or "")


def _build_prompt(
    word: str,
    translation: Optional[str],
    source_language: Optional[str],
    target_language: Optional[str],
    preferred_type: Optional[str],
) -> str:
    source_label = _language_label(source_language) or (source_language or "the source language")
    target_label = _language_label(target_language) or (target_language or "the target language")
    source_hint = (
        f"- Source language term provided by the teacher: \"{translation}\"."
        if translation
        else "- No explicit translation provided; infer a natural bridge to the source language."
    )
    bridge_hint = f' such as the source word "{translation}"' if translation else ""

    if preferred_type == "idiom":
        type_instruction = (
            "- Provide a well-known idiom, proverb, or fixed expression from the source language that clearly relates to the target word.\n"
            "- If no suitable idiom exists, respond with {\"text\":\"No idiom available.\",\"type\":\"idiom\"}."
        )
        category_desc = '"idiom"'
        fallback_type = "idiom"
        example_type = "idiom"
        fallback_response = '{"text":"No idiom available.","type":"idiom"}'
    elif preferred_type in _VALID_TYPES:
        type_instruction = (
            f"- Focus on a {preferred_type} insight. The JSON \"type\" must be \"{preferred_type}\"."
        )
        category_desc = f'"{preferred_type}"'
        fallback_type = preferred_type
        example_type = preferred_type
        fallback_response = f'{{"text":"","type":"{preferred_type}"}}'
    else:
        type_instruction = (
            "- Choose the strongest category (etymology preferred, otherwise idiom, else trivia) and set the JSON \"type\" accordingly."
        )
        category_desc = 'one of "etymology", "idiom", or "trivia"'
        fallback_type = "trivia"
        example_type = "etymology"
        fallback_response = '{"text":"","type":"trivia"}'

    prompt = (
        "You are a concise linguistics assistant.\n\n"
        "TASK: Generate EXACTLY ONE short, memorable word fact that helps a language teacher connect the student's source language to the new vocabulary word.\n\n"
        "CONTEXT:\n"
        f"- Target language: {target_label}.\n"
        f"- Target word (student is learning): \"{word}\".\n"
        f"{source_hint}\n"
        f"- Source language for explanation: {source_label}.\n\n"
        f"{type_instruction}\n"
        "REQUIREMENTS:\n"
        "- Keep the fact <= 220 characters.\n"
        f"- Make the fact memorable and explicitly link \"{word}\" to the source language{bridge_hint}.\n"
        "- Use clear, teacher-friendly language.\n"
        f"- Output MUST be valid JSON with keys \"text\" and \"type\" (no prose or markdown). Example: {{\"text\":\"...\",\"type\":\"{example_type}\"}}. The \"type\" value must be {category_desc}.\n"
        f"If you cannot find a reliable fact, respond with {fallback_response}."
    )
    return prompt

def _extract_json(payload: str) -> Dict[str, Any]:
    """
    Best-effort JSON extractor that tolerates prose and code fences.
    1) Try direct loads.
    2) Strip markdown fences.
    3) Scan for the first balanced {...} block.
    """
    s = (payload or "").strip()

    # 1) Fast path
    try:
        return json.loads(s)
    except Exception:
        pass

    # 2) Strip common code fences if present
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*\s*|\s*```$", "", s, flags=re.DOTALL).strip()
        try:
            return json.loads(s)
        except Exception:
            pass

    # 3) Find first balanced JSON object
    start = s.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(s)):
            ch = s[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = s[start:i+1]
                    try:
                        return json.loads(candidate)
                    except Exception:
                        break
        start = s.find("{", start + 1)

    raise ValueError("No valid JSON object found in model output.")

def _coerce_result(obj: Dict[str, Any]) -> FactResult:
    text = (obj.get("text") or "").strip()
    ftype = (obj.get("type") or "").strip().lower()

    if not text:
        return {"text": "", "type": "trivia", "confidence": 0.0}
    if len(text) > 220:
        text = text[:220].rstrip()

    if ftype not in _VALID_TYPES:
        lowered = text.lower()
        if any(k in lowered for k in ("idiom", "phrase", "expression")):
            ftype = "idiom"
        elif any(k in lowered for k in ("origin", "from ", "latin", "greek", "old ", "proto-")):
            ftype = "etymology"
        else:
            ftype = "trivia"

    conf = 0.9 if len(text) <= 220 else 0.6
    return {"text": text, "type": ftype, "confidence": conf}


def get_fact(
    word: str,
    *,
    translation: Optional[str] = None,
    source_language: Optional[str] = None,
    target_language: Optional[str] = None,
    preferred_type: Optional[str] = None,
    model_id: Optional[str] = None,
) -> FactResult:
    """
    Generate a short fact for a word using Gemini.
    Returns: {"text": str, "type": "etymology"|"idiom"|"trivia", "confidence": float}
    """
    if not word or not isinstance(word, str):
        return {"text": "", "type": "trivia", "confidence": 0.0}

    translation_value = (translation or "").strip()
    preferred = (preferred_type or "").strip().lower()
    if preferred not in _VALID_TYPES:
        preferred = None

    if genai is None:
        logger.warning("google-generativeai package not installed.")
        return {"text": "", "type": "trivia", "confidence": 0.0}

    api_key = getattr(settings, "GEMINI_API_KEY", None)
    if not api_key:
        logger.warning("Gemini API key missing in settings.")
        return {"text": "", "type": "trivia", "confidence": 0.0}

    try:
        genai.configure(api_key=api_key)
        model_name = model_id or getattr(settings, "GEMINI_MODEL_ID", "gemini-1.5-flash")
        model = genai.GenerativeModel(
            model_name,
            generation_config={"temperature": 0.6, "max_output_tokens": 120},
            safety_settings={
                "HARASSMENT": "BLOCK_NONE",
                "HATE_SPEECH": "BLOCK_NONE",
                "SEXUAL": "BLOCK_NONE",
                "DANGEROUS": "BLOCK_NONE",
            },
        )

        prompt = _build_prompt(
            word,
            translation_value,
            source_language,
            target_language,
            preferred,
        )
        resp = model.generate_content(prompt)

        raw = getattr(resp, "text", "") or ""
        if not raw and getattr(resp, "candidates", None):
            for cand in resp.candidates or []:
                parts = getattr(getattr(cand, "content", None), "parts", None) or []
                for p in parts:
                    raw += str(getattr(p, "text", "") or "")

        if not raw:
            logger.warning("Gemini returned empty text for '%s'", word)
            return {"text": "", "type": "trivia", "confidence": 0.0}

        data = _extract_json(raw)
        result = _coerce_result(data)
        if preferred:
            result["type"] = preferred
        return result

    except Exception as e:
        logger.exception("Gemini fact generation failed for '%s': %s", word, e)
        return {"text": "", "type": "trivia", "confidence": 0.0}
