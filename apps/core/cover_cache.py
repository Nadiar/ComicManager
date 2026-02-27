"""
Cover image cache.

Caches cover images on disk to avoid repeatedly extracting from CBZ archives
or fetching from ComicVine. Covers are stored as JPEG files in COVER_CACHE_DIR.

Two types of cached covers:
- Comic covers:    cover_cache/<uuid>.jpg   (extracted from CBZ)
- ComicVine covers: cover_cache/cv_<issue_id>.jpg  (downloaded from CV)
"""

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
    """
    cache_path = COVER_CACHE_DIR / f"cv_{issue_id}.jpg"

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


def has_cv_cover_cached(issue_id: int) -> bool:
    """Check if a ComicVine cover is already cached locally."""
    return (COVER_CACHE_DIR / f"cv_{issue_id}.jpg").exists()


def invalidate_comic_cover(comic_pk) -> None:
    """Remove cached cover for a comic (e.g. after re-scrape or file change)."""
    cache_path = COVER_CACHE_DIR / f"{comic_pk}.jpg"
    cache_path.unlink(missing_ok=True)


def invalidate_comic_pages(comic_pk) -> None:
    """Remove all cached page images for a comic (cover + all page thumbnails)."""
    invalidate_comic_cover(comic_pk)
    for path in COVER_CACHE_DIR.glob(f"{comic_pk}_p*.jpg"):
        path.unlink(missing_ok=True)
