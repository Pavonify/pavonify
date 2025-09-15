from __future__ import annotations

from typing import Any, Dict, List

from .gemini_facts import get_fact
from .wikimedia_images import search_images

def get_enrichments(words: List[str]) -> List[Dict[str, Any]]:
    """
    For each word, returns:
      {"word": str,
       "images": [{"url","thumb","source","attribution","license"}, ...],
       "fact": {"text","type","confidence"}}
    """
    out: List[Dict[str, Any]] = []
    for w in words:
        w_clean = (w or "").strip()
        if not w_clean:
            continue
        images = search_images(w_clean, limit=3)
        fact = get_fact(w_clean)
        out.append({
            "word": w_clean,
            "images": images,
            "fact": fact,
        })
    return out
