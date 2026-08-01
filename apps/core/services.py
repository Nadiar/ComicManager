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

    # Cleanup: drop untouched comics whose files are gone, flag the rest
    if cleanup and not dry_run:
        missing = check_missing_files(untagged_path)
        result["cleaned"] = missing["removed"]
        result["flagged_missing"] = missing["flagged"]
        if missing["skipped"]:
            result["errors"].append(missing["reason"])

    # Find all comic files
    extensions = (".cbz", ".cbr", ".cb7", ".pdf", ".zip")
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
            is_corrupted = False
            if file_format == "cbz":
                page_count, is_corrupted = _get_cbz_page_count(file_path)

            # Detect flags for review queue
            flags = _detect_flags(
                file_format=file_format,
                page_count=page_count,
                filename=file_path.name,
                parsed=parsed,
                is_corrupted=is_corrupted,
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


# Above this share of missing files the folder is assumed to be unmounted or
# being moved, and nothing is changed.
MISSING_FILES_ABORT_RATIO = 0.5
MISSING_FILES_ABORT_MIN = 10


def check_missing_files(untagged_path: str, dry_run: bool = False) -> dict:
    """
    Handle comics under the untagged folder whose files are gone.

    Only untouched comics (state 'new') are removed from the database. Comics
    further along keep their record and get a file_missing flag, so scraped
    and hand-edited metadata is never lost; the flag clears itself when the
    file is back. If the folder looks unmounted (it is empty, or most files
    are missing) nothing is changed at all.

    Returns a dict: removed, flagged, unflagged, skipped (bool), reason.
    """
    result = {"removed": 0, "flagged": 0, "unflagged": 0, "skipped": False, "reason": ""}
    prefix = untagged_path.rstrip("/") + "/"
    comics = list(Comic.objects.filter(
        file_path__startswith=prefix,
        medium=Comic.MEDIUM_DIGITAL,
    ))
    if not comics:
        return result

    missing = [c for c in comics if not os.path.exists(c.file_path)]
    folder_empty = not any(os.scandir(untagged_path))
    if missing and (folder_empty or (
            len(missing) >= MISSING_FILES_ABORT_MIN
            and len(missing) / len(comics) > MISSING_FILES_ABORT_RATIO)):
        result["skipped"] = True
        result["reason"] = (
            f"{len(missing)} of {len(comics)} files under {untagged_path} are missing; "
            "the folder may not be mounted, so nothing was removed or flagged"
        )
        return result

    missing_pks = {c.pk for c in missing}
    for comic in comics:
        if comic.pk in missing_pks:
            if comic.state == Comic.STATE_NEW:
                if not dry_run:
                    comic.delete()
                result["removed"] += 1
            elif not comic.has_flag("file_missing"):
                if not dry_run:
                    comic.add_flag("file_missing")
                    comic.save(update_fields=["flags"])
                result["flagged"] += 1
        elif comic.has_flag("file_missing"):
            if not dry_run:
                comic.remove_flag("file_missing")
                comic.save(update_fields=["flags"])
            result["unflagged"] += 1

    return result


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


def try_rezip_cbz(cbz_path: Path) -> dict:
    """
    Attempt to recover a corrupted CBZ by re-extracting all readable entries
    and repacking them into a fresh archive in place.

    Returns a dict:
    - success (bool)
    - page_count (int|None): image count in the recovered archive
    - extracted (int): total entries recovered
    - error (str): failure reason if not successful
    """
    import shutil
    import tempfile

    tmp_dir = Path(tempfile.mkdtemp())
    tmp_out = cbz_path.with_suffix(".cbz.tmp")

    try:
        try:
            zf_in = zipfile.ZipFile(cbz_path, "r")
        except (zipfile.BadZipFile, EOFError) as exc:
            return {"success": False, "error": f"Archive cannot be opened: {exc}"}

        extracted = []
        with zf_in:
            for info in zf_in.infolist():
                try:
                    zf_in.extract(info, tmp_dir)
                    extracted.append(info.filename)
                except Exception:
                    pass

        if not extracted:
            return {"success": False, "error": "No entries could be extracted from the archive"}

        from .cbz_utils import list_pages
        image_count = len(list_pages(extracted))

        with zipfile.ZipFile(tmp_out, "w", zipfile.ZIP_DEFLATED) as zf_out:
            for filename in sorted(extracted):
                src = tmp_dir / filename
                if src.exists():
                    zf_out.write(src, filename)

        tmp_out.replace(cbz_path)

        return {
            "success": True,
            "page_count": image_count if image_count > 0 else None,
            "extracted": len(extracted),
        }

    except Exception as exc:
        return {"success": False, "error": str(exc)}

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if tmp_out.exists():
            tmp_out.unlink(missing_ok=True)


def _get_cbz_page_count(cbz_path: Path) -> tuple[int | None, bool]:
    """
    Count image files inside a CBZ archive.

    Returns (count, is_corrupted):
    - (count, False) on success (count may be None if no images found)
    - (None, True) if the archive is corrupted or truncated
    """
    try:
        from .cbz_utils import list_pages
        with zipfile.ZipFile(cbz_path, "r") as zf:
            count = len(list_pages(zf.namelist()))
            return (count if count > 0 else None, False)
    except (zipfile.BadZipFile, EOFError):
        return (None, True)


def refresh_file_info(comic: "Comic") -> dict:
    """
    Re-read page count, file size, and cover hashes from the comic's file on disk.

    Returns a dict:
    {
        "updated": {field: new_value, ...},  -- only fields that changed
        "error": str | None,                 -- set if the file could not be read
        "hash_status": "updated"|"ok"|"unavailable"|"skipped",
    }
    """
    from apps.scraper.hasher import extract_cover_hashes

    if not comic.file_path:
        return {"updated": {}, "error": "No file path set on this comic.", "hash_status": "skipped"}

    path = Path(comic.file_path)
    if not path.exists():
        return {"updated": {}, "error": "File not found on disk.", "hash_status": "skipped"}

    updated = {}
    save_fields = []
    hash_status = "skipped"

    # File size
    new_size = path.stat().st_size
    if comic.file_size != new_size:
        comic.file_size = new_size
        updated["file_size"] = new_size
        save_fields.append("file_size")

    # Page count and cover hashes (CBZ only)
    if path.suffix.lower() == ".cbz":
        new_count, is_corrupted = _get_cbz_page_count(path)
        if is_corrupted:
            comic.add_flag("corrupted_archive")
            save_fields.append("flags")

        if not is_corrupted:
            if new_count is not None and comic.page_count != new_count:
                comic.page_count = new_count
                updated["page_count"] = new_count
                save_fields.append("page_count")

            hashes = extract_cover_hashes(path)
            if hashes:
                hash_changed = False
                if comic.phash != hashes.phash_hex:
                    comic.phash = hashes.phash_hex
                    updated["phash"] = hashes.phash_hex
                    save_fields.append("phash")
                    hash_changed = True
                if comic.ahash != hashes.ahash_hex:
                    comic.ahash = hashes.ahash_hex
                    updated["ahash"] = hashes.ahash_hex
                    save_fields.append("ahash")
                    hash_changed = True
                hash_status = "updated" if hash_changed else "ok"
            else:
                hash_status = "unavailable"

    if save_fields:
        comic.save(update_fields=list(set(save_fields)))

    return {"updated": updated, "error": None, "hash_status": hash_status}


def _detect_flags(
    file_format: str,
    page_count: int | None,
    filename: str,
    parsed: dict,
    is_corrupted: bool = False,
) -> dict:
    """
    Detect issues that need user review.

    Flags:
    - corrupted_archive: CBZ archive is corrupted or truncated (cannot be opened)
    - low_page_count: Less than 5 pages (configurable)
    - is_pdf: PDF files need manual review
    - no_series: Couldn't parse series name from filename
    - cover_only: Likely just a cover (≤3 pages + "cover" in filename)
    - needs_conversion: CBR/CB7 files need conversion to CBZ
    """
    from .models import get_setting

    flags = {}
    filename_lower = filename.lower()

    # Corrupted or truncated archive
    if is_corrupted:
        flags["corrupted_archive"] = True

    # Low page count (default threshold: 5)
    min_pages = get_setting("min_page_count", 5)
    if page_count is not None and page_count < min_pages:
        flags["low_page_count"] = True

    # PDF files need review
    if file_format == "pdf":
        flags["is_pdf"] = True

    # No series could be parsed
    if not parsed.get("series"):
        flags["no_series"] = True

    # Cover-only files (≤3 pages and "cover" in filename)
    cover_threshold = get_setting("cover_page_threshold", 3)
    if page_count is not None and page_count <= cover_threshold:
        if "cover" in filename_lower:
            flags["cover_only"] = True

    # Needs conversion (CBR, CB7)
    if file_format in ("cbr", "cb7"):
        flags["needs_conversion"] = True

    # ZIP files should be renamed to CBZ
    if file_format == "zip":
        flags["is_zip"] = True

    return flags


# Page count thresholds for collection format detection (see Comic_Book_Format_Definitions.md)
# 500+ pages with no other signals is reliably Omnibus territory (1000-1500 page Omnibus editions)
OMNIBUS_MIN_PAGES = 500
TPB_MIN_PAGES = 80

# Matches collection signals in a description:
#   - issue ranges:  "#1-5", "#2-#8", "Collects Batman #10-15"
#   - issue lists:   "#  1,   2,   3" (space-padded numbers after a hash)
#   - collection phrases: "features the following issues", "collecting issues"
TPB_ISSUE_RANGE_RE = re.compile(
    r"#\s*\d+\s*[-\u2013]\s*#?\s*\d+"          # range: #1-5 or #2-#8
    r"|Collects\b"                               # "Collects ..."
    r"|#\s*\d+(?:\s*,\s*\d+)+"                  # list: #1, 2, 3, 4
    r"|features\s+the\s+following\s+issues"      # "features the following issues"
    r"|collecting\s+issues",
    re.IGNORECASE,
)


def _parse_issue_number(number_str) -> int | None:
    """Extract the leading integer from an issue number string (e.g. '695' -> 695, '12.1' -> 12)."""
    if not number_str:
        return None
    m = re.match(r'^\d+', str(number_str))
    return int(m.group()) if m else None


def detect_format(comic, _one_shot_max=None, _limited_max=None) -> str | None:
    """
    Auto-detect comic format using the 3-step classification from Comic_Book_Format_Definitions.md.

    Step 1 — Edition modifiers (series/title text):
        Director's Cut, Black & White

    Step 2 — Collection formats (in priority order):
        1. Omnibus keyword in series/title/summary: definitive
        2. TPB keyword in series/title: definitive
        3. TPB by pages: page_count >= 80 AND summary has issue range (beats page-count Omnibus)
        4. Omnibus by pages: page_count >= 500 with no TPB signals (last resort fallback)

    Step 3 — Publication structure:
        Preview: "Preview"/"Previews" keyword in series/title
        Annual: keyword in series/title
        Count-based: Main Series (count > 15, or issue# > 15), Limited Series (2–15 with low issue#), One-Shot (count = 1 with low issue#)
    """
    from .models import get_setting

    text = f"{comic.series or ''} {comic.title or ''}"
    summary = comic.summary or ""
    page_count = comic.page_count or 0

    # Step 1: Edition modifiers
    if re.search(r"\bDirector'?s\s+Cut\b", text, re.IGNORECASE):
        return "Director's Cut"
    if re.search(r"\bBlack\s*&\s*White\b|\bB&W\b", text, re.IGNORECASE):
        return "Black & White"

    # Step 2: Collection formats
    # Omnibus keyword in title/series OR summary is definitive
    if re.search(r"\bOmnibus\b", text + " " + summary, re.IGNORECASE):
        return "Omnibus"
    # TPB signals evaluated before page-count Omnibus fallback
    if re.search(r"\bTPB\b|\bTrade\s+Paperback\b", text + " " + summary, re.IGNORECASE):
        return "TPB"
    if page_count >= TPB_MIN_PAGES and TPB_ISSUE_RANGE_RE.search(summary):
        return "TPB"
    # Page-count-only Omnibus: 500+ pages is reliably Omnibus territory
    if page_count >= OMNIBUS_MIN_PAGES:
        return "Omnibus"

    # Step 3: Publication structure
    if re.search(r"\bPreviews?\b", text, re.IGNORECASE):
        return "Preview"
    if re.search(r"\bAnnual\b", text, re.IGNORECASE):
        return "Annual"

    if comic.count is not None:
        one_shot_max = _one_shot_max if _one_shot_max is not None else get_setting("one_shot_max_count", 1)
        limited_max = _limited_max if _limited_max is not None else get_setting("limited_series_max_count", 15)

        if comic.count > limited_max:
            return "Main Series"
        issue_num = _parse_issue_number(comic.number)
        if issue_num is not None and issue_num > limited_max:
            return "Main Series"  # continuation / renumbered series
        if comic.count > one_shot_max:
            return "Limited Series"
        return "One-Shot"

    return None


def detect_and_set_format(comic, _one_shot_max=None, _limited_max=None) -> dict:
    """
    Detect format and apply it to a comic. Advances state to formatted.

    If comic.format_ok is True the detected format is NOT written — the manually
    confirmed format is preserved. State still advances and needs_reformat is cleared.

    Returns dict with detection results for reporting.
    """
    old_format = comic.format
    detected = detect_format(comic, _one_shot_max=_one_shot_max, _limited_max=_limited_max)

    is_inducks = comic.custom_values.get("scrape_source") == "inducks"

    if detected and not getattr(comic, "format_ok", False):
        comic.format = detected
        comic.flags.pop("missing_format", None)
    elif not comic.format:
        # Inducks comics have no CV issue count so count-based format rules don't apply;
        # skip the missing_format flag to avoid cluttering the review queue
        if not is_inducks:
            comic.flags["missing_format"] = True

    if comic.state == Comic.STATE_FORMATTED:
        if comic.medium == Comic.MEDIUM_PHYSICAL:
            comic.state = Comic.STATE_WRITTEN
        else:
            comic.state = Comic.STATE_DEDUPLICATED
    elif comic.state in (Comic.STATE_NEW, Comic.STATE_IMPORTED, Comic.STATE_SCRAPED,
                         Comic.STATE_COUNTED, Comic.STATE_TAGGED):
        if comic.medium == Comic.MEDIUM_PHYSICAL:
            comic.state = Comic.STATE_WRITTEN
        else:
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
