"""
Cover image cache.

Caches cover images on disk to avoid repeatedly extracting from CBZ archives
or fetching from ComicVine. Covers are stored as JPEG files in COVER_CACHE_DIR.

Two types of cached covers:
- Comic covers:    cover_cache/<uuid>.jpg   (extracted from CBZ)
- ComicVine covers: cover_cache/cv_<issue_id>_<url_hash>.jpg  (downloaded from CV)
"""

import hashlib
import logging
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

from django.conf import settings

logger = logging.getLogger(__name__)

COVER_CACHE_DIR = Path(getattr(settings, "COVER_CACHE_DIR", "/app/cover_cache"))


def _ensure_cache_dir():
    COVER_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_comic_cover(comic) -> bytes | None:
    """
    Get cover image for an owned comic. Returns cached version if available,
    otherwise extracts from CBZ and caches it.
    """
    cache_path = COVER_CACHE_DIR / f"{comic.pk}.jpg"

    # Return from cache
    if cache_path.exists():
        return cache_path.read_bytes()

    # Extract from CBZ and cache
    if not comic.file_path:
        return None

    from apps.scraper.hasher import extract_cover_image
    cover_data = extract_cover_image(comic.file_path)
    if not cover_data:
        return None

    try:
        _ensure_cache_dir()
        cache_path.write_bytes(cover_data)
    except OSError as e:
        logger.warning("Failed to cache cover for %s: %s", comic.pk, e)

    return cover_data


def get_comic_thumb(comic, width: int = 80) -> bytes | None:
    """
    Get a small thumbnail for list display. Cached as {pk}_thumb.jpg.
    Falls back to full cover if PIL resize fails.
    """
    cache_path = COVER_CACHE_DIR / f"{comic.pk}_thumb.jpg"
    if cache_path.exists():
        return cache_path.read_bytes()

    cover_data = get_comic_cover(comic)
    if not cover_data:
        return None

    try:
        from io import BytesIO
        from PIL import Image
        img = Image.open(BytesIO(cover_data)).convert("RGB")
        h = int(img.height * width / img.width)
        img = img.resize((width, h), Image.LANCZOS)
        out = BytesIO()
        img.save(out, format="JPEG", quality=70, optimize=True)
        thumb_data = out.getvalue()
    except Exception as e:
        logger.warning("Failed to generate thumb for %s: %s", comic.pk, e)
        return cover_data

    try:
        _ensure_cache_dir()
        cache_path.write_bytes(thumb_data)
    except OSError as e:
        logger.warning("Failed to cache thumb for %s: %s", comic.pk, e)

    return thumb_data


def get_comic_page(comic, page_index: int) -> bytes | None:
    """
    Get image for a specific page of an owned comic.
    Caches the page image to avoid repeatedly extracting from CBZ.
    """
    if page_index == 0:
        return get_comic_cover(comic)
        
    cache_path = COVER_CACHE_DIR / f"{comic.pk}_p{page_index}.jpg"

    # Return from cache
    if cache_path.exists():
        return cache_path.read_bytes()

    # Extract from CBZ and cache
    if not comic.file_path:
        return None

    from apps.scraper.hasher import extract_comic_page
    page_data = extract_comic_page(comic.file_path, page_index)
    if not page_data:
        return None

    try:
        _ensure_cache_dir()
        cache_path.write_bytes(page_data)
    except OSError as e:
        logger.warning("Failed to cache page %s for %s: %s", page_index, comic.pk, e)

    return page_data


