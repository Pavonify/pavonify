# learning/services/enrichment.py
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from typing import Any, Dict, List, Optional
import logging
import os
import time

from django.utils.translation import get_language_info

from .gemini_facts import get_fact
from .wikimedia_images import search_images

logger = logging.getLogger(__name__)

# Tunables (can override via env)
PER_WORD_TIMEOUT = float(os.getenv("ENRICH_TIMEOUT_PER_WORD", "6.0"))   # seconds for images/fact each
MAX_THREADS = int(os.getenv("ENRICH_MAX_THREADS", "8"))  # overall concurrency cap
IMG_LIMIT = int(os.getenv("ENRICH_IMG_LIMIT", "3"))

_FACT_TYPES = {"etymology", "idiom", "trivia"}


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

def _safe_images(payload: Any) -> List[Dict[str, str]]:
    try:
        if isinstance(payload, dict):
            query = (payload.get("word") or payload.get("query") or "").strip()
            source_word = (payload.get("source_word") or "").strip()
            context_hint = payload.get("context_hint") or payload.get("context") or None
            exclude = payload.get("exclude") or []
        else:
            query = str(payload or "").strip()
            source_word = ""
            context_hint = None
            exclude = []
        cleaned_exclude = [
            str(url).strip()
            for url in (exclude or [])
            if isinstance(url, str) and url and str(url).strip()
        ]
        return search_images(
            query,
            limit=IMG_LIMIT,
            source_word=source_word or None,
            context_hint=context_hint or None,
            exclude_urls=cleaned_exclude,
        )
    except Exception as e:
        query = payload.get("word") if isinstance(payload, dict) else payload
        logger.warning("image search failed for %r: %s", query, e)
        return []

def _safe_fact(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        result = get_fact(**payload)
        preferred = payload.get("preferred_type")
        if (
            preferred == "idiom"
            and not (result.get("text") or "").strip()
        ):
            return {"text": "No idiom available.", "type": "idiom", "confidence": 0.0}
        text = (result.get("text") or "").strip()
        if not text:
            return _fallback_fact(payload)
        result["text"] = text
        rtype = (result.get("type") or "").strip().lower()
        if rtype not in _FACT_TYPES:
            result["type"] = preferred if preferred in _FACT_TYPES and preferred != "idiom" else "trivia"
        if "confidence" not in result or not isinstance(result.get("confidence"), (int, float)):
            result["confidence"] = 0.0
        return result
    except Exception as e:
        logger.warning("fact generation failed for %r: %s", payload.get("word"), e)
        preferred = payload.get("preferred_type")
        fallback = preferred if preferred in _FACT_TYPES else "trivia"
        if fallback == "idiom":
            return {"text": "No idiom available.", "type": "idiom", "confidence": 0.0}
        adjusted = dict(payload)
        adjusted["preferred_type"] = fallback
        return _fallback_fact(adjusted)


def _fallback_fact(payload: Dict[str, Any]) -> Dict[str, Any]:
    word = (payload.get("word") or "").strip()
    translation = (payload.get("translation") or "").strip()
    source_label = _language_label(payload.get("source_language")) or (
        payload.get("source_language") or "the source language"
    )
    target_label = _language_label(payload.get("target_language")) or (
        payload.get("target_language") or "the target language"
    )
    fact_type = payload.get("preferred_type")
    if fact_type not in _FACT_TYPES or fact_type == "idiom":
        fact_type = "trivia"
    if translation:
        text = f'In {target_label}, "{word}" means "{translation}" in {source_label}.'
    elif word and target_label:
        text = f'"{word}" is a useful {target_label} word to teach.'
    else:
        text = f'Add your own fun fact about "{word}".'
    if len(text) > 220:
        text = text[:220].rstrip()
    return {"text": text, "type": fact_type, "confidence": 0.1}


def _with_timeout(fn, arg, timeout: float):
    """Run fn(arg) with a hard timeout; return None on timeout/error."""
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(fn, arg)
        done, _ = wait([fut], timeout=timeout, return_when=FIRST_COMPLETED)
        if fut in done:
            try:
                return fut.result()
            except Exception as e:
                logger.warning("task error for %r: %s", arg, e)
                return None
        logger.warning("task timed out for %r after %.1fs", arg, timeout)
        return None

def _normalize_fact_type(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    lowered = value.strip().lower()
    return lowered if lowered in _FACT_TYPES else None


def enrich_one(
    entry: Dict[str, Any],
    *,
    source_language: Optional[str] = None,
    target_language: Optional[str] = None,
) -> Dict[str, Any]:
    w = (entry.get("word") or "").strip()
    if not w:
        return {}
    translation = (entry.get("translation") or "").strip()
    requested_type = _normalize_fact_type(entry.get("fact_type"))
    fact_word = w
    source_term = translation or None

    exclude_images_raw = entry.get("exclude_images") or []
    exclude_images = [
        str(url).strip()
        for url in exclude_images_raw
        if isinstance(url, str) and url and str(url).strip()
    ]
    image_payload = {"word": w, "exclude": exclude_images}

    # run images + fact in parallel, each time-boxed
    with ThreadPoolExecutor(max_workers=2) as ex:
        fi = ex.submit(
            _with_timeout,
            _safe_images,
            image_payload,
            PER_WORD_TIMEOUT,
        )
        ff = ex.submit(
            _with_timeout,
            _safe_fact,
            {
                "word": fact_word,
                "translation": source_term or None,
                "source_language": source_language,
                "target_language": target_language,
                "preferred_type": requested_type,
            },
            PER_WORD_TIMEOUT,
        )
        images = fi.result() or []
        fact = ff.result() or {
            "text": "",
            "type": requested_type or "trivia",
            "confidence": 0.0,
        }
    return {"word": w, "translation": translation, "images": images, "fact": fact}

def get_enrichments(
    entries: List[Any],
    *,
    source_language: Optional[str] = None,
    target_language: Optional[str] = None,
) -> List[Dict[str, Any]]:
    clean: List[Dict[str, Any]] = []
    for item in entries or []:
        if isinstance(item, dict):
            word = (item.get("word") or "").strip()
            if not word:
                continue
            translation = (item.get("translation") or "").strip()
            fact_type = _normalize_fact_type(item.get("fact_type"))
            exclude_raw = item.get("exclude_images") or []
            exclude_images = [
                str(url).strip()
                for url in exclude_raw
                if isinstance(url, str) and url and str(url).strip()
            ]
            clean.append(
                {
                    "word": word,
                    "translation": translation,
                    "fact_type": fact_type,
                    "exclude_images": exclude_images,
                }
            )
        elif isinstance(item, str):
            word = item.strip()
            if word:
                clean.append({"word": word, "translation": "", "fact_type": None, "exclude_images": []})

    if not clean:
        return []
    start = time.time()
    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(MAX_THREADS, max(1, len(clean)))) as ex:
        futures = [
            ex.submit(
                enrich_one,
                entry,
                source_language=source_language,
                target_language=target_language,
            )
            for entry in clean
        ]
        for fut in futures:
            try:
                row = fut.result()
            except Exception as exc:
                logger.warning("enrichment worker failed: %s", exc)
                continue
            if row:
                results.append(row)
    logger.info("enrichment built for %d words in %.2fs", len(clean), time.time() - start)
    return results
