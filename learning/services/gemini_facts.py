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

_PROMPT_TEMPLATE = """You are a concise linguistics assistant.

TASK: Generate EXACTLY ONE short, interesting “word fact” for the target word.

CONSTRAINTS:
- Length <= 220 characters.
- Choose ONE category: etymology | idiom | trivia (lowercase).
- Output MUST be valid JSON (no preamble, no code fences):
  {"text":"...", "type":"etymology"}

TARGET WORD: "{word}"

If you cannot find a reliable fact, reply with:
{"text":"", "type":"trivia"}
"""

def _extract_json(payload: str) -> Dict[str, Any]:
    """
    Best-effort JSON extractor:
    - If the model returns extra prose or code fences, pull out the JSON object.
    """
    payload = payload.strip()
    # Fast path
    try:
        return json.loads(payload)
    except Exception:
        pass

    match = re.search(r"\{(?:[^{}]|(?R))*\}", payload, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in model output.")
    return json.loads(match.group(0))

def _coerce_result(obj: Dict[str, Any]) -> FactResult:
    text = (obj.get("text") or "").strip()
    ftype = (obj.get("type") or "").strip().lower()

    if not text:
        return {"text": "", "type": "trivia", "confidence": 0.0}
    if ftype not in _VALID_TYPES:
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
        model = genai.GenerativeModel(model_name)
        prompt = _PROMPT_TEMPLATE.format(word=word)

        resp = model.generate_content(prompt)
        # Handle different SDK shapes (text or parts)
        if hasattr(resp, "text") and resp.text:
            raw = resp.text
        else:
            # Fallback: concatenate parts if needed
            raw = ""
            try:
                for cand in getattr(resp, "candidates", []) or []:
                    for part in getattr(cand, "content", {}).get("parts", []) or []:
                        raw += str(getattr(part, "text", part))
            except Exception:
                pass

        data = _extract_json(raw)
        result = _coerce_result(data)
        return result
    except Exception as e:
        logger.exception("Gemini fact generation failed for '%s': %s", word, e)
        return {"text": "", "type": "trivia", "confidence": 0.0}
