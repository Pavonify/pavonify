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
UA = "Pavonify/1.1 (https://www.pavonify.com; admin@pavonify.com)"
TIMEOUT = 12

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})

PIXABAY_API = "https://pixabay.com/api/"
PIXABAY_KEY = os.getenv("PIXABAY_KEY", "").strip()

# ---------- heuristics & helpers ----------

_TAGS = re.compile(r"<[^>]+>")

BAD_MIME = ("image/svg+xml",)  # icons/logos
ALWAYS_BAD_WORDS = (
    "logo", "icon", "emblem", "symbol",
    "heraldry", "coat_of_arms", "coat-of-arms", "coat of arms",
    "map", "diagram", "chart", "graph",
    "clipart", "clip-art", "pictogram", "infographic",
    "statue", "sculpture", "bust", "figurine", "toy",
    "tank", "ship", "warship", "destroyer", "battleship", "submarine",
    "insignia", "badge", "stamp", "postage",
    "painting", "drawing", "sketch", "engraving", "woodcut", "lithograph",
)

ALWAYS_BAD_CATS = (
    "Logos", "Icons", "Heraldry", "Coats of arms",
    "Maps", "Diagrams", "Charts", "Graphs",
    "Clip art", "Pictograms", "Infographics",
    "Statues", "Sculptures", "Busts", "Toys",
    "Ships", "Warships", "Tanks", "Military vehicles",
    "Paintings", "Drawings", "Sketches", "Engravings", "Lithographs",
)

PEOPLE_WORDS = (
    "portrait", "headshot", "self-portrait", "selfportrait",
    "person", "people", "man", "woman", "boy", "girl", "human",
    "celebrity", "actor", "actress",
)
PEOPLE_CATS  = ("Portraits", "People", "Men", "Women", "Self-portraits", "Celebrities")

ANIMALISH_CATS = (
    "Animals", "Mammals", "Birds", "Fish", "Fishes", "Reptiles", "Amphibians",
    "Insects", "Arachnids", "Wildlife", "Fauna", "Felines", "Canines", "Cetaceans",
)
# Helps catch taxonomic families on Commons (Felidae, Aves, Pisces, etc.)
ANIMALISH_TOKEN = re.compile(
    r"\b(animals?|wildlife|mammals?|aves|birds?|pisces|fish|fishes|reptiles?|amphibians?|insects?|arachnids?|fauna|felidae|canidae|panthera|equidae|chelonia|testudines)\b",
    re.I,
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
    if any(cat.lower() in c for cat in PEOPLE_CATS): return True
    # "Firstname_Lastname" or "Lastname,_Firstname" often indicate people
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

# ---------- scoring & extraction ----------

def _score_candidate(*, title: str, categories: str, mime: str, prefer_animals: bool, allow_people: bool, keywords: Tuple[str, ...]) -> int:
    """
    Positive scores for animal photographs; negative for drawings/people/objects.
    """
    score = 0
    t = (title or "")
    tl = t.lower()
    c = (categories or "")
    cl = c.lower()

    # exact text hits
    for kw in keywords:
        if kw and kw.lower() in tl:
            score += 2

    # prefer photos (Commons often tags photographs)
    if "photographs" in cl or "photography" in cl:
        score += 3

    # animal-ish categories
    if prefer_animals and (ANIMALISH_TOKEN.search(cl) or any(cat.lower() in cl for cat in ANIMALISH_CATS)):
        score += 4

    # penalize drawings/paintings etc.
    if any(w in tl for w in ("painting","drawing","sketch","engraving","woodcut","lithograph")):
        score -= 5
    if any(cat.lower() in cl for cat in (x.lower() for x in ("Paintings","Drawings","Sketches","Engravings","Lithographs"))):
        score -= 5

    # people penalty (unless explicitly allowed)
    if not allow_people and _looks_like_people(t, c):
        score -= 6

    # drop non-photo-ish mimes
    if mime and mime not in ("image/jpeg", "image/png", "image/gif", "image/webp", "image/tiff"):
        score -= 4

    return score

def _extract_ranked(
    pages: Dict[str, Dict[str, object]],
    limit: int,
    *,
    allow_people: bool,
    prefer_animals: bool,
    keywords: Tuple[str, ...],
) -> List[Dict[str, str]]:
    candidates = []
    seen_urls: set[str] = set()

    for page in (pages or {}).values():
        if not isinstance(page, dict):
            continue
        title = page.get("title") or ""
        infos = page.get("imageinfo") or []
        if not infos or not isinstance(infos, list):
            continue

        info = infos[0] if isinstance(infos[0], dict) else {}
        url  = info.get("url")
        mime = info.get("mime", "")
        if not url or url in seen_urls:
            continue

        # categories from prop=categories + extmetadata
        categories_text = ""
        if "categories" in page and isinstance(page["categories"], list):
            categories_text = " ".join([c.get("title","") for c in page["categories"] if isinstance(c, dict)])
        meta = info.get("extmetadata") or {}
        categories_text += " " + (meta.get("Categories") or {}).get("value", "")

        # global bad filters first
        if _looks_like_always_bad(title, categories_text, mime):
            continue
        if not allow_people and _looks_like_people(title, categories_text):
            continue

        score = _score_candidate(
            title=title, categories=categories_text, mime=mime,
            prefer_animals=prefer_animals, allow_people=allow_people,
            keywords=keywords,
        )

        # soft floor to discard very dubious matches
        if score < -1:
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

    # sort by score desc, keep unique
    candidates.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in candidates[:limit]]

