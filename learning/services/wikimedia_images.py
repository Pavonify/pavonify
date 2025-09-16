from __future__ import annotations

import logging
from typing import Dict, List
import requests

logger = logging.getLogger(__name__)

API = "https://commons.wikimedia.org/w/api.php"
UA  = "Pavonify/1.0 (https://www.pavonify.com; admin@pavonify.com)"  # <-- set a real contact email/url
TIMEOUT = 12

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})

def _extract_from_pages(pages: Dict[str, Dict[str, object]]) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    seen: set[str] = set()
    for page in pages.values():
        infos = page.get("imageinfo") if isinstance(page, dict) else None
        if not infos or not isinstance(infos, list):
            continue
        info = infos[0]
        if not isinstance(info, dict):
            continue
        url = info.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        thumb = info.get("thumburl") or url
        meta = info.get("extmetadata") if isinstance(info.get("extmetadata"), dict) else {}
        license_short = (meta.get("LicenseShortName") or {}).get("value", "") if isinstance(meta.get("LicenseShortName"), dict) else ""
        artist        = (meta.get("Artist")          or {}).get("value", "") if isinstance(meta.get("Artist"), dict)          else ""
        credit        = (meta.get("Credit")          or {}).get("value", "") if isinstance(meta.get("Credit"), dict)          else ""
        attribution   = artist or credit or "Wikimedia Commons"
        results.append({
            "url": url,
            "thumb": thumb or url,
            "source": "Wikimedia",
            "attribution": attribution,
            "license": license_short,
        })
    return results

def _search_titles(word: str, limit: int) -> List[str]:
    params = {
        "action": "query",
        "format": "json",
        "list": "search",
        "srsearch": word,        # <- keep it simple and broad
        "srnamespace": 6,        # File namespace
        "srlimit": max(limit * 3, limit),
        "srinfo": "totalhits",
    }
    r = SESSION.get(API, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    hits = (data.get("query") or {}).get("search") or []
    titles: List[str] = []
    for item in hits:
        title = item.get("title") if isinstance(item, dict) else None
        if title:
            titles.append(title)
        if len(titles) >= limit * 5:
            break
    return titles

def _fetch_by_titles(titles: List[str]) -> List[Dict[str, str]]:
    if not titles:
        return []
    params = {
        "action": "query",
        "format": "json",
        "prop": "imageinfo",
        "titles": "|".join(titles[:50]),
        "iiprop": "url|extmetadata",
        "iiurlwidth": 512,
        "redirects": 1,
    }
    r = SESSION.get(API, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    pages = (data.get("query") or {}).get("pages") or {}
    return _extract_from_pages(pages if isinstance(pages, dict) else {})

def search_images(word: str, limit: int = 3) -> List[Dict[str, str]]:
    """Return up to ``limit`` candidate images from Wikimedia Commons."""
    if not word:
        return []
    limit = max(int(limit), 1)
    try:
        # Primary: generator=search in File namespace (broad query, no filetype filter)
        params = {
            "action": "query",
            "format": "json",
            "prop": "imageinfo",
            "generator": "search",
            "gsrsearch": word,        # <- removed filetype filter
            "gsrnamespace": 6,
            "gsrlimit": max(limit * 3, limit),
            "iiprop": "url|extmetadata",
            "iiurlwidth": 512,
            "redirects": 1,
        }
        r = SESSION.get(API, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        pages = (data.get("query") or {}).get("pages") or {}
        results = _extract_from_pages(pages if isinstance(pages, dict) else {})
        if results:
            return results[:limit]

        # Fallback: title search then resolve
        titles = _search_titles(word, limit)
        fallback = _fetch_by_titles(titles)
        return fallback[:limit]
    except Exception as e:
        logger.warning("Wikimedia search failed for '%s': %s", word, e)
        return []
