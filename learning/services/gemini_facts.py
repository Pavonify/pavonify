from __future__ import annotations

import json
import logging
import re
import hashlib
import time
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, Optional, TypedDict, List, Tuple

from django.conf import settings
from django.utils.translation import get_language_info

try:
    # Django cache (preferred if configured)
    from django.core.cache import cache as django_cache  # type: ignore
except Exception:  # pragma: no cover
    django_cache = None

try:
    import google.generativeai as genai
except Exception:  # pragma: no cover
    genai = None

logger = logging.getLogger(__name__)


# ----------------------------- Public Types -----------------------------

class FactResult(TypedDict):
    text: str
    type: str
    confidence: float


# ----------------------------- Constants -------------------------------

_VALID_TYPES = {"etymology", "idiom", "trivia"}
_CACHE_TTL_SECONDS = getattr(settings, "GEMINI_FACTS_CACHE_TTL_SECONDS", 24 * 3600)

# Higher-bandwidth default model
_DEFAULT_MODEL = getattr(
    settings, "GEMINI_MODEL_ID", "gemini-2.5-flash-lite"
)

# Sensible free-tier defaults. Tune in settings when billing is enabled.
_DEFAULT_RPM = getattr(settings, "GEMINI_RPM", 12)  # 15 is free cap; stay a little under
_DEFAULT_RPD = getattr(settings, "GEMINI_RPD", 900)  # 1000 is free cap; stay a little under
_MAX_RETRIES = getattr(settings, "GEMINI_MAX_RETRIES", 4)
_BASE_BACKOFF = getattr(settings, "GEMINI_BASE_BACKOFF_SECONDS", 2.0)  # exponential backoff base

# ----------------------------- Utilities -------------------------------

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


def _hash_key(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()  # noqa: S324 (not for security)


def _cache_get(cache_key: str) -> Optional[Dict[str, Any]]:
    # Prefer Django cache if available
    if django_cache is not None:
        try:
            return django_cache.get(cache_key)
        except Exception:
            pass
    # Fallback to in-memory TTL cache
    return _MemoryTTLCache.get(cache_key)


def _cache_set(cache_key: str, value: Dict[str, Any], ttl: int = _CACHE_TTL_SECONDS) -> None:
    if django_cache is not None:
        try:
            django_cache.set(cache_key, value, ttl)
            return
        except Exception:
            pass
    _MemoryTTLCache.set(cache_key, value, ttl)


# Simple in-process TTL cache (fallback)
class _MemoryTTLCache:
    _store: Dict[str, Tuple[float, Dict[str, Any]]] = {}
    _lock = threading.Lock()

    @classmethod
    def get(cls, key: str) -> Optional[Dict[str, Any]]:
        now = time.time()
        with cls._lock:
            item = cls._store.get(key)
            if not item:
                return None
            expires_at, val = item
            if now >= expires_at:
                cls._store.pop(key, None)
                return None
            return val

    @classmethod
    def set(cls, key: str, value: Dict[str, Any], ttl: int) -> None:
        with cls._lock:
            cls._store[key] = (time.time() + ttl, value)


# Token-bucket rate limiter for RPM and RPD combined
@dataclass
class _TokenBucket:
    capacity: int
    refill_per_sec: float
    tokens: float
    last: float

    def take(self, amount: float = 1.0) -> None:
        # Block until a token is available
        while True:
            now = time.time()
            # refill
            delta = max(0.0, now - self.last)
            self.tokens = min(self.capacity, self.tokens + delta * self.refill_per_sec)
            self.last = now
            if self.tokens >= amount:
                self.tokens -= amount
                return
            # sleep a bit until tokens refill
            time.sleep(0.05)


class _CompositeLimiter:
    """
    Enforces both RPM and RPD. Uses two token buckets:
      - per-minute bucket
      - per-day bucket
    The day bucket is coarse but prevents accidental hard 429s.
    """
    def __init__(self, rpm: int, rpd: int):
        now = time.time()
        self._minute = _TokenBucket(capacity=rpm, refill_per_sec=rpm / 60.0, tokens=rpm, last=now)
        self._day = _TokenBucket(capacity=rpd, refill_per_sec=rpd / (24 * 3600.0), tokens=rpd, last=now)

    def acquire(self) -> None:
        # Acquire day token first, then minute token.
        self._day.take(1.0)
        self._minute.take(1.0)


# Single shared limiter per process
_LIMITER = _CompositeLimiter(_DEFAULT_RPM, _DEFAULT_RPD)


# ----------------------------- Prompting -------------------------------

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
        f'- Source language term provided by the teacher: "{translation}".'
        if translation
        else "- No explicit translation provided; infer a natural bridge to the source language."
    )
    bridge_hint = f' such as the source word "{translation}"' if translation else ""

    if preferred_type == "idiom":
        type_instruction = (
            "- Provide a well-known idiom, proverb, or fixed expression from the source language that clearly relates to the target word.\n"
            '- If no suitable idiom exists, respond with {"text":"No idiom available.","type":"idiom"}.'
        )
        category_desc = '"idiom"'
        example_type = "idiom"
        fallback_response = '{"text":"No idiom available.","type":"idiom"}'
    elif preferred_type in _VALID_TYPES:
        type_instruction = (
            f'- Focus on a {preferred_type} insight. The JSON "type" must be "{preferred_type}".'
        )
        category_desc = f'"{preferred_type}"'
        example_type = preferred_type
        fallback_response = f'{{"text":"","type":"{preferred_type}"}}'
    else:
        type_instruction = (
            '- Choose the strongest category (etymology preferred, otherwise idiom, else trivia) and set the JSON "type" accordingly.'
        )
        category_desc = 'one of "etymology", "idiom", or "trivia"'
        example_type = "etymology"
        fallback_response = '{"text":"","type":"trivia"}'

    prompt = (
        "You are a concise linguistics assistant.\n\n"
        "TASK: Generate EXACTLY ONE short, memorable word fact that helps a language teacher connect the student's source language to the new vocabulary word.\n\n"
        "CONTEXT:\n"
        f"- Target language: {target_label}.\n"
        f'- Target word (student is learning): "{word}".\n'
        f"{source_hint}\n"
        f"- Source language for explanation: {source_label}.\n\n"
        f"{type_instruction}\n"
        "REQUIREMENTS:\n"
        "- Keep the fact <= 220 characters.\n"
        f'- Make the fact memorable and explicitly link "{word}" to the source language{bridge_hint}.\n'
        "- Use clear, teacher-friendly language.\n"
        f'- Output MUST be valid JSON with keys "text" and "type" (no prose or markdown). Example: {{"text":"...","type":"{example_type}"}}. The "type" value must be {category_desc}.\n'
        f"If you cannot find a reliable fact, respond with {fallback_response}."
    )
    return prompt


