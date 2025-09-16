from __future__ import annotations
import logging
import re
from functools import lru_cache
from typing import Dict, List, Optional, Tuple
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
    "map", "atlas", "diagram", "clipart", "clip-art", "pictogram",
    "infographic", "poster", "banner", "flyer",
    "statue", "sculpture", "bust", "figurine", "toy",
    "seal", "crest", "insignia",
    "stamp", "postage", "coin", "banknote",
    # typical texture/stock/background junk
    "texture", "tile", "tiled", "tiles", "mosaic", "patchwork", "background",
    "pattern", "fabric", "wallpaper", "swatch", "sample", "macro", "close-up",
    "collage", "abstract",
)

ALWAYS_BAD_CATS = (
    "Logos", "Icons", "Heraldry", "Coats of arms", "Maps", "Diagrams", "Clip art",
    "Pictograms", "Infographics", "Statues", "Sculptures", "Collages",
    "Backgrounds", "Textures", "Patterns", "Wallpapers", "Fabrics",
)

# people/portraits filters (skipped when allow_people=True)
PEOPLE_WORDS = (
    "portrait", "headshot", "self-portrait", "selfportrait",
    "person", "people", "man", "woman", "boy", "girl", "human",
    "celebrity", "actor", "actress",
)
PEOPLE_CATS = ("Portraits", "People", "Men", "Women", "Self-portraits", "Celebrities")

ANIMALISH_CATS = (
    "Animals", "Mammals", "Birds", "Fish", "Reptiles",
    "Amphibians", "Insects", "Arachnids", "Wildlife",
)

# Fine-grained nudges to help generic vocab like "fish", "turtle", "cat", etc.
ANIMAL_KEY_HINTS: Dict[str, Tuple[str, ...]] = {
    "fish": ("fish", "fishes", "teleost", "ichthy", "shark", "ray", "eel"),
    "turtle": ("turtle", "tortoise", "terrapin", "cheloni", "sea turtle"),
    "bird": ("bird", "avian"),
    "cat": ("cat", "felid", "feline"),
    "dog": ("dog", "canid", "canine"),
}

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

# ---------------- scoring ----------------

_WORD_SPLIT = re.compile(r"[^\w]+")

def _tokenize(s: str) -> List[str]:
    return [w for w in _WORD_SPLIT.split((s or "").lower()) if w]

def _score_candidate(
    *,
    word: str,
    gloss: str,
    title: str,
    desc: str,
    categories: str,
    mime: str,
    allow_people: bool,
    prefer_animals: bool,
) -> float:
    """
    Higher is better.
    """
    score = 0.0
    tks_title = set(_tokenize(title))
    tks_desc  = set(_tokenize(desc))
    tks_cats  = set(_tokenize(categories))
    tks_all   = tks_title | tks_desc | tks_cats

    # Must be an actual raster image
    if not (mime and mime.startswith("image/")) or (mime in BAD_MIME):
        return -100.0

    # hard negatives
    if _looks_like_always_bad(title, categories, mime):
        return -50.0

    if not allow_people and _looks_like_people(title, categories):
        score -= 10.0

    # positive matching on the query and gloss
    for tok in _tokenize(word)[:3]:
        if tok and tok in tks_all:
            score += 4.0
        if tok and tok in tks_title:
            score += 3.0
    for tok in _tokenize(gloss)[:3]:
        if tok and tok in tks_all:
            score += 2.0

    # animal preference: require animalish hints to pass a minimum
    if prefer_animals:
        if any(cat.lower() in categories.lower() for cat in ANIMALISH_CATS):
            score += 5.0
        else:
            score -= 8.0  # strongly demote non-animal results for animal contexts

    # Special nudges for common ambiguous words like "fish", "turtle"
    key = word.lower().strip()
    for hint in ANIMAL_KEY_HINTS.get(key, ()):
        if hint in tks_title or hint in tks_cats:
            score += 3.0

    # reward descriptive titles over codes/abstracts
    if re.search(r"\d{5,}", title):
        score -= 1.5
    if any(k in tks_title for k in ("closeup", "macro", "texture", "pattern", "background")):
        score -= 3.0

    return score

# --------------- core helpers ---------------

