"""Licence-safe cover photos.

Order: Wikimedia Commons (named people, companies, places, CC/PD only)
       -> Pixabay (generic scenes, free commercial licence)
       -> no photo (template falls back to a branded gradient).
Every photo carries a credit line that goes into the caption and onto the cover.
"""
import io
import logging
import re
from dataclasses import dataclass

import requests
from PIL import Image

from .config import USER_AGENT, settings
from .sources import strip_html

log = logging.getLogger(__name__)

ALLOWED_LICENCES = ("cc0", "public domain", "pd", "cc by")  # "cc by" also covers CC BY-SA
STOPWORDS = {"the", "and", "of", "for", "inc", "ltd", "group", "company", "corp"}


@dataclass
class Photo:
    data: bytes  # normalised JPEG
    credit: str
    source: str


def _normalise(raw: bytes) -> bytes:
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.thumbnail((1800, 1800))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _download(url: str, headers: dict | None = None) -> bytes | None:
    try:
        r = requests.get(url, headers=headers or {"User-Agent": USER_AGENT}, timeout=30)
        r.raise_for_status()
        return r.content
    except Exception as e:
        log.warning("image download failed %s: %s", url, e)
        return None


def wikimedia(query: str) -> Photo | None:
    if not query:
        return None
    # The file title must mention a real word from the query, so we never put the wrong face on a story.
    keywords = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 3 and w not in STOPWORDS]
    if not keywords:
        return None
    try:
        r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": f"{query} filetype:bitmap",
                "gsrnamespace": 6,
                "gsrlimit": 12,
                "prop": "imageinfo",
                "iiprop": "url|size|mime|extmetadata",
                "iiurlwidth": 1600,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=20,
        )
        pages = sorted(r.json().get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    except Exception as e:
        log.warning("wikimedia search failed: %s", e)
        return None

    for page in pages:
        title = page.get("title", "").lower()
        if not any(k in title for k in keywords):
            continue
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("mime") not in ("image/jpeg", "image/png") or info.get("width", 0) < 900:
            continue
        meta = info.get("extmetadata", {})
        licence = meta.get("LicenseShortName", {}).get("value", "")
        if not licence.lower().startswith(ALLOWED_LICENCES):
            continue
        raw = _download(info.get("thumburl") or info.get("url"))
        if not raw:
            continue
        artist = strip_html(meta.get("Artist", {}).get("value", "")) or "Unknown"
        credit = f"Photo: {artist[:60]} / Wikimedia Commons, {licence}"
        return Photo(_normalise(raw), credit, "wikimedia")
    return None


def pixabay(query: str) -> Photo | None:
    """Pixabay Content License: free commercial use, no attribution required (we credit anyway).
    Their API terms forbid hotlinking, so we download and re-host, which is what we do."""
    if not query or not settings.pixabay_api_key:
        return None
    try:
        r = requests.get(
            "https://pixabay.com/api/",
            params={
                "key": settings.pixabay_api_key,
                "q": query[:100],
                "image_type": "photo",
                "orientation": "vertical",
                "safesearch": "true",
                "min_width": 1080,
                "per_page": 5,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=20,
        )
        hits = r.json().get("hits", [])
    except Exception as e:
        log.warning("pixabay search failed: %s", e)
        return None
    for h in hits:
        raw = _download(h.get("largeImageURL", ""))
        if raw:
            return Photo(_normalise(raw), f"Photo: {h.get('user', 'Pixabay')} / Pixabay", "pixabay")
    return None


def find_photo(entity_query: str, scene_query: str) -> Photo | None:
    photo = wikimedia(entity_query) or pixabay(scene_query)
    log.info("cover photo: %s", photo.source if photo else "none, using gradient")
    return photo
