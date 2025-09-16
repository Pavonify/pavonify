from __future__ import annotations
import logging, re
from typing import Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

API = "https://commons.wikimedia.org/w/api.php"
UA  = "Pavonify/1.0 (https://www.pavonify.com; admin@pavonify.com)"
TIMEOUT = 12

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})

_TAGS = re.compile(r"<[^>]+>")
BAD_WORDS = (
    "portrait", "headshot", "self-portrait", "selfportrait",
    "person", "people", "man", "woman", "boy", "girl", "human",
)
BAD_CATS = (
    "Portrait", "People", "Men", "Women", "Self-portraits", "Celebrities",
)

def _strip_tags(html: str) -> str:
    return _TAGS.sub("", html or "").strip()

def _looks_like_person(title: str, categories: str) -> bool:
    t = (title or "").lower()
    c = (categories or "").lower()
    if any(b in t for b in BAD_WORDS): return True
    if any(b.lower() in c for b in BAD_CATS): return True
    # crude: filenames like "Firstname_Lastname" often indicate people
    if re.search(r"[A-Z][a-z]+_[A-Z][a-z]+", title or ""): return True
    return False

def _extract_from_pages(pages: Dict[str, Dict[str, object]], limit: int) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen: set[str] = set()
    for page in pages.values():
        if not isinstance(page, dict): continue
        title = page.get("title") or ""
        infos = page.get("imageinfo") or []
        if not infos or not isinstance(infos, list): continue
        info = infos[0] if isinstance(infos[0], dict) else {}
        url = info.get("url")
        if not url or url in seen: continue
        meta = info.get("extmetadata") or {}
        license_short = (meta.get("LicenseShortName") or {}).get("value", "")
        artist        = (meta.get("Artist") or {}).get("value", "")
        credit        = (meta.get("Credit") or {}).get("value", "")
        categories    = (meta.get("Categories") or {}).get("value", "")
        if _looks_like_person(title, categories):
            continue  # drop portraits/people
        seen.add(url)
        thumb = info.get("thumburl") or url
        attribution_html = artist or credit or "Wikimedia Commons"
        out.append({
            "url": url,
            "thumb": thumb or url,
            "source": "Wikimedia",
            "attribution": attribution_html,
            "attribution_text": _strip_tags(attribution_html),
            "license": license_short,
        })
        if len(out) >= limit: break
    return out

def _query_pages(params: Dict[str, str]) -> Dict[str, Dict[str, object]]:
    r = SESSION.get(API, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return (data.get("query") or {}).get("pages") or {}

def search_images(word: str, limit: int = 3, *, source_word: Optional[str] = None) -> List[Dict[str, str]]:
    """
    Return up to `limit` candidate images for a concept, steering away from people/portraits.
    `source_word` is an English (or class source-language) gloss like "bird".
    """
    if not word: return []
    limit = max(int(limit), 1)

    # Build a richer search string: target word + gloss + negative terms
    negatives = "-portrait -person -headshot -self-portrait -human"
    gloss = (source_word or "").strip()
    base_query = f'{word} {gloss} {negatives}'.strip()

    try:
        # Primary: generator=search on File namespace with combined terms
        params = {
            "action": "query",
            "format": "json",
            "prop": "imageinfo",
            "generator": "search",
            "gsrsearch": base_query,
            "gsrnamespace": 6,
            "gsrlimit": max(limit * 4, limit),
            "iiprop": "url|extmetadata",
            "iiurlwidth": 512,
            "redirects": 1,
        }
        pages = _query_pages(params)
        results = _extract_from_pages(pages if isinstance(pages, dict) else {}, limit)
        if results:
            return results

        # Fallback A: search by gloss only (e.g., "bird -portrait ...")
        if gloss:
            params["gsrsearch"] = f"{gloss} {negatives}"
            pages = _query_pages(params)
            results = _extract_from_pages(pages if isinstance(pages, dict) else {}, limit)
            if results:
                return results

        # Fallback B: title search -> resolve
        s_params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": base_query,
            "srnamespace": 6,
            "srlimit": max(limit * 6, limit),
            "srinfo": "totalhits",
        }
        s = SESSION.get(API, params=s_params, timeout=TIMEOUT)
        s.raise_for_status()
        hits = (s.json().get("query") or {}).get("search") or []
        titles = [h.get("title") for h in hits if isinstance(h, dict) and h.get("title")]
        if not titles:
            return []

        q_params = {
            "action": "query",
            "format": "json",
            "prop": "imageinfo",
            "titles": "|".join(titles[:50]),
            "iiprop": "url|extmetadata",
            "iiurlwidth": 512,
            "redirects": 1,
        }
        pages = _query_pages(q_params)
        return _extract_from_pages(pages if isinstance(pages, dict) else {}, limit)

    except Exception as e:
        logger.warning("Wikimedia search failed for %r: %s", word, e)
        return []
