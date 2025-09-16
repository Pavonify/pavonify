from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional, TypedDict

from django.conf import settings

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
_PROMPT_TEMPLATE = """You are a concise linguistics assistant.

TASK: Generate EXACTLY ONE short, interesting “word fact” for the target word.

CONSTRAINTS:
- Length <= 220 characters.
- Choose ONE category: etymology | idiom | trivia (lowercase).
- Prefer idioms or etymology when reliable; use trivia only if no idiom or origin insight exists.
- Output MUST be valid JSON (no preamble, no code fences):
  {{"text":"...", "type":"etymology"}}

TARGET WORD: "{word}"

If you cannot find a reliable fact, reply with:
{{"text":"", "type":"trivia"}}
"""

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

def get_fact(word: str, *, model_id: Optional[str] = None) -> FactResult:
    """
    Generate a single short fact for a word using Gemini.
    Returns: {"text": str, "type": "etymology"|"idiom"|"trivia", "confidence": float}
    """
    if not word or not isinstance(word, str):
        return {"text": "", "type": "trivia", "confidence": 0.0}

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

        prompt = _PROMPT_TEMPLATE.format(word=word)
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
        return _coerce_result(data)

    except Exception as e:
        logger.exception("Gemini fact generation failed for '%s': %s", word, e)
        return {"text": "", "type": "trivia", "confidence": 0.0}