def get_cv_cover(issue_id: int, cover_url: str) -> bytes | None:
    """
    Get cover image for a ComicVine issue. Returns cached version if available,
    otherwise downloads from the URL and caches it.

    Cache key includes a short hash of the URL so different variant covers for
    the same issue are stored as separate files.
    """
    url_hash = hashlib.md5(cover_url.encode()).hexdigest()[:8] if cover_url else "none"
    cache_path = COVER_CACHE_DIR / f"cv_{issue_id}_{url_hash}.jpg"

    # Return from cache
    if cache_path.exists():
        return cache_path.read_bytes()

    # Download and cache
    if not cover_url:
        return None

    try:
        req = Request(cover_url, headers={"User-Agent": "ComicManager/1.0"})
        with urlopen(req, timeout=10) as resp:
            cover_data = resp.read()
    except (URLError, OSError, TimeoutError) as e:
        logger.warning("Failed to download CV cover %s: %s", issue_id, e)
        return None

    if not cover_data:
        return None

    try:
        _ensure_cache_dir()
        cache_path.write_bytes(cover_data)
    except OSError as e:
        logger.warning("Failed to cache CV cover %s: %s", issue_id, e)

    return cover_data


def has_cv_cover_cached(issue_id: int, cover_url: str = "") -> bool:
    """Check if a ComicVine cover is already cached locally."""
    url_hash = hashlib.md5(cover_url.encode()).hexdigest()[:8] if cover_url else "none"
    return (COVER_CACHE_DIR / f"cv_{issue_id}_{url_hash}.jpg").exists()


def get_inducks_cover(issuecode: str, cover_url: str) -> bytes | None:
    """
    Get cover image for an Inducks issue. Returns cached version if available,
    otherwise downloads from the inducks.org cover viewer URL and caches it.

    Uses HTTP Basic Auth with credentials from the inducks_username/password
    settings (inducks.org requires login to serve images).
    """
    import base64
    from apps.core.models import get_setting

    safe_code = issuecode.replace("/", "_").replace(" ", "_")
    cache_path = COVER_CACHE_DIR / f"inducks_{safe_code}.jpg"

    if cache_path.exists():
        return cache_path.read_bytes()

    if not cover_url:
        return None

    username = get_setting("inducks_username", "")
    password = get_setting("inducks_password", "")

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:137.0) Gecko/20100101 Firefox/137.0",
    }
    if username and password:
        credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {credentials}"

    try:
        req = Request(cover_url, headers=headers)
        with urlopen(req, timeout=15) as resp:
            cover_data = resp.read()
    except (URLError, OSError, TimeoutError) as e:
        logger.warning("Failed to download Inducks cover %s: %s", issuecode, e)
        return None

    if not cover_data:
        return None

    try:
        _ensure_cache_dir()
        cache_path.write_bytes(cover_data)
    except OSError as e:
        logger.warning("Failed to cache Inducks cover %s: %s", issuecode, e)

    return cover_data


def cache_physical_cover(comic_pk, cover_url: str) -> bool:
    """Download and cache a cover image for a physical comic from a URL."""
    if not cover_url:
        return False
    cache_path = COVER_CACHE_DIR / f"{comic_pk}.jpg"
    try:
        req = Request(cover_url, headers={"User-Agent": "ComicManager/1.0"})
        with urlopen(req, timeout=10) as resp:
            cover_data = resp.read()
    except (URLError, OSError, TimeoutError) as e:
        logger.warning("Failed to download cover for physical %s: %s", comic_pk, e)
        return False
    if not cover_data:
        return False
    try:
        _ensure_cache_dir()
        cache_path.write_bytes(cover_data)
    except OSError as e:
        logger.warning("Failed to cache cover for physical %s: %s", comic_pk, e)
        return False
    return True


def invalidate_comic_cover(comic_pk) -> None:
    """Remove cached cover and thumbnail for a comic (e.g. after re-scrape or file change)."""
    (COVER_CACHE_DIR / f"{comic_pk}.jpg").unlink(missing_ok=True)
    (COVER_CACHE_DIR / f"{comic_pk}_thumb.jpg").unlink(missing_ok=True)


def invalidate_comic_pages(comic_pk) -> None:
    """Remove all cached page images for a comic (cover + all page thumbnails)."""
    invalidate_comic_cover(comic_pk)
    for path in COVER_CACHE_DIR.glob(f"{comic_pk}_p*.jpg"):
        path.unlink(missing_ok=True)
