"""
Core Services.

Business logic for the core app, extracted for reuse across views and commands.
"""

import os
import re
import zipfile
from pathlib import Path

from django.conf import settings

from .models import Comic


def scan_untagged_folder(path: str = None, dry_run: bool = False, cleanup: bool = True) -> dict:
    """
    Scan the untagged folder for new comics and import them into the database.

    Args:
        path: Override path to scan (default: UNTAGGED_DIR from settings)
        dry_run: If True, don't actually import anything
        cleanup: If True, remove comics whose files no longer exist

    Returns:
        dict with results: imported, skipped, cleaned, errors
    """
    untagged_path = path or getattr(settings, "UNTAGGED_DIR", "/comics/untagged")

    if not os.path.exists(untagged_path):
        return {
            "success": False,
            "error": f"Untagged path does not exist: {untagged_path}",
            "imported": 0,
            "skipped": 0,
            "cleaned": 0,
            "errors": [],
        }

    result = {
        "success": True,
        "imported": 0,
        "skipped": 0,
        "cleaned": 0,
        "errors": [],
        "dry_run": dry_run,
    }

    # Cleanup: remove comics whose files no longer exist
    if cleanup and not dry_run:
        result["cleaned"] = _cleanup_missing_files(untagged_path)

    # Find all comic files
    extensions = (".cbz", ".cbr", ".cb7", ".pdf")
    comic_files = []
    for ext in extensions:
        comic_files.extend(Path(untagged_path).rglob(f"*{ext}"))

    for file_path in comic_files:
        file_path_str = str(file_path)

        # Check if already imported
        if Comic.objects.filter(file_path=file_path_str).exists():
            result["skipped"] += 1
            continue

        try:
            # Parse filename for proposed metadata
            parsed = _parse_filename(file_path.stem)

            # Get file info
            file_stat = file_path.stat()
            file_format = file_path.suffix.lower().lstrip(".")

            # Extract page count for CBZ files
            page_count = None
            if file_format == "cbz":
                page_count = _get_cbz_page_count(file_path)

            # Detect flags for review queue
            flags = _detect_flags(
                file_format=file_format,
                page_count=page_count,
                filename=file_path.name,
                parsed=parsed,
            )

            comic_data = {
                "file_path": file_path_str,
                "file_format": file_format,
                "file_size": file_stat.st_size,
                "page_count": page_count,
                "state": Comic.STATE_NEW,
                "medium": Comic.MEDIUM_DIGITAL,
                "proposed_series": parsed.get("series"),
                "proposed_number": parsed.get("number"),
                "proposed_volume": parsed.get("volume"),
                "proposed_year": parsed.get("year"),
                "flags": flags,
            }

            if not dry_run:
                Comic.objects.create(**comic_data)

            result["imported"] += 1

        except Exception as e:
            result["errors"].append(f"{file_path.name}: {str(e)}")

    return result


def _cleanup_missing_files(untagged_path: str) -> int:
    """Remove comics from database whose files no longer exist on disk."""
    untagged_comics = Comic.objects.filter(
        file_path__startswith=untagged_path,
        medium=Comic.MEDIUM_DIGITAL,
    )

    removed = 0
    for comic in untagged_comics:
        if not os.path.exists(comic.file_path):
            comic.delete()
            removed += 1

    return removed


def _parse_filename(filename: str) -> dict:
    """
    Parse comic filename to extract series, number, volume, and year.

    Handles common patterns like:
    - "Detective Comics 1094 (2025) (Digital) (PyrateGoneKiwi)"
    - "Batman #050 (2018)"
    - "Amazing Spider-Man v2 #001 (1999)"
    - "X-Men (2021) 001"
    """
    result = {
        "series": None,
        "number": None,
        "volume": None,
        "year": None,
    }

    clean_name = filename

    # First extract year from parentheses - (2025), (2021), etc.
    year_match = re.search(r'\((\d{4})\)', clean_name)
    if year_match:
        result["year"] = int(year_match.group(1))

    # Remove ALL parenthesized content (year, Digital, scanner names, etc.)
    clean_name = re.sub(r'\s*\([^)]*\)', '', clean_name).strip()

    # Extract volume - v2, Vol. 3, Volume 4
    vol_match = re.search(r'\b[vV](?:ol(?:ume)?\.?\s*)?(\d+)\b', clean_name)
    if vol_match:
        result["volume"] = int(vol_match.group(1))
        clean_name = re.sub(r'\b[vV](?:ol(?:ume)?\.?\s*)?\d+\b', '', clean_name).strip()

    # Extract issue number - multiple patterns
    # Try hash format first: #001, #1, #12.1
    num_match = re.search(r'#(\d+(?:\.\d+)?)', clean_name)
    if num_match:
        result["number"] = num_match.group(1).lstrip("0") or "0"
        clean_name = clean_name.replace(num_match.group(0), "").strip()
    else:
        # Try trailing number (most common): "Catwoman 061", "Batman Beyond - Neo-Gothic 006"
        num_match = re.search(r'\s+(\d{2,4})\s*$', clean_name)
        if num_match:
            result["number"] = num_match.group(1).lstrip("0") or "0"
            clean_name = clean_name[:num_match.start()].strip()
        else:
            # Try single digit or decimal: "Issue 5", "Batman 1.5"
            num_match = re.search(r'\s+(\d+(?:\.\d+)?)\s*$', clean_name)
            if num_match:
                result["number"] = num_match.group(1).lstrip("0") or "0"
                clean_name = clean_name[:num_match.start()].strip()

    # What's left is the series name
    series = clean_name.strip()
    # Clean up extra spaces
    series = re.sub(r'\s+', ' ', series)
    # Remove trailing dashes or hyphens (but preserve internal ones like "Spider-Man")
    series = re.sub(r'\s*-\s*$', '', series)
    series = re.sub(r'\s+-$', '', series)

    if series:
        result["series"] = series

    return result