def _extract_json(payload: str) -> Dict[str, Any]:
    s = (payload or "").strip()
    try:
        return json.loads(s)
    except Exception:
        pass

    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*\s*|\s*```$", "", s, flags=re.DOTALL).strip()
        try:
            return json.loads(s)
        except Exception:
            pass

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
                    candidate = s[start : i + 1]
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


# ----------------------------- Core Calls ------------------------------

def _call_gemini(prompt: str, *, model_id: str, temperature: float = 0.6, max_tokens: int = 120) -> str:
    """
    Single Gemini call with:
      - composite rate limiting (RPM + RPD),
      - exponential backoff with server-guided retry_delay,
      - robust extraction of text from candidates.
    """
    if genai is None:
        logger.warning("google-generativeai package not installed.")
        return ""

    api_key = getattr(settings, "GEMINI_API_KEY", None)
    if not api_key:
        logger.warning("Gemini API key missing in settings.")
        return ""

    genai.configure(api_key=api_key)

    model = genai.GenerativeModel(
        model_id,
        generation_config={
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            # Ask for JSON directly (helps reduce fence/prose)
            "response_mime_type": "application/json",
        },
        safety_settings={
            "HARASSMENT": "BLOCK_NONE",
            "HATE_SPEECH": "BLOCK_NONE",
            "SEXUAL": "BLOCK_NONE",
            "DANGEROUS": "BLOCK_NONE",
        },
    )

    # Rate limit BEFORE sending to avoid 429s
    _LIMITER.acquire()

    attempt = 0
    last_err = None
    while attempt <= _MAX_RETRIES:
        try:
            resp = model.generate_content(prompt)
            raw = getattr(resp, "text", "") or ""
            if not raw and getattr(resp, "candidates", None):
                for cand in resp.candidates or []:
                    parts = getattr(getattr(cand, "content", None), "parts", None) or []
                    for p in parts:
                        raw += str(getattr(p, "text", "") or "")
            return raw or ""
        except Exception as e:
            last_err = e
            # Try to respect server-provided retry_delay when present
            delay = _parse_retry_delay_seconds(e)
            if delay is None:
                # exponential backoff with jitter
                delay = _BASE_BACKOFF * (2 ** attempt)
                delay *= (0.85 + 0.3 * _jitter())
            attempt += 1
            if attempt > _MAX_RETRIES:
                logger.exception("Gemini call failed after retries: %s", e)
                break
            logger.warning("Gemini call failed (attempt %d/%d). Sleeping %.2fs. Error: %s",
                           attempt, _MAX_RETRIES, delay, e)
            time.sleep(delay)
    # Give up
    if last_err:
        logger.exception("Gemini final failure: %s", last_err)
    return ""


def _jitter() -> float:
    # simple 0..1 pseudo-jitter without random module (time-based)
    return (time.time() * 1000.0 % 1000) / 1000.0


def _parse_retry_delay_seconds(err: Exception) -> Optional[float]:
    """
    Attempts to extract a retry delay from the Google API error.
    Works with stringified gRPC error that includes 'retry_delay { seconds: N }'.
    """
    s = str(err)
    m = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", s)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None
    return None


# ----------------------------- Public API ------------------------------

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

    model_name = model_id or _DEFAULT_MODEL

    # ------ Cache key
    prompt = _build_prompt(
        word=word,
        translation=translation_value,
        source_language=source_language,
        target_language=target_language,
        preferred_type=preferred,
    )
    cache_key = f"gemini_fact:{model_name}:{_hash_key(prompt)}"
    cached = _cache_get(cache_key)
    if cached:
        return _coerce_result(cached)

    # ------ Call model
    raw = _call_gemini(prompt, model_id=model_name)
    if not raw:
        logger.warning("Gemini returned empty text for '%s'", word)
        return {"text": "", "type": "trivia", "confidence": 0.0}

    try:
        data = _extract_json(raw)
        result = _coerce_result(data)
        if preferred:
            # force type if caller explicitly asked
            result["type"] = preferred
        # cache normalized result
        _cache_set(cache_key, {"text": result["text"], "type": result["type"]}, _CACHE_TTL_SECONDS)
        return result
    except Exception as e:
        logger.exception("Failed to parse JSON for '%s': %s; raw=%r", word, e, raw[:2000])
        return {"text": "", "type": "trivia", "confidence": 0.0}


def get_facts(
    words: List[str],
    *,
    translation: Optional[str] = None,
    source_language: Optional[str] = None,
    target_language: Optional[str] = None,
    preferred_type: Optional[str] = None,
    model_id: Optional[str] = None,
    max_concurrency: Optional[int] = None,
) -> List[FactResult]:
    """
    Batch helper. Safely fans out across a limited number of concurrent workers
    while observing rate limits and caching results. Returns results in the
    same order as `words`.
    """
    if not words:
        return []

    # Keep concurrency comfortably under RPM to avoid bursts
    rpm = _DEFAULT_RPM
    max_workers = max(1, min(int(rpm // 3) or 1, 8))
    if max_concurrency:
        max_workers = max(1, max_concurrency)

    model_name = model_id or _DEFAULT_MODEL
    preferred = (preferred_type or "").strip().lower()
    if preferred not in _VALID_TYPES:
        preferred = None

    # Pre-build prompts + look up cache to avoid duplicate calls
    tasks: List[Tuple[int, str, str]] = []  # (index, cache_key, prompt)
    results: List[Optional[FactResult]] = [None] * len(words)

    for idx, w in enumerate(words):
        if not isinstance(w, str) or not w:
            results[idx] = {"text": "", "type": "trivia", "confidence": 0.0}
            continue
        p = _build_prompt(
            word=w,
            translation=(translation or "").strip(),
            source_language=source_language,
            target_language=target_language,
            preferred_type=preferred,
        )
        key = f"gemini_fact:{model_name}:{_hash_key(p)}"
        cached = _cache_get(key)
        if cached:
            results[idx] = _coerce_result(cached)
        else:
            tasks.append((idx, key, p))

    if not tasks:
        return [r if r is not None else {"text": "", "type": "trivia", "confidence": 0.0} for r in results]

    # Simple bounded worker pool (threading) to parallelize within limits
    def worker(q: deque[Tuple[int, str, str]]) -> None:
        while True:
            try:
                idx, key, p = q.popleft()
            except IndexError:
                return
            raw = _call_gemini(p, model_id=model_name)
            if not raw:
                results[idx] = {"text": "", "type": "trivia", "confidence": 0.0}
                continue
            try:
                data = _extract_json(raw)
                result = _coerce_result(data)
                if preferred:
                    result["type"] = preferred
                _cache_set(key, {"text": result["text"], "type": result["type"]}, _CACHE_TTL_SECONDS)
                results[idx] = result
            except Exception as e:
                logger.exception("Batch: parse failure for idx=%s word=%r: %s", idx, words[idx], e)
                results[idx] = {"text": "", "type": "trivia", "confidence": 0.0}

    q: deque[Tuple[int, str, str]] = deque(tasks)
    threads: List[threading.Thread] = []
    for _ in range(max_workers):
        t = threading.Thread(target=worker, args=(q,), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    # Fill any None
    return [r if r is not None else {"text": "", "type": "trivia", "confidence": 0.0} for r in results]