def _query(params: Dict[str, str]) -> Dict:
    r = SESSION.get(API, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def _extract_from_pages(
    pages: Dict[str, Dict[str, object]],
    limit: int,
    *,
    allow_people: bool,
    prefer_animals: bool,
    word: str,
    gloss: str,
) -> List[Dict[str, str]]:
    candidates: List[Tuple[float, Dict[str, str]]] = []
    seen_urls: set[str] = set()

    for page in pages.values():
        if not isinstance(page, dict):
            continue

        title = str(page.get("title") or "")
        infos = page.get("imageinfo") or []
        if not infos or not isinstance(infos, list):
            continue
        info = infos[0] if isinstance(infos[0], dict) else {}
        url  = info.get("url")
        mime = info.get("mime", "")
        if not url or url in seen_urls:
            continue

        # categories from prop=categories plus any extmetadata we get
        categories_text = ""
        if "categories" in page and isinstance(page["categories"], list):
            categories_text = " ".join([c.get("title","") for c in page["categories"] if isinstance(c, dict)])
        meta = info.get("extmetadata") or {}
        categories_text += " " + (meta.get("Categories") or {}).get("value", "")

        # description for extra signal
        description_html = (meta.get("ImageDescription") or {}).get("value", "")
        description_text = _strip_tags(description_html)

        # score it
        s = _score_candidate(
            word=word, gloss=gloss, title=title, desc=description_text,
            categories=categories_text, mime=mime,
            allow_people=allow_people, prefer_animals=prefer_animals,
        )
        if s < -20:
            continue  # hopeless

        thumb = info.get("thumburl") or url
        artist  = (meta.get("Artist") or {}).get("value", "")
        credit  = (meta.get("Credit") or {}).get("value", "")
        license_short = (meta.get("LicenseShortName") or {}).get("value", "")
        attribution_html = artist or credit or "Wikimedia Commons"

        candidates.append((
            s,
            {
                "url": url,
                "thumb": thumb or url,
                "source": "Wikimedia",
                "attribution": attribution_html,
                "attribution_text": _strip_tags(attribution_html),
                "license": license_short,
                # for debugging/ranking introspection (optional; remove if you prefer)
                # "score": s,
                # "title": title,
            }
        ))
        seen_urls.add(url)

    # sort by score, then prefer larger thumbs implicitly (thumburl is baked by iiurlwidth)
    candidates.sort(key=lambda x: x[0], reverse=True)
    return [c[1] for c in candidates[:limit]]

# --------------- main API -------------------

@lru_cache(maxsize=4096)
def _build_search_query(word: str, gloss: str, *, allow_people: bool, prefer_animals: bool) -> str:
    """Build a Cirrus search query string (cached)."""
    negatives = "-icon -svg -heraldry -coat -arms -map -diagram -clipart -pictogram -infographic -statue -sculpture -toy -logo -texture -tile -tiled -mosaic -pattern -background -wallpaper -fabric -collage -abstract"
    negatives_people = "" if allow_people else " -portrait -person -headshot -self-portrait -human"
    incat = ' incategory:"Animals"' if prefer_animals else ""
    positive_terms = f"{word} {gloss}".strip()
    return f'filetype:bitmap {positive_terms} {negatives}{negatives_people}{incat}'.strip()

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
    - negative filters for icons/heraldry/statues/textures/etc,
    - optional people filtering (skipped if allow_people or context suggests people),
    - optional animal preference when context suggests animals,
    - candidate scoring to surface true photographs of the concept.
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

    # Build query once
    base_query = _build_search_query(word, gloss, allow_people=allow_people, prefer_animals=prefer_animals)

    try:
        # Primary: generator=search with categories + imageinfo
        params = {
            "action": "query",
            "format": "json",
            "prop": "imageinfo|categories",
            "generator": "search",
            "gsrsearch": base_query,
            "gsrnamespace": 6,
            # over-fetch: we score and then take top N
            "gsrlimit": max(limit * 14, 40),
            "iiprop": "url|mime|extmetadata",
            "iiurlwidth": 768,  # larger thumbs; same request cost
            "redirects": 1,
            "clshow": "!hidden",
            "cllimit": 50,
        }
        data = _query(params)
        pages = (data.get("query") or {}).get("pages") or {}
        results = _extract_from_pages(
            pages if isinstance(pages, dict) else {}, limit,
            allow_people=allow_people, prefer_animals=prefer_animals,
            word=word, gloss=gloss,
        )
        if results:
            return results

        # Fallback A: gloss only (retain context)
        if gloss:
            params["gsrsearch"] = _build_search_query(gloss, "", allow_people=allow_people, prefer_animals=prefer_animals)
            data = _query(params)
            pages = (data.get("query") or {}).get("pages") or {}
            results = _extract_from_pages(
                pages if isinstance(pages, dict) else {}, limit,
                allow_people=allow_people, prefer_animals=prefer_animals,
                word=gloss, gloss="",
            )
            if results:
                return results

        # Fallback B: drop category constraints but keep filters & scoring
        del params["clshow"]; del params["cllimit"]
        params["prop"] = "imageinfo"
        params["gsrsearch"] = _build_search_query(word, gloss, allow_people=allow_people, prefer_animals=False)
        data = _query(params)
        pages = (data.get("query") or {}).get("pages") or {}
        results = _extract_from_pages(
            pages if isinstance(pages, dict) else {}, limit,
            allow_people=allow_people, prefer_animals=False,
            word=word, gloss=gloss,
        )
        return results
    except Exception as e:
        logger.warning("Wikimedia search failed for %r: %s", word, e)
        return []
