# learning/services/enrichment.py
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from typing import Any, Dict, List
import logging
import os
import time

from .gemini_facts import get_fact
from .wikimedia_images import search_images

logger = logging.getLogger(__name__)

# Tunables (can override via env)
PER_WORD_TIMEOUT = float(os.getenv("ENRICH_TIMEOUT_PER_WORD", "6.0"))   # seconds for images/fact each
MAX_THREADS      = int(os.getenv("ENRICH_MAX_THREADS", "8"))            # overall concurrency cap
IMG_LIMIT        = int(os.getenv("ENRICH_IMG_LIMIT", "3"))

def _safe_images(word: str) -> List[Dict[str, str]]:
    try:
        return search_images(word, limit=IMG_LIMIT)
    except Exception as e:
        logger.warning("image search failed for %r: %s", word, e)
        return []

def _safe_fact(word: str) -> Dict[str, Any]:
    try:
        return get_fact(word)
    except Exception as e:
        logger.warning("fact generation failed for %r: %s", word, e)
        return {"text": "", "type": "trivia", "confidence": 0.0}

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

def enrich_one(word: str) -> Dict[str, Any]:
    w = (word or "").strip()
    if not w:
        return {}
    # run images + fact in parallel, each time-boxed
    with ThreadPoolExecutor(max_workers=2) as ex:
        fi = ex.submit(_with_timeout, _safe_images, w, PER_WORD_TIMEOUT)
        ff = ex.submit(_with_timeout, _safe_fact,   w, PER_WORD_TIMEOUT)
        images = fi.result() or []
        fact   = ff.result() or {"text": "", "type": "trivia", "confidence": 0.0}
    return {"word": w, "images": images, "fact": fact}

def get_enrichments(words: List[str]) -> List[Dict[str, Any]]:
    clean = [w.strip() for w in (words or []) if isinstance(w, str) and w.strip()]
    if not clean:
        return []
    start = time.time()
    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(MAX_THREADS, max(1, len(clean)))) as ex:
        for row in ex.map(enrich_one, clean):
            if row:
                results.append(row)
    logger.info("enrichment built for %d words in %.2fs", len(clean), time.time() - start)
    return results
