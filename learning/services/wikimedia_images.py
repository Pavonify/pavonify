# learning/services/wikimedia_images.py
from __future__ import annotations

import logging
import os
import re
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# ---------- HTTP clients ----------

WIKI_API = "https://commons.wikimedia.org/w/api.php"
UA = "Pavonify/1.2 (https://www.pavonify.com; admin@pavonify.com)"
TIMEOUT = 12

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})

PIXABAY_API = "https://pixabay.com/api/"
PIXABAY_KEY = os.getenv("PIXABAY_KEY", "").strip()

# ---------- universal heuristics (apply to ALL topics) ----------

_TAGS = re.compile(r"<[^>]+>")

BAD_MIME = ("image/svg+xml",)  # icons/logos etc.
ALWAYS_BAD_WORDS = (
    # non-photo & UI junk
    "logo", "icon", "emblem", "symbol",
    "heraldry", "coat_of_arms", "coat-of-arms", "coat of arms",
    "map", "diagram", "chart", "graph",
    "clipart", "clip-art", "pictogram", "infographic",
    # sculpture/replicas/toys
    "statue", "sculpture", "bust", "figurine", "toy",
    # drawings/paintings/prints
    "painting", "drawing", "sketch", "engraving", "woodcut", "lithograph",
    # plaques/inscriptions (nearly always misleading)
    "plaque", "inscription", "tablet", "relief",
)

ALWAYS_BAD_CATS = (
    "Logos", "Icons", "Heraldry", "Coats of arms",
    "Maps", "Diagrams", "Charts", "Graphs",
    "Clip art", "Pictograms", "Infographics",
    "Statues", "Sculptures", "Busts", "Toys",
    "Paintings", "Drawings", "Sketches", "Engravings", "Lithographs",
)

# People filtering (skip unless profile is "people" or allow_people=True)
PEOPLE_WORDS = (
    "portrait", "headshot", "self-portrait", "selfportrait",
    "person", "people", "man", "woman", "boy", "girl", "human",
    "celebrity", "actor", "actress",
)
PEOPLE_CATS = ("Portraits", "People", "Men", "Women", "Self-portraits", "Celebrities")

def _strip_tags(html: str) -> str:
    return _TAGS.sub("", html or "").strip()

def _looks_like_people(title: str, categories: str) -> bool:
    t = (title or "").lower()
    c = (categories or "").lower()
    if any(b in t for b in PEOPLE_WORDS): return True
    if any(cat.lower() in c for cat in PEOPLE_CATS): return True
    # "Firstname_Lastname" or "Lastname, Firstname"
    if re.search(r"\b[A-Z][a-z]+_[A-Z][a-z]+\b", title or ""): return True
    if re.search(r"\b[A-Z][a-z]+,\s*[A-Z][a-z]+\b", title or ""): return True
    return False

def _looks_like_always_bad(title: str, categories: str, mime: str) -> bool:
    t = (title or "").lower()
    c = (categories or "").lower()
    if mime and (mime in BAD_MIME or not mime.startswith("image/")):
        return True
    if any(b in t for b in ALWAYS_BAD_WORDS): return True
    if any(b.lower() in c for b in (x.lower() for x in ALWAYS_BAD_CATS)): return True
    return False

