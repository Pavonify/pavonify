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

# ---------------- heuristics ----------------

_TAGS = re.compile(r"<[^>]+>")

# things we almost never want (unless the context explicitly allows)
BAD_MIME = ("image/svg+xml",)  # icons/logos
ALWAYS_BAD_WORDS = (
    "logo", "icon", "emblem", "symbol",
    "heraldry", "coat_of_arms", "coat-of-arms", "coat of arms",
    "map", "diagram", "clipart", "clip-art", "pictogram",
    "statue", "sculpture", "bust", "figurine", "toy",
)
ALWAYS_BAD_CATS = (
    "Logos", "Icons", "Heraldry", "Coats of arms", "Maps", "Diagrams", "Clip art",
    "Pictograms", "Infographics", "Statues", "Sculptures",
)

# people/portraits filters (skipped when allow_people=True)
PEOPLE_WORDS = (
    "portrait", "headshot", "self-portrait", "selfportrait",
    "person", "people", "man", "woman", "boy", "girl", "human",
    "celebrity", "actor", "actress",
)
PEOPLE_CATS = ("Portrait", "People", "Men", "Women", "Self-portraits", "Celebrities")

ANIMALISH_CATS = (
    "Animals", "Mammals", "Birds", "Fish", "Reptiles",
    "Amphibians", "Insects", "Arachnids", "Wildlife",
)

PEOPLE_CONTEXT_HINTS = ("family", "members", "people", "persons", "jobs", "professions", "occupations", "friends", "relatives")
ANIMAL_CONTEXT_HINTS = ("animal", "animals", "wildlife", "zoo", "fauna")

def _strip_tags(html: str) -> str:
    return _TAGS.sub("", html or "").strip()

def _classify_context(context_hint: Optional[str]) -> dict:
    ctx = (context_hint or "").strip().lower()
    prefer_animals = any(k in ctx for k in ANIMAL_CONTEXT_HINTS)
    prefer_people  = any(k in ctx for k in PEOPLE_CONTEXT_HINTS)
    return {"prefer_animals": prefer_animals, "prefer_people": prefer_people}

def _looks_like_people(title: str, categories: str) -> bool:
    t = (title or "").lower()
    c = (categories or "").lower()
    if any(b in t for b in PEOPLE_WORDS): return True
    if any(b.lower() in c for b in PEOPLE_CATS): return True
    # crude: filenames like "Firstname_Lastname" often indicate people
    if re.search(r"[A-Z][a-z]+_[A-Z][a-z]+", title or ""): return True
    return False

def _looks_like_always_bad(title: str, categories: str, mime: str) -> bool:
    t = (title or "").lower()
    c = (categories or "").lower()
    if mime and (mime in BAD_MIME or not mime.startswith("image/")):
        return True
    if any(b in t for b in ALWAYS_BAD_WORDS): return True
    if any(b.lower() in c for b in ALWAYS_BAD_CATS): return True
    return False

# --------------- core helpers ---------------