# ---------- Pixabay fallback ----------

def _pixabay_search(query: str, limit: int, *, prefer_animals: bool) -> List[Dict[str, str]]:
    if not PIXABAY_KEY:
        return []

    params = {
        "key": PIXABAY_KEY,
        "q": query,
        "image_type": "photo",
        "safesearch": "true",
        "orientation": "horizontal",
        "per_page": max(10, limit * 3),
        "order": "popular",
        "category": "animals" if prefer_animals else "",
        # note: Pixabay handles pluralization/english terms well
    }
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
    context_hint: Optional[str] = None,    # e.g. "Animals", "Family members"
    allow_people: Optional[bool] = None,   # override people filter per-call
) -> List[Dict[str, str]]:
    """
    Try Wikimedia first (tight filters + scoring). If not enough good matches,
    fall back to Pixabay (photo-only) automatically.
    """
    if not word:
        return []
    limit = max(int(limit), 1)

    # context classification
    ctx = _classify_context(context_hint)
    prefer_animals = ctx["prefer_animals"]
    prefer_people  = ctx["prefer_people"]
    allow_people = bool(allow_people) or prefer_people

    # Build a stricter Commons query:
    # - Restrict to *file* namespace.
    # - Require bitmap photos.
    # - Prefer page *titles* containing the word.
    # - Bias to animal categories when appropriate.
    gloss = (source_word or "").strip()
    keywords = tuple(k for k in {word, gloss} if k)

    negatives_common = "-icon -svg -heraldry -coat -arms -map -diagram -chart -graph -clipart -pictogram -statue -sculpture -toy -logo -painting -drawing -sketch -engraving -lithograph -ship -tank"
    negatives_people = "" if allow_people else " -portrait -person -headshot -self-portrait -human"

    incat = ' incategory:"Animals"' if prefer_animals else ""
    # 'intitle:' pushes the actual animal name in filename
    base_query = f'filetype:bitmap intitle:{word} {gloss} {negatives_common}{negatives_people}{incat}'.strip()

    try:
        params = {
            "action": "query",
            "format": "json",
            "prop": "imageinfo|categories",
            "generator": "search",
            "gsrsearch": base_query,
            "gsrnamespace": 6,
            "gsrlimit": max(limit * 20, 50),  # fetch plenty; we'll score
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
            allow_people=allow_people,
            prefer_animals=prefer_animals,
            keywords=keywords,
        )

        # If Wikimedia looks weak (none or clearly too few), use Pixabay.
        if len(results) < limit:
            # 1) Try again using just the gloss (sometimes works better)
            if gloss:
                params["gsrsearch"] = f'filetype:bitmap intitle:{gloss} {negatives_common}{negatives_people}{incat}'.strip()
                data = _query(params)
                pages = (data.get("query") or {}).get("pages") or {}
                extra = _extract_ranked(
                    pages if isinstance(pages, dict) else {},
                    limit - len(results),
                    allow_people=allow_people,
                    prefer_animals=prefer_animals,
                    keywords=keywords,
                )
                results.extend(extra)

        # Final guard: if still short, Pixabay fallback.
        if len(results) < limit:
            # Prefer the more "animal-ish" of (word, gloss) for Pixabay query.
            pixabay_q = gloss or word
            results.extend(_pixabay_search(pixabay_q, limit - len(results), prefer_animals=prefer_animals))

        # If absolutely nothing, return empty list (caller can handle a default image)
        return results[:limit]
    except Exception as e:
        logger.warning("Wikimedia search failed for %r: %s", word, e)
        # Network or API failure? Try Pixabay directly.
        fb = _pixabay_search(gloss or word, limit, prefer_animals=prefer_animals)
        return fb[:limit]