def _query(params: Dict[str, str]) -> Dict:
    r = SESSION.get(WIKI_API, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

# ---------- context profiles ----------

# Each profile:
# - commons_bias: categories to boost in scoring
# - commons_incat: optional incategory constraint for search
# - pixabay_category: mapped Pixabay category (or "")
CONTEXT_PROFILES = {
    "animals": {
        "commons_bias": (
            r"\b(animals?|wildlife|mammals?|aves|birds?|pisces|fish|fishes|reptiles?|amphibians?|insects?|arachnids?|fauna|felidae|canidae|panthera|equidae|chelonia|testudines)\b",
        ),
        "commons_incat": "Animals",
        "pixabay_category": "animals",
        "default_allow_people": False,
    },
    "transport": {
        "commons_bias": (
            r"\b(transport|transportation|vehicles?|cars?|trucks?|buses|coaches|trains?|railways?|locomotives?|trams?|trolleys?|ships?|boats?|aircraft|airplanes?|planes?|helicopters?|bicycles?|motorcycles?)\b",
        ),
        "commons_incat": "Transport",
        "pixabay_category": "transportation",
        "default_allow_people": False,
    },
    "food": {
        "commons_bias": (r"\b(food|foods|fruits?|vegetables?|meals?|dishes?|cuisine|drinks?|beverages?)\b",),
        "commons_incat": "Food",
        "pixabay_category": "food",
        "default_allow_people": False,
    },
    "people": {
        "commons_bias": (r"\b(people|persons?|occupations?|professions?|jobs?)\b",),
        "commons_incat": "People",
        "pixabay_category": "people",
        "default_allow_people": True,  # portraits allowed here
    },
    "places": {
        "commons_bias": (r"\b(cities?|towns?|villages?|landscapes?|buildings?|landmarks?|monuments?)\b",),
        "commons_incat": "Places",
        "pixabay_category": "places",
        "default_allow_people": False,
    },
    "generic": {
        "commons_bias": (),
        "commons_incat": "",
        "pixabay_category": "",
        "default_allow_people": False,
    },
}

def _detect_profile(context_hint: Optional[str]) -> str:
    ctx = (context_hint or "").lower()
    if any(k in ctx for k in ("animal", "wildlife", "zoo", "fauna")):
        return "animals"
    if any(k in ctx for k in ("transport", "transportation", "vehicle", "vehicles", "cars", "trains", "buses", "ships", "boats", "planes")):
        return "transport"
    if any(k in ctx for k in ("food", "foods", "cuisine", "cooking", "meal", "drink", "beverage")):
        return "food"
    if any(k in ctx for k in ("people", "persons", "occupations", "jobs", "professions", "family", "members", "friends", "relatives")):
        return "people"
    if any(k in ctx for k in ("places", "cities", "buildings", "landmarks", "geography")):
        return "places"
    return "generic"

# ---------- scoring & extraction ----------

def _score_candidate(
    *,
    title: str,
    categories: str,
    mime: str,
    profile: str,
    allow_people: bool,
    keywords: Tuple[str, ...],
) -> int:
    """Positive scores for photo-like results with profile matches; negative for drawings/people (if not allowed)."""
    score = 0
    tl = (title or "").lower()
    cl = (categories or "").lower()

    # exact keyword hits in filename/title
    for kw in keywords:
        if kw and kw.lower() in tl:
            score += 2

    # prefer photos (Commons often tags photographs)
    if "photographs" in cl or "photography" in cl:
        score += 3

    # profile-specific category boosts
    for pat in CONTEXT_PROFILES[profile]["commons_bias"]:
        if re.search(pat, cl, flags=re.I):
            score += 4

    # penalize drawings/paintings/etc.
    if any(w in tl for w in ("painting", "drawing", "sketch", "engraving", "woodcut", "lithograph")):
        score -= 5
    if any(x.lower() in cl for x in ("Paintings","Drawings","Sketches","Engravings","Lithographs")):
        score -= 5

    # people penalty (unless allowed/profile=people)
    if not allow_people and _looks_like_people(title, categories):
        score -= 6

    # drop non-photo-ish mimes
    if mime and mime not in ("image/jpeg", "image/png", "image/gif", "image/webp", "image/tiff"):
        score -= 4

    return score

def _extract_ranked(
    pages: Dict[str, Dict[str, object]],
    limit: int,
    *,
    profile: str,
    allow_people: bool,
    keywords: Tuple[str, ...],
    dbg: Dict[str, int] | None = None,
) -> List[Dict[str, str]]:
    candidates = []
    seen_urls: set[str] = set()

    for page in (pages or {}).values():
        if not isinstance(page, dict):
            continue
        title = page.get("title") or ""
        infos = page.get("imageinfo") or []
        if not infos or not isinstance(infos, list):
            if dbg is not None: dbg["no_imageinfo"] = dbg.get("no_imageinfo", 0) + 1
            continue

        info = infos[0] if isinstance(infos[0], dict) else {}
        url  = info.get("url")
        mime = info.get("mime", "")
        if not url or url in seen_urls:
            if dbg is not None: dbg["missing_or_dup_url"] = dbg.get("missing_or_dup_url", 0) + 1
            continue

        # categories from prop=categories + extmetadata
        categories_text = ""
        if "categories" in page and isinstance(page["categories"], list):
            categories_text = " ".join([c.get("title","") for c in page["categories"] if isinstance(c, dict)])
        meta = info.get("extmetadata") or {}
        categories_text += " " + (meta.get("Categories") or {}).get("value", "")

        # universal bad filters
        if _looks_like_always_bad(title, categories_text, mime):
            if dbg is not None: dbg["universal_bad"] = dbg.get("universal_bad", 0) + 1
            continue
        if not allow_people and _looks_like_people(title, categories_text):
            if dbg is not None: dbg["people_filtered"] = dbg.get("people_filtered", 0) + 1
            continue

        score = _score_candidate(
            title=title, categories=categories_text, mime=mime,
            profile=profile, allow_people=allow_people, keywords=keywords,
        )

        # soft floor to discard very dubious matches
        if score < -1:
            if dbg is not None: dbg["low_score"] = dbg.get("low_score", 0) + 1
            continue

        thumb = info.get("thumburl") or url
        artist  = (meta.get("Artist") or {}).get("value", "")
        credit  = (meta.get("Credit") or {}).get("value", "")
        license_short = (meta.get("LicenseShortName") or {}).get("value", "")
        attribution_html = artist or credit or "Wikimedia Commons"

        candidates.append((
            score,
            {
                "url": url,
                "thumb": thumb or url,
                "source": "Wikimedia",
                "attribution": attribution_html,
                "attribution_text": _strip_tags(attribution_html),
                "license": license_short,
            }
        ))
        seen_urls.add(url)

    candidates.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in candidates[:limit]]

# ---------- Pixabay fallback ----------

