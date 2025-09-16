# learning/services/enrichment.py
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from typing import Any, Dict, List, Optional
import logging
import os
import time

from .gemini_facts import get_fact
from .wikimedia_images import search_images

logger = logging.getLogger(__name__)

# Tunables (can override via env)
PER_WORD_TIMEOUT = float(os.getenv("ENRICH_TIMEOUT_PER_WORD", "6.0"))   # seconds for images/fact each
MAX_THREADS = int(os.getenv("ENRICH_MAX_THREADS", "8"))  # overall concurrency cap
IMG_LIMIT = int(os.getenv("ENRICH_IMG_LIMIT", "3"))

_FACT_TYPES = {"etymology", "idiom", "trivia"}

def _safe_images(word: str) -> List[Dict[str, str]]:
    try:
        return search_images(word, limit=IMG_LIMIT)
    except Exception as e:
        logger.warning("image search failed for %r: %s", word, e)
        return []

def _safe_fact(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return get_fact(**payload)
    except Exception as e:
        logger.warning("fact generation failed for %r: %s", payload.get("word"), e)
        preferred = payload.get("preferred_type")
        fallback = preferred if preferred in _FACT_TYPES else "trivia"
        return {"text": "", "type": fallback, "confidence": 0.0}

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

    # run images + fact in parallel, each time-boxed
    with ThreadPoolExecutor(max_workers=2) as ex:
        fi = ex.submit(_with_timeout, _safe_images, w, PER_WORD_TIMEOUT)
        ff = ex.submit(
            _with_timeout,
            _safe_fact,
            {
                "word": w,
                "translation": translation or None,
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
            clean.append({"word": word, "translation": translation, "fact_type": fact_type})
        elif isinstance(item, str):
            word = item.strip()
            if word:
                clean.append({"word": word, "translation": "", "fact_type": None})

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
