from __future__ import annotations

import logging
from typing import Dict, List

import requests

logger = logging.getLogger(__name__)

API = "https://commons.wikimedia.org/w/api.php"

def search_images(word: str, limit: int = 3) -> List[Dict[str, str]]:
    """
    Returns up to `limit` images with fields:
    {url, thumb, source, attribution, license}
    """
    try:
        params = {
            "action": "query",
            "format": "json",
            "prop": "imageinfo",
            "generator": "search",
            "gsrsearch": word,
            "gsrlimit": limit,
            "iiprop": "url|extmetadata",
            "iiurlwidth": 320,
            "redirects": 1,
            "origin": "*",
        }
        r = requests.get(API, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        pages = (data.get("query") or {}).get("pages") or {}
        results: List[Dict[str, str]] = []
        for _, page in pages.items():
            infos = page.get("imageinfo") or []
            if not infos:
                continue
            info = infos[0]
            url = info.get("url")
            thumb = info.get("thumburl", url)
            meta = (info.get("extmetadata") or {})
            license_short = (meta.get("LicenseShortName") or {}).get("value", "")
            artist = (meta.get("Artist") or {}).get("value", "")
            credit = (meta.get("Credit") or {}).get("value", "")
            attribution = artist or credit or "Wikimedia Commons"
            if url:
                results.append({
                    "url": url,
                    "thumb": thumb or url,
                    "source": "Wikimedia",
                    "attribution": attribution,
                    "license": license_short,
                })
        return results[:limit]
    except Exception as e:
        logger.warning("Wikimedia search failed for '%s': %s", word, e)
        return []