def _get_cbz_page_count(cbz_path: Path) -> int | None:
    """Count image files inside a CBZ archive."""
    try:
        with zipfile.ZipFile(cbz_path, "r") as zf:
            image_extensions = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
            count = sum(
                1 for name in zf.namelist()
                if name.lower().endswith(image_extensions)
                and not name.startswith("__MACOSX")
                and not name.startswith(".")
            )
            return count if count > 0 else None
    except zipfile.BadZipFile:
        return None


def _detect_flags(file_format: str, page_count: int | None, filename: str, parsed: dict) -> dict:
    """
    Detect issues that need user review.

    Flags:
    - low_page_count: Less than 5 pages (configurable)
    - is_pdf: PDF files need manual review
    - no_series: Couldn't parse series name from filename
    - cover_only: Likely just a cover (≤3 pages + "cover" in filename)
    - needs_conversion: CBR/CB7 files need conversion to CBZ
    """
    flags = {}
    filename_lower = filename.lower()

    # Low page count (default threshold: 5)
    min_pages = 5
    if page_count is not None and page_count < min_pages:
        flags["low_page_count"] = True

    # PDF files need review
    if file_format == "pdf":
        flags["is_pdf"] = True

    # No series could be parsed
    if not parsed.get("series"):
        flags["no_series"] = True

    # Cover-only files (≤3 pages and "cover" in filename)
    cover_threshold = 3
    if page_count is not None and page_count <= cover_threshold:
        if "cover" in filename_lower:
            flags["cover_only"] = True

    # Needs conversion (CBR, CB7)
    if file_format in ("cbr", "cb7"):
        flags["needs_conversion"] = True

    return flags


# Format patterns for auto-detection (shared between views and tasks)
FORMAT_PATTERNS = [
    (r"\bTPB\b|\bTrade Paperback\b", "TPB"),
    (r"\bHC\b|\bHardcover\b", "HC"),
    (r"\bAnnual\b", "Annual"),
    (r"\bSpecial\b", "Special"),
    (r"\bOne[- ]?Shot\b", "One-Shot"),
    (r"\bGiant[- ]?Size\b", "Giant-Size"),
    (r"\bKing[- ]?Size\b", "King-Size"),
    (r"\bOmnibus\b", "Omnibus"),
    (r"\bDeluxe\b", "Deluxe"),
    (r"\bDirector'?s Cut\b", "Director's Cut"),
]


def detect_format(comic) -> str | None:
    """
    Auto-detect comic format from series name, title, or issue count.

    Detection priority:
    1. Special formats (TPB, HC, Omnibus, etc.) from series/title text
    2. Classify by issue count: One-Shot, Limited Series, Main Series
    """
    from .models import get_setting

    text_to_check = f"{comic.series or ''} {comic.title or ''}"

    for pattern, format_name in FORMAT_PATTERNS:
        if re.search(pattern, text_to_check, re.IGNORECASE):
            return format_name

    if comic.count is not None:
        one_shot_max = get_setting("one_shot_max_count", 1)
        limited_max = get_setting("limited_series_max_count", 15)

        if comic.count <= one_shot_max:
            return "One-Shot"
        elif comic.count <= limited_max:
            return "Limited Series"
        else:
            return "Main Series"

    return None


def detect_and_set_format(comic) -> dict:
    """
    Detect format and apply it to a comic. Advances state to formatted.

    Returns dict with detection results for reporting.
    """
    old_format = comic.format
    detected = detect_format(comic)

    if detected:
        comic.format = detected

    if comic.state in (Comic.STATE_NEW, Comic.STATE_IMPORTED, Comic.STATE_SCRAPED,
                       Comic.STATE_COUNTED, Comic.STATE_TAGGED):
        comic.state = Comic.STATE_FORMATTED

    comic.needs_reformat = False
    comic.save()

    return {
        "success": True,
        "old_format": old_format,
        "new_format": comic.format,
        "detected_format": detected,
        "format_changed": old_format != comic.format,
    }