def _pixabay_search(query: str, limit: int, *, profile: str) -> List[Dict[str, str]]:
    if not PIXABAY_KEY:
        return []

    category = CONTEXT_PROFILES[profile]["pixabay_category"]

    params = {
        "key": PIXABAY_KEY,
        "q": query,
        "image_type": "photo",
        "safesearch": "true",
        "orientation": "horizontal",
        "per_page": max(10, limit * 3),
        "order": "popular",
    }
    if category:
        params["category"] = category

    try:
        r = SESSION.get(PIXABAY_API, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.warning("Pixabay fallback failed for %r: %s", query, e)
        return []

    hits = data.get("hits") or []
    out: List[Dict[str, str]] = []
    for h in hits:
        url = h.get("largeImageURL") or h.get("webformatURL")
        if not url:
            continue
        out.append({
            "url": url,
            "thumb": h.get("webformatURL") or url,
            "source": "Pixabay",
            "attribution": "Pixabay (free to use)",
            "attribution_text": "Pixabay (free to use)",
            "license": "Pixabay License",
        })
        if len(out) >= limit:
            break
    return out

# ---------- Public API ----------

def search_images(
    word: str,
    limit: int = 3,
    *,
    source_word: Optional[str] = None,     # gloss like "fish"
    context_hint: Optional[str] = None,    # e.g. "Animals", "Transport", "Food", "People", ...
    allow_people: Optional[bool] = None,   # override people filter per-call
    return_debug: bool = False,            # when True, return {"images":[...], "debug":{...}}
) -> List[Dict[str, str]] | Dict[str, object]:
    """
    Wikimedia first (profile-aware query + scoring). If too few matches,
    fall back to Pixabay with the right category for the profile.

    If return_debug=True, returns {"images": [...], "debug": {...}} for use in a debug page.
    """
    if not word:
        return [] if not return_debug else {"images": [], "debug": {"reason": "empty_word"}}
    limit = max(int(limit), 1)

    # pick a profile from context
    profile = _detect_profile(context_hint)
    profile_cfg = CONTEXT_PROFILES[profile]

    # allow_people final decision
    allow_people_final = bool(allow_people) or profile_cfg["default_allow_people"]

    gloss = (source_word or "").strip()
    keywords = tuple(k for k in {word, gloss} if k)

    # universal negatives; only add people-negatives if people aren't allowed
    negatives_common = "-icon -svg -heraldry -coat -arms -map -diagram -chart -graph -clipart -pictogram -statue -sculpture -toy -logo -painting -drawing -sketch -engraving -lithograph -plaque -inscription -relief -tablet"
    negatives_people = "" if allow_people_final else " -portrait -person -headshot -self-portrait -human"

    incat = f' incategory:"{profile_cfg["commons_incat"]}"' if profile_cfg["commons_incat"] else ""
    base_query = f'filetype:bitmap intitle:{word} {gloss} {negatives_common}{negatives_people}{incat}'.strip()

    dbg: Dict[str, int] = {} if return_debug else None

    try:
        params = {
            "action": "query",
            "format": "json",
            "prop": "imageinfo|categories",
            "generator": "search",
            "gsrsearch": base_query,
            "gsrnamespace": 6,
            "gsrlimit": max(limit * 20, 50),
            "iiprop": "url|mime|extmetadata",
            "iiurlwidth": 512,
            "redirects": 1,
            "clshow": "!hidden",
            "cllimit": 50,
        }
        data = _query(params)
        pages = (data.get("query") or {}).get("pages") or {}
        results = _extract_ranked(
            pages if isinstance(pages, dict) else {},
            limit,
            profile=profile,
            allow_people=allow_people_final,
            keywords=keywords,
            dbg=dbg,
        )

        # Try again with just gloss if weak.
        if len(results) < limit and gloss:
            params["gsrsearch"] = f'filetype:bitmap intitle:{gloss} {negatives_common}{negatives_people}{incat}'.strip()
            data = _query(params)
            pages = (data.get("query") or {}).get("pages") or {}
            extra = _extract_ranked(
                pages if isinstance(pages, dict) else {},
                limit - len(results),
                profile=profile,
                allow_people=allow_people_final,
                keywords=keywords,
                dbg=dbg,
            )
            results.extend(extra)

        # Pixabay fallback if still short
        if len(results) < limit:
            pixabay_q = gloss or word
            pix = _pixabay_search(pixabay_q, limit - len(results), profile=profile)
            results.extend(pix)

        images = results[:limit]
        if return_debug:
            dbg_out = {
                "profile": profile,
                "allow_people": allow_people_final,
                "commons_query": base_query,
                "commons_returned": len((data or {}).get("query", {}).get("pages", {}) if isinstance(data, dict) else {}),
                "drop_reasons": dbg,
                "pixabay_used": max(0, limit - len(results)),
            }
            return {"images": images, "debug": dbg_out}
        return images
    except Exception as e:
        logger.warning("Image search failed for %r: %s", word, e)
        fb = _pixabay_search(gloss or word, limit, profile=profile)
        if return_debug:
            return {"images": fb[:limit], "debug": {"exception": str(e), "fallback": "pixabay", "profile": profile}}
        return fb[:limit]