def _query(params: Dict[str, str]) -> Dict:
    r = SESSION.get(API, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def _extract_from_pages(pages: Dict[str, Dict[str, object]], limit: int, *, allow_people: bool, prefer_animals: bool) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen: set[str] = set()
    for page in pages.values():
        if not isinstance(page, dict):
            continue
        title = page.get("title") or ""
        infos = page.get("imageinfo") or []
        if not infos or not isinstance(infos, list):
            continue
        info = infos[0] if isinstance(infos[0], dict) else {}
        url  = info.get("url")
        mime = info.get("mime", "")
        if not url or url in seen:
            continue

        # categories from prop=categories plus any extmetadata we get
        categories_text = ""
        if "categories" in page and isinstance(page["categories"], list):
            categories_text = " ".join([c.get("title","") for c in page["categories"] if isinstance(c, dict)])
        meta = info.get("extmetadata") or {}
        categories_text += " " + (meta.get("Categories") or {}).get("value", "")

        # global bad filters (icons, heraldry, statues, etc.)
        if _looks_like_always_bad(title, categories_text, mime):
            continue

        # optional people filter
        if not allow_people and _looks_like_people(title, categories_text):
            continue

        # optional animal preference (if context suggests animals)
        if prefer_animals:
            cats_l = categories_text.lower()
            if not any(cat.lower() in cats_l for cat in ANIMALISH_CATS):
                # try to keep animal-ish; skip otherwise
                continue

        seen.add(url)
        thumb = info.get("thumburl") or url
        artist  = (meta.get("Artist") or {}).get("value", "")
        credit  = (meta.get("Credit") or {}).get("value", "")
        license_short = (meta.get("LicenseShortName") or {}).get("value", "")
        attribution_html = artist or credit or "Wikimedia Commons"
        out.append({
            "url": url,
            "thumb": thumb or url,
            "source": "Wikimedia",
            "attribution": attribution_html,
            "attribution_text": _strip_tags(attribution_html),
            "license": license_short,
        })
        if len(out) >= limit:
            break
    return out

# --------------- main API -------------------

def search_images(
    word: str,
    limit: int = 3,
    *,
    source_word: Optional[str] = None,     # gloss like "fish"
    context_hint: Optional[str] = None,    # list title: "Animals", "School subjects", "Family members", ...
    allow_people: Optional[bool] = None,   # override people filter per-call
) -> List[Dict[str, str]]:
    """
    Return up to `limit` candidate images using:
    - positive bias from `source_word` (gloss) and `context_hint`,
    - negative filters for icons/heraldry/statues/etc,
    - optional people filtering (skipped if allow_people or context suggests people),
    - optional animal preference when context suggests animals.
    """
    if not word:
        return []
    limit = max(int(limit), 1)

    # context classification
    ctx = _classify_context(context_hint)
    prefer_animals = ctx["prefer_animals"]
    prefer_people  = ctx["prefer_people"]

    # allow_people final decision
    allow_people = bool(allow_people) or prefer_people

    gloss = (source_word or "").strip()

    # Build CirrusSearch query: prefer bitmaps/photos; include gloss; push away junk.
    negatives_common = "-icon -svg -heraldry -coat -arms -map -diagram -clipart -pictogram -statue -sculpture -toy -logo"
    negatives_people = "" if allow_people else " -portrait -person -headshot -self-portrait -human"
    incat = ' incategory:"Animals"' if prefer_animals else ""
    positive_terms = f"{word} {gloss}".strip()
    base_query = f'filetype:bitmap {positive_terms} {negatives_common}{negatives_people}{incat}'.strip()

    try:
        # Primary: generator=search with categories + imageinfo
        params = {
            "action": "query",
            "format": "json",
            "prop": "imageinfo|categories",
            "generator": "search",
            "gsrsearch": base_query,
            "gsrnamespace": 6,
            "gsrlimit": max(limit * 8, limit),
            "iiprop": "url|mime|extmetadata",
            "iiurlwidth": 512,
            "redirects": 1,
            "clshow": "!hidden",
            "cllimit": 50,
        }
        data = _query(params)
        pages = (data.get("query") or {}).get("pages") or {}
        results = _extract_from_pages(pages if isinstance(pages, dict) else {}, limit,
                                      allow_people=allow_people, prefer_animals=prefer_animals)
        if results:
            return results

        # Fallback A: gloss only (retain context)
        if gloss:
            params["gsrsearch"] = f'filetype:bitmap {gloss} {negatives_common}{negatives_people}{incat}'
            data = _query(params)
            pages = (data.get("query") or {}).get("pages") or {}
            results = _extract_from_pages(pages if isinstance(pages, dict) else {}, limit,
                                          allow_people=allow_people, prefer_animals=prefer_animals)
            if results:
                return results

        # Fallback B: drop category constraints but keep filters
        del params["clshow"]; del params["cllimit"]
        params["prop"] = "imageinfo"
        params["gsrsearch"] = f'filetype:bitmap {positive_terms} {negatives_common}{negatives_people}'
        data = _query(params)
        pages = (data.get("query") or {}).get("pages") or {}
        results = _extract_from_pages(pages if isinstance(pages, dict) else {}, limit,
                                      allow_people=allow_people, prefer_animals=False)
        return results
    except Exception as e:
        logger.warning("Wikimedia search failed for %r: %s", word, e)
        return []
