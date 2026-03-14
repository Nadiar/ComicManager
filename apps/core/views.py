import os
import re
import tempfile
import zipfile
from pathlib import Path

from django.shortcuts import render, get_object_or_404
from django.utils.html import strip_tags
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST, require_GET

from .models import Comic, get_setting
from .utils import natural_number_annotation, natural_sort_key, html_to_text, COLUMNS_REGISTRY, DEFAULT_COLUMNS, STATE_NEW_DEFAULT_COLUMNS
from .cbz_utils import insert_variant_covers
from apps.scraper.comicvine import ComicVineScraper, ComicVineRateLimitError
from apps.scraper.inducks import InducksScraper, is_inducks_available
from apps.scraper.hasher import extract_cover_hashes, extract_cover_image
from apps.scraper.services import (
    try_hash_match as _try_hash_match,
    try_metadata_match as _try_metadata_match,
    find_best_match as _find_best_match,
    apply_cv_match as _apply_match,
    metadata_alignment_score as _metadata_alignment_score,
    series_matches as _series_matches,
    normalize_issue_number as _normalize_issue_number,
)
from .services import scan_untagged_folder


# Columns editable inline on the STATE_NEW list
_INLINE_EDITABLE_FIELDS = {"proposed_series", "proposed_number", "proposed_volume", "publisher", "format"}

# Flag display names for the UI
FLAG_LABELS = {
    "corrupted_archive": "Corrupted Archive",
    "low_page_count": "Low Page Count",
    "is_pdf": "PDF File",
    "no_series": "No Series Parsed",
    "cover_only": "Cover Only",
    "needs_conversion": "Needs Conversion",
    "missing_count": "Missing Issue Count",
    "count_mismatch": "Count Mismatch",
    "metadata_mismatch": "Metadata Mismatch",
    "scrape_no_match": "Scrape: No Match",
    "scrape_error": "Scrape: Error",
    "scrape_skipped": "Scrape: Skipped",
    "unknown_publisher": "Unknown Publisher",
    "format_mismatch_in_volume": "Format Mismatch in Volume",
    "cv_volume_conflict": "CV Volume Conflict",
}

# Workflow states in order (for navigation)
WORKFLOW_STATES = [
    ("new",         "New"),
    ("scrape",      "Scrape"),
    ("count",       "Add Count"),
    ("tagging",     "Tagging"),
    ("formats",     "Add Formats"),
    ("deduplicate", "Deduplicate"),
    ("move",        "Move Files"),
    ("write",       "Write to CBZ"),
]


def _parse_smart_search(query):
    """
    Parse structured tokens out of a free-text search query.

    Recognised modifiers (extracted and removed from the base text):
      #N       -> issue number  (e.g. #10, #10.1, #Annual)
      (YYYY)   -> 4-digit year in parentheses
      VYYY     -> volume number  (e.g. V2, V12)

    Returns a dict: {text, number, year, volume}
    """
    text = query
    number = year = volume = None

    m = re.search(r'#(\S+)', text)
    if m:
        number = m.group(1)
        text = (text[:m.start()] + text[m.end():]).strip()

    m = re.search(r'\((\d{4})\)', text)
    if m:
        year = int(m.group(1))
        text = (text[:m.start()] + text[m.end():]).strip()

    m = re.search(r'\bV(\d+)\b', text, re.IGNORECASE)
    if m:
        volume = int(m.group(1))
        text = (text[:m.start()] + text[m.end():]).strip()

    return {"text": text, "number": number, "year": year, "volume": volume}


def comic_list(request):
    from django.db.models import Q
    from django.core.paginator import Paginator

    # Filter by state if provided
    state = request.GET.get("state")
    # Filter by flag if provided
    flag = request.GET.get("flag")

    # Column customization
    active_columns = request.GET.getlist("col")
    if not active_columns:
        # Try to load from settings based on context
        layout_key = "layout_default"
        if state:
            layout_key = f"layout_state_{state}"
        elif flag:
            layout_key = f"layout_flag_{flag}"
        
        saved_layout = get_setting(layout_key)
        if saved_layout:
            active_columns = saved_layout.split(",")
        elif state == Comic.STATE_NEW:
            active_columns = STATE_NEW_DEFAULT_COLUMNS
        else:
            active_columns = DEFAULT_COLUMNS

    comics = Comic.objects.all()

    # Search filter
    search = request.GET.get("q", "").strip()
    if search:
        parsed = _parse_smart_search(search)
        base_text = parsed["text"]

        if state == Comic.STATE_NEW:
            if base_text:
                comics = comics.filter(
                    Q(proposed_series__icontains=base_text) |
                    Q(proposed_number__icontains=base_text) |
                    Q(file_path__icontains=base_text)
                )
            if parsed["number"]:
                comics = comics.filter(proposed_number__iexact=parsed["number"])
        else:
            if base_text:
                comics = comics.filter(
                    Q(series__icontains=base_text) |
                    Q(title__icontains=base_text) |
                    Q(publisher__icontains=base_text) |
                    Q(number__icontains=base_text) |
                    Q(writer__icontains=base_text) |
                    Q(penciller__icontains=base_text) |
                    Q(inker__icontains=base_text) |
                    Q(colorist__icontains=base_text) |
                    Q(letterer__icontains=base_text) |
                    Q(cover_artist__icontains=base_text) |
                    Q(editor__icontains=base_text) |
                    Q(characters__icontains=base_text) |
                    Q(teams__icontains=base_text) |
                    Q(genre__icontains=base_text) |
                    Q(notes__icontains=base_text)
                )
            if parsed["number"]:
                comics = comics.filter(number__iexact=parsed["number"])
            if parsed["year"]:
                comics = comics.filter(year=parsed["year"])
            if parsed["volume"]:
                comics = comics.filter(volume=parsed["volume"])

    if state:
        comics = comics.filter(state=state)
    
    # Filter by publisher if provided
    publisher = request.GET.get("publisher")
    if publisher:
        comics = comics.filter(publisher=publisher)

    # Filter by format if provided
    format_filter = request.GET.get("format")
    if format_filter:
        comics = comics.filter(format=format_filter)

    # Filter by medium if provided
    medium = request.GET.get("medium")
    if medium:
        comics = comics.filter(medium=medium)

    if flag:
        # JSONField lookup: flags__<flag_name>=True
        comics = comics.filter(**{f"flags__{flag}": True})

    needs_reformat = request.GET.get("needs_reformat")
    if needs_reformat:
        comics = comics.filter(needs_reformat=True)

    # Annotate for natural number sorting (1, 2, 10 instead of 1, 10, 2)
    comics = comics.annotate(number_sort_key=natural_number_annotation())

    # Sorting
    sort = request.GET.get("sort", "series")
    sort_dir = request.GET.get("dir", "asc")

    # Map sort keys (matching COLUMNS_REGISTRY sort values) to ordered model field lists.
    # Keys not listed here fall back to [sort_key, "series", "volume", ...] automatically.
    sort_fields = {
        "series": ["series", "volume", "number_sort_key", "number"],
        "number": ["number_sort_key", "number"],
        "publisher": ["publisher", "series", "volume", "number_sort_key", "number"],
        "year": ["year", "series", "volume", "number_sort_key", "number"],
        "state": ["state", "series", "volume", "number_sort_key", "number"],
        "format": ["format", "series", "volume", "number_sort_key", "number"],
        "updated_at": ["updated_at"],
        "imported_at": ["imported_at"],
        "last_written": ["last_written"],
        "proposed_series": ["proposed_series", "proposed_volume", "proposed_number"],
        "proposed_number": ["proposed_number", "proposed_series"],
        "proposed_year": ["proposed_year", "proposed_series", "proposed_number"],
    }

    from django.db.models import F
    if sort == "page_count":
        # Use NULLS LAST so comics without a page count always sort to the bottom
        page_order = F("page_count").desc(nulls_last=True) if sort_dir == "desc" else F("page_count").asc(nulls_last=True)
        comics = comics.order_by(page_order, "series", "volume", "number_sort_key", "number")
    else:
        # Unknown sort keys fall back to [sort_key, secondary...] so any column is sortable
        order_fields = sort_fields.get(sort, [sort, "series", "volume", "number_sort_key", "number"])
        if sort_dir == "desc":
            order_fields = [f"-{f}" for f in order_fields]
        comics = comics.order_by(*order_fields)

    # Paginate (100 per page)
    per_page = int(request.GET.get("per_page", 100))
    per_page = min(max(per_page, 25), 500)  # Clamp between 25 and 500
    paginator = Paginator(comics, per_page)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    # Get distinct values for filter dropdowns
    publishers = Comic.objects.exclude(publisher__isnull=True).exclude(publisher="").values_list("publisher", flat=True).distinct().order_by("publisher")
    formats = Comic.objects.exclude(format__isnull=True).exclude(format="").values_list("format", flat=True).distinct().order_by("format")

    # Count comics needing conversion (for "Convert All" button)
    needs_conversion_count = Comic.objects.filter(flags__needs_conversion=True).count()

    # Build query string without page param (for pagination links)
    query_params = request.GET.copy()
    query_params.pop("page", None)
    query_string = query_params.urlencode()

    return render(request, "core/comic_list.html", {
        "comics": page_obj,
        "page_obj": page_obj,
        "total_count": paginator.count,
        "query_string": query_string,
        "per_page": per_page,
        "current_state": state,
        "current_state_label": dict(WORKFLOW_STATES).get(state, state),
        "current_flag": flag,
        "current_search": search,
        "current_publisher": publisher,
        "current_format": format_filter,
        "current_medium": medium,
        "current_sort": sort,
        "current_dir": sort_dir,
        "flag_label": FLAG_LABELS.get(flag, flag),
        "needs_conversion_count": needs_conversion_count,
        "workflow_states": WORKFLOW_STATES,
        "publishers": publishers,
        "formats": formats,
        "active_columns": active_columns,
        "all_columns": dict(sorted(COLUMNS_REGISTRY.items(), key=lambda x: x[1]["label"])),
        "inline_editable_cols": list(_INLINE_EDITABLE_FIELDS),
        "inducks_enabled": get_setting("inducks_enabled", False),
        "inducks_country_lock": get_setting("inducks_country_lock", ""),
        "inducks_country_codes": [c.strip() for c in get_setting("inducks_country_codes", "dk,de,nl,se,no,fi,us,it,fr,br").split(",") if c.strip()],
    })


def comic_detail(request, pk):
    """
    Display detailed information about a comic.

    For digital comics with CBZ files, reads ComicInfo.xml and compares
    database values against XML values to highlight differences.
    """
    from .utils import read_comicinfo_xml, compare_db_vs_xml

    comic = get_object_or_404(Comic, pk=pk)
    xml_data = None
    comparison = None
    reorganize_preview = None

    # Auto-scan page count if missing; flag corrupted archives
    if comic.is_digital and comic.file_path and not comic.page_count:
        if comic.file_path.lower().endswith('.cbz'):
            from .services import _get_cbz_page_count
            count, is_corrupted = _get_cbz_page_count(Path(comic.file_path))
            if count:
                comic.page_count = count
                comic.save(update_fields=["page_count"])
            elif is_corrupted and not comic.has_flag("corrupted_archive"):
                comic.add_flag("corrupted_archive")
                comic.save(update_fields=["flags"])

    # For digital comics, try to read ComicInfo.xml from the file
    if comic.is_digital and comic.file_path:
        if comic.file_path.lower().endswith('.cbz'):
            xml_data = read_comicinfo_xml(comic.file_path)
            if xml_data is not None:
                comparison = compare_db_vs_xml(comic, xml_data)

    # For organized/written comics, show reorganize preview
    if comic.state in (Comic.STATE_ORGANIZED, Comic.STATE_WRITTEN):
        from apps.organizer.services import preview_organization
        reorganize_preview = preview_organization(comic)

    # Filter out standard XML field names from custom_values for display
    from .utils import _STANDARD_XML_FIELDS
    display_custom_values = {
        k: v for k, v in (comic.custom_values or {}).items()
        if k not in _STANDARD_XML_FIELDS
    }

    # Check if series completion bar is enabled
    from .models import get_setting
    show_series_completion = get_setting("show_series_completion", True)

    # Variant covers range (1-based for the template loop)
    alt_cover_count = int(comic.custom_values.get("AltCoverCount", 0))
    alt_cover_range = range(1, alt_cover_count + 1) if alt_cover_count > 0 else []

    # Inducks search settings
    inducks_enabled = get_setting("inducks_enabled", False)
    inducks_country_lock = get_setting("inducks_country_lock", "")
    inducks_country_codes_str = get_setting("inducks_country_codes", "dk,de,nl,se,no,fi,us,it,fr,br")
    inducks_country_codes = [c.strip() for c in inducks_country_codes_str.split(",") if c.strip()]

    # Cover availability: digital with file, or any comic with a cached cover image
    from .cover_cache import COVER_CACHE_DIR
    has_cover = (
        (comic.is_digital and bool(comic.file_path))
        or (COVER_CACHE_DIR / f"{comic.pk}.jpg").exists()
    )

    # Physical alt covers: pre-compute proxy URLs so the template stays simple
    physical_covers = []
    if comic.is_physical:
        from urllib.parse import quote
        cv_issue_id = comic.custom_values.get("comicvine_issue", "0")
        main_cover_url = comic.custom_values.get("physical_main_cover_url", "")
        raw_urls = comic.custom_values.get("physical_cover_urls", [])
        if isinstance(raw_urls, list):
            for url in raw_urls:
                if url:
                    physical_covers.append({
                        "proxy_url": f"/comics/cv-cover/{cv_issue_id}/?url={quote(url, safe='')}",
                        "original_url": url,
                        "is_main": url == main_cover_url,
                    })

    return render(request, "core/comic_detail.html", {
        "comic": comic,
        "xml_data": xml_data,
        "comparison": comparison,
        "reorganize_preview": reorganize_preview,
        "display_custom_values": display_custom_values,
        "show_series_completion": show_series_completion,
        "alt_cover_range": alt_cover_range,
        "inducks_enabled": inducks_enabled,
        "inducks_country_lock": inducks_country_lock,
        "inducks_country_codes": inducks_country_codes,
        "has_cover": has_cover,
        "physical_covers": physical_covers,
    })


@require_POST
def try_rezip(request, pk):
    """
    Attempt to recover a corrupted CBZ by re-extracting readable entries and repacking.
    On success, clears the corrupted_archive flag and updates page_count.
    """
    comic = get_object_or_404(Comic, pk=pk)

    if not comic.is_digital or not comic.file_path:
        return JsonResponse({"success": False, "error": "Not a digital comic with a file"}, status=400)

    if not comic.file_path.lower().endswith(".cbz"):
        return JsonResponse({"success": False, "error": "Not a CBZ file"}, status=400)

    if not os.path.exists(comic.file_path):
        return JsonResponse({"success": False, "error": "File not found on disk"}, status=404)

    from .services import try_rezip_cbz
    result = try_rezip_cbz(Path(comic.file_path))

    if result["success"]:
        comic.remove_flag("corrupted_archive")
        if result.get("page_count"):
            comic.page_count = result["page_count"]
        comic.save(update_fields=["flags", "page_count"])
        return JsonResponse({
            "success": True,
            "message": f"Recovered {result['extracted']} entries. The file has been repacked.",
            "page_count": result.get("page_count"),
        })

    return JsonResponse({"success": False, "error": result["error"]}, status=500)


@require_POST
def toggle_scrape_skip(request, pk):
    """Toggle the scrape_skipped flag on a comic."""
    comic = get_object_or_404(Comic, pk=pk)
    if comic.flags.get("scrape_skipped"):
        comic.remove_flag("scrape_skipped")
        skipped = False
    else:
        comic.add_flag("scrape_skipped")
        skipped = True
    comic.save(update_fields=["flags"])
    return JsonResponse({"success": True, "skipped": skipped})


@require_POST
def convert_cbr(request, pk):
    """
    Convert a CBR/CB7 file to CBZ format.

    Extracts the archive to a temp directory, then repacks as a ZIP file
    with the same name but .cbz extension.
    """
    comic = get_object_or_404(Comic, pk=pk)

    # Validate this is a convertible file
    if comic.file_format not in ("cbr", "cb7"):
        return JsonResponse({
            "success": False,
            "error": f"Cannot convert {comic.file_format} format"
        }, status=400)

    if not comic.file_path or not os.path.exists(comic.file_path):
        return JsonResponse({
            "success": False,
            "error": "Source file not found"
        }, status=404)

    original_path = Path(comic.file_path)
    new_path = original_path.with_suffix(".cbz")

    # Don't overwrite existing CBZ
    if new_path.exists():
        return JsonResponse({
            "success": False,
            "error": f"Target file already exists: {new_path.name}"
        }, status=400)

    try:
        # Import patoolib lazily (only needed for conversion)
        import patoolib

        # Create temp directory for extraction
        with tempfile.TemporaryDirectory() as temp_dir:
            # Extract archive using patoolib
            patoolib.extract_archive(str(original_path), outdir=temp_dir, verbosity=-1)

            # Create new CBZ (ZIP file)
            with zipfile.ZipFile(new_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(temp_dir):
                    # Skip __MACOSX and hidden directories
                    dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__MACOSX"]

                    for file in sorted(files):
                        # Skip hidden files and metadata
                        if file.startswith(".") or file == "Thumbs.db":
                            continue

                        file_path = Path(root) / file
                        # Calculate archive path (relative to temp_dir)
                        arc_path = file_path.relative_to(temp_dir)
                        zf.write(file_path, arc_path)

        # Update comic record
        old_path_str = comic.file_path
        comic.file_path = str(new_path)
        comic.file_format = "cbz"

        # Remove needs_conversion flag
        if comic.flags and "needs_conversion" in comic.flags:
            del comic.flags["needs_conversion"]
            # Keep as empty dict, not None (NOT NULL constraint)
            if not comic.flags:
                comic.flags = {}

        comic.save()

        # Delete original file after successful conversion
        original_path.unlink()

        return JsonResponse({
            "success": True,
            "message": f"Converted to {new_path.name}",
            "new_path": str(new_path),
        })

    except Exception as e:
        # Clean up partial CBZ if it exists
        if new_path.exists():
            new_path.unlink()

        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=500)


@require_POST
def accept_comic(request, pk):
    """
    Accept a comic and move it from 'new' to 'imported' state.

    Copies proposed values to confirmed fields.
    """
    comic = get_object_or_404(Comic, pk=pk)

    if comic.state != Comic.STATE_NEW:
        return JsonResponse({
            "success": False,
            "error": f"Comic is not in 'new' state (current: {comic.state})"
        }, status=400)

    # Copy proposed values to confirmed fields
    comic.series = comic.proposed_series
    comic.number = comic.proposed_number
    comic.volume = comic.proposed_volume
    comic.year = comic.proposed_year

    # Advance state
    comic.state = Comic.STATE_IMPORTED
    comic.save()

    return JsonResponse({
        "success": True,
        "message": f"Accepted: {comic.series} #{comic.number}",
    })


@require_POST
def accept_all_comics(request):
    """
    Accept all comics in 'new' state, moving them to 'imported'.

    Only accepts comics that have a proposed_series (skips those with no_series flag).
    """
    comics = Comic.objects.filter(state=Comic.STATE_NEW)

    # Optionally filter to only accept comics without problematic flags
    skip_flags = request.POST.get("skip_flags", "").split(",")
    skip_flags = [f.strip() for f in skip_flags if f.strip()]

    accepted = 0
    skipped = 0

    for comic in comics:
        # Skip comics with no series parsed
        if not comic.proposed_series:
            skipped += 1
            continue

        # Skip comics with specified flags
        if skip_flags:
            has_skip_flag = any(comic.flags.get(f) for f in skip_flags)
            if has_skip_flag:
                skipped += 1
                continue

        # Copy proposed values to confirmed fields
        comic.series = comic.proposed_series
        comic.number = comic.proposed_number
        comic.volume = comic.proposed_volume
        comic.year = comic.proposed_year

        # Advance state
        comic.state = Comic.STATE_IMPORTED
        comic.save()
        accepted += 1

    return JsonResponse({
        "success": True,
        "accepted": accepted,
        "skipped": skipped,
    })


@require_POST
def convert_all_cbr(request):
    """
    Dispatch a Celery task to convert all CBR/CB7 files flagged for conversion.
    """
    from celery.result import AsyncResult
    from .tasks import convert_all_cbr_task

    active = request.session.get("active_task_id")
    if active and AsyncResult(active).state in ("PENDING", "STARTED", "PROGRESS"):
        return JsonResponse({"success": False, "error": "A task is already running", "task_id": active}, status=409)

    total = Comic.objects.filter(flags__needs_conversion=True).count()
    result = convert_all_cbr_task.delay()
    request.session["active_task_id"] = result.id
    request.session["active_task_label"] = "Converting files"
    return JsonResponse({"success": True, "task_id": result.id, "total": total, "message": f"Converting {total} files in background"})


def scrape_preview(request, pk):
    """
    Preview scrape matches for a comic without applying them.

    Returns a list of potential matches with cover URLs for user review.
    When the local DB is unavailable, returns an empty match list so the
    user can switch to the "Search API" tab in the scrape modal.

    Query params:
        force=1: Skip state check (for re-scraping comics in any state)
    """
    from apps.scraper.cv_sources import is_cv_db_available

    comic = get_object_or_404(Comic, pk=pk)

    force = request.GET.get("force") == "1"
    if not force and comic.state != Comic.STATE_IMPORTED:
        return JsonResponse({
            "success": False,
            "error": f"Comic is not in 'imported' state (current: {comic.state})"
        }, status=400)

    scraper = ComicVineScraper()
    max_distance = 10
    all_matches = []
    raw_matches = []

    if is_cv_db_available():
        # Try hash matching first
        if comic.file_path:
            hashes = extract_cover_hashes(comic.file_path)
            if hashes:
                comic.phash = hashes.phash_hex
                comic.ahash = hashes.ahash_hex

                hash_matches = scraper.match_by_hash_fast(
                    hashes.phash,
                    hashes.ahash,
                    max_distance=max_distance,
                    limit=5,
                )
                raw_matches.extend(hash_matches)

        # Also try metadata matching
        if comic.series and comic.number:
            meta_matches = scraper.match_by_metadata(
                series=comic.series,
                issue_number=comic.number,
                year=comic.year,
            )

            # Add metadata matches that aren't already in hash matches
            existing_ids = {m.issue_id for m in raw_matches}
            for match in meta_matches[:3]:
                if match.issue_id not in existing_ids:
                    raw_matches.append(match)

        # Enrich all matches with all cover URLs
        raw_matches = scraper.enrich_matches_with_covers(raw_matches)

    # Convert to dict format for JSON response
    for match in raw_matches:
        score = _metadata_alignment_score(comic, match)
        all_matches.append({
            "issue_id": match.issue_id,
            "volume_id": match.volume_id,
            "series": match.series,
            "number": match.issue_number,
            "title": match.title,
            "publisher": match.publisher,
            "year": match.start_year,
            "cover_url": match.cover_url,
            "cover_urls": match.cover_urls or [],
            "match_type": match.match_type,
            "match_score": match.match_score,
            "alignment_score": score,
            "recommended": score > 0,
        })

    # Sort by alignment score (desc) then match score (asc)
    all_matches.sort(key=lambda m: (-m["alignment_score"], m["match_score"]))

    return JsonResponse({
        "success": True,
        "comic": {
            "id": str(comic.pk),
            "series": comic.series,
            "number": comic.number,
            "year": comic.year,
        },
        "matches": all_matches,
    })


def scrape_api_search(request, pk):
    """
    Search the ComicVine API for matches.

    Query params:
        q: Search query (defaults to comic's series + number).
           If the query matches the pattern "4000-<issue_id>" it is treated as a
           direct ComicVine issue ID lookup — no search is performed.
    """
    from .models import get_setting
    from apps.scraper.cv_sources import is_cv_db_available

    comic = get_object_or_404(Comic, pk=pk)

    api_key = get_setting("cv_api_key")
    if not api_key:
        return JsonResponse({
            "success": False,
            "error": "ComicVine API key not configured. Set it in Settings.",
        }, status=400)

    query = request.GET.get("q", "").strip()
    if not query:
        parts = [comic.series or comic.proposed_series or "", comic.number or comic.proposed_number or ""]
        query = " ".join(p for p in parts if p).strip()

    if not query:
        return JsonResponse({
            "success": False,
            "error": "No search query provided and couldn't derive one from comic metadata.",
        }, status=400)

    scraper = ComicVineScraper()

    # Direct issue ID lookup: "4000-<issue_id>"
    direct_id_match = re.fullmatch(r"4000-(\d+)", query, re.IGNORECASE)
    if direct_id_match:
        issue_id = int(direct_id_match.group(1))
        match = None

        # Try local DB first (free, fast)
        if is_cv_db_available():
            match = scraper.get_issue_details(issue_id)
            if match:
                match = scraper.enrich_matches_with_covers([match])[0]

        # Fall back to API
        if match is None:
            try:
                match = scraper.get_issue_from_api(issue_id)
            except ComicVineRateLimitError as e:
                return JsonResponse({"success": False, "error": str(e), "rate_limited": True}, status=429)

        if match is None:
            return JsonResponse({
                "success": False,
                "error": f"No issue found for ID 4000-{issue_id}.",
            }, status=404)

        score = _metadata_alignment_score(comic, match)
        return JsonResponse({
            "success": True,
            "source": "direct",
            "comic": {"id": str(comic.pk), "series": comic.series, "number": comic.number, "year": comic.year},
            "matches": [{
                "issue_id": match.issue_id,
                "volume_id": match.volume_id,
                "series": match.series,
                "number": match.issue_number,
                "title": match.title,
                "publisher": match.publisher,
                "year": match.start_year,
                "cover_url": match.cover_url,
                "cover_urls": match.cover_urls or [],
                "match_type": "direct",
                "match_score": 0,
                "alignment_score": score,
                "recommended": True,
            }],
        })

    try:
        api_matches = scraper.search_api(query)
    except ComicVineRateLimitError as e:
        return JsonResponse({
            "success": False,
            "error": str(e),
            "rate_limited": True,
        }, status=429)

    all_matches = []
    for match in api_matches:
        score = _metadata_alignment_score(comic, match)
        all_matches.append({
            "issue_id": match.issue_id,
            "volume_id": match.volume_id,
            "series": match.series,
            "number": match.issue_number,
            "title": match.title,
            "publisher": match.publisher,
            "year": match.start_year,
            "cover_url": match.cover_url,
            "cover_urls": match.cover_urls or [],
            "match_type": match.match_type,
            "match_score": match.match_score,
            "alignment_score": score,
            "recommended": score > 0,
        })

    all_matches.sort(key=lambda m: (-m["alignment_score"], m["match_score"]))

    return JsonResponse({
        "success": True,
        "source": "api",
        "comic": {
            "id": str(comic.pk),
            "series": comic.series,
            "number": comic.number,
            "year": comic.year,
        },
        "matches": all_matches,
    })


def inducks_search(request, pk):
    """
    Search the local Inducks database for matches.

    Query params:
        q: Search query (publication title, optionally with issue number)
        country: Country code filter (e.g. dk, us, de)
    """
    from .models import get_setting

    comic = get_object_or_404(Comic, pk=pk)

    if not get_setting("inducks_enabled", False):
        return JsonResponse({
            "success": False,
            "error": "Inducks search is not enabled. Enable it in Settings.",
        }, status=400)

    if not is_inducks_available():
        return JsonResponse({
            "success": False,
            "error": "Inducks database not found. Check the inducks_db_path setting.",
        }, status=400)

    query = request.GET.get("q", "").strip()
    storycode = request.GET.get("storycode", "").strip()

    if not query and not storycode:
        parts = [comic.series or comic.proposed_series or "", comic.number or comic.proposed_number or ""]
        query = " ".join(p for p in parts if p).strip()

    if not query and not storycode:
        return JsonResponse({
            "success": False,
            "error": "No search query provided.",
        }, status=400)

    # Country: use lock setting, or query param, or None
    country_lock = get_setting("inducks_country_lock", "").strip()
    country = country_lock or request.GET.get("country", "").strip() or None

    scraper = InducksScraper()
    try:
        if storycode:
            matches = scraper.search_by_storycode(storycode, country=country, limit=10)
        else:
            matches = scraper.search(query, country=country, limit=10)
    except Exception as e:
        logger.exception("Inducks search error")
        return JsonResponse({
            "success": False,
            "error": f"Search error: {e}",
        }, status=500)

    all_matches = []
    for match in matches:
        all_matches.append({
            "issuecode": match.issuecode,
            "series": match.series,
            "number": match.issue_number,
            "title": match.title,
            "publisher": match.publisher,
            "year": match.start_year,
            "cover_url": match.cover_url,
            "cover_urls": [],
            "match_type": "inducks",
            "match_score": 0,
            "alignment_score": 0,
            "recommended": False,
            "pages": match.pages,
            "country": match.country,
            "language": match.language,
            "source": "inducks",
            "stories": match.stories or [],
        })

    return JsonResponse({
        "success": True,
        "source": "inducks",
        "comic": {
            "id": str(comic.pk),
            "series": comic.series,
            "number": comic.number,
            "year": comic.year,
        },
        "matches": all_matches,
    })


def inducks_cover(request):
    """
    Proxy endpoint for Inducks cover images.

    Downloads the cover once and caches it locally, serving from cache on
    subsequent requests.
    """
    from .cover_cache import get_inducks_cover

    issuecode = request.GET.get("issuecode", "")
    cover_url = request.GET.get("url", "")
    if not issuecode or not cover_url:
        return HttpResponse(status=400)

    cover_data = get_inducks_cover(issuecode, cover_url)
    if not cover_data:
        return HttpResponse(status=404)

    # Detect content type from URL
    content_type = "image/jpeg"
    if cover_url.lower().endswith(".png"):
        content_type = "image/png"

    response = HttpResponse(cover_data, content_type=content_type)
    response["Cache-Control"] = "public, max-age=604800"
    return response


def cv_compare(request, pk):
    """
    4-way metadata comparison: DB vs ComicInfo.xml vs comicvine.db vs CV API.

    Uses the comic's comicvine_issue ID to fetch data from local CV DB and API,
    then compares all four sources field by field.
    """
    from .utils import read_comicinfo_xml, compare_all_sources
    from .models import get_setting

    comic = get_object_or_404(Comic, pk=pk)

    if comic.custom_values.get("scrape_source") == "inducks":
        return JsonResponse({
            "success": False,
            "error": "CV comparison not available for Inducks-scraped comics.",
        })

    cv_issue_id = comic.custom_values.get("comicvine_issue")
    if not cv_issue_id:
        return JsonResponse({
            "success": False,
            "error": "No ComicVine issue ID linked to this comic.",
        })

    scraper = ComicVineScraper()

    # Source 2: XML
    xml_data = None
    if comic.is_digital and comic.file_path and comic.file_path.lower().endswith('.cbz'):
        xml_data = read_comicinfo_xml(comic.file_path)

    # Source 3: CV Local DB
    cv_local = scraper.get_issue_details(int(cv_issue_id))

    # Source 4: CV API (only if API key configured)
    cv_api = None
    api_key = get_setting("cv_api_key", "").strip()
    api_skipped_reason = None
    if api_key:
        try:
            cv_api = scraper.get_issue_from_api(int(cv_issue_id))
            if cv_api is None:
                api_skipped_reason = "API call returned no data"
        except ComicVineRateLimitError:
            api_skipped_reason = "Rate limited — wait a minute before retrying"
    else:
        api_skipped_reason = "No API key configured"

    comparison = compare_all_sources(comic, xml_data, cv_local, cv_api)

    return JsonResponse({
        "success": True,
        "cv_issue_id": int(cv_issue_id),
        "sources": {
            "db": True,
            "xml": xml_data is not None,
            "cv_local": cv_local is not None,
            "cv_api": cv_api is not None,
            "api_skipped_reason": api_skipped_reason,
        },
        "common": comparison["common"],
        "extras": comparison["extras"],
    })


def comic_cover(request, pk):
    """
    Serve the cover image of a comic file.

    For digital comics: extracts from CBZ on first request and caches.
    For physical comics: serves from cache (populated after scraping or manual upload).
    """
    from .cover_cache import get_comic_cover

    comic = get_object_or_404(Comic, pk=pk)

    cover_data = get_comic_cover(comic)
    if not cover_data:
        return HttpResponse(status=404)

    response = HttpResponse(cover_data, content_type="image/jpeg")
    response["Cache-Control"] = "public, max-age=86400"
    return response


@require_POST
def set_physical_cover(request, pk):
    """Set a specific CV cover URL as the main cover for a physical comic."""
    from urllib.parse import quote
    from .cover_cache import cache_physical_cover, invalidate_comic_cover

    comic = get_object_or_404(Comic, pk=pk)
    if not comic.is_physical:
        return JsonResponse({"success": False, "error": "Not a physical comic"}, status=400)

    cover_url = request.POST.get("cover_url", "").strip()
    if not cover_url:
        return JsonResponse({"success": False, "error": "No cover_url provided"}, status=400)

    invalidate_comic_cover(comic.pk)
    ok = cache_physical_cover(comic.pk, cover_url)
    if not ok:
        return JsonResponse({"success": False, "error": "Failed to download cover"}, status=500)

    comic.custom_values["physical_main_cover_url"] = cover_url
    comic.save()
    return JsonResponse({"success": True})


def upload_cover(request, pk):
    """Upload a cover image for a physical comic, stored in the cover cache."""
    import io as _io
    from PIL import Image
    from .cover_cache import COVER_CACHE_DIR, _ensure_cache_dir, invalidate_comic_cover

    comic = get_object_or_404(Comic, pk=pk)

    cover_file = request.FILES.get("cover")
    if not cover_file:
        return JsonResponse({"success": False, "error": "No file uploaded"}, status=400)

    allowed_types = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"}
    if cover_file.content_type not in allowed_types:
        return JsonResponse({"success": False, "error": "Invalid file type"}, status=400)

    try:
        img = Image.open(cover_file)
        try:
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            output = _io.BytesIO()
            img.save(output, format="JPEG", quality=85)
            cover_data = output.getvalue()
        finally:
            img.close()
    except Exception as e:
        return JsonResponse({"success": False, "error": f"Failed to process image: {e}"}, status=400)

    invalidate_comic_cover(comic.pk)
    _ensure_cache_dir()
    (COVER_CACHE_DIR / f"{comic.pk}.jpg").write_bytes(cover_data)

    return JsonResponse({"success": True, "message": "Cover uploaded successfully"})


def comic_page(request, pk, page_num):
    """
    Serve a specific page of a comic file.
    page_num is 0-based.
    """
    from .cover_cache import get_comic_page

    comic = get_object_or_404(Comic, pk=pk)

    if not comic.file_path:
        return HttpResponse(status=404)

    page_data = get_comic_page(comic, int(page_num))
    if not page_data:
        return HttpResponse(status=404)

    response = HttpResponse(page_data, content_type="image/jpeg")
    response["Cache-Control"] = "public, max-age=86400"
    return response


@require_GET
def comic_pages_list(request, pk):
    """
    GET → JSON: {page_count: N, pages: [{index, url}]}
    Lists all pages of a CBZ comic for the page manager UI.
    """
    comic = get_object_or_404(Comic, pk=pk)

    if not comic.is_digital or not comic.file_path:
        return JsonResponse({"error": "Not a digital comic with a file"}, status=400)

    page_count = comic.page_count or 0
    pages = [
        {"index": i, "url": f"/comics/{pk}/page/{i}/"}
        for i in range(page_count)
    ]
    return JsonResponse({"page_count": page_count, "pages": pages})


@require_POST
def comic_pages_reorder(request, pk):
    """
    POST → JSON: {success, page_count}
    Body: {order: [0, 3, 1, 2, ...]}  — list of old indices in new sequence.
    """
    import json
    from .cbz_utils import reorder_pages
    from .cover_cache import invalidate_comic_pages

    comic = get_object_or_404(Comic, pk=pk)

    if not comic.is_digital or not comic.file_path:
        return JsonResponse({"error": "Not a digital comic with a file"}, status=400)

    try:
        body = json.loads(request.body)
        new_order = body.get("order", [])
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    if not isinstance(new_order, list) or not new_order:
        return JsonResponse({"error": "order must be a non-empty list"}, status=400)

    success = reorder_pages(comic.file_path, new_order)
    if not success:
        return JsonResponse({"error": "Reorder failed"}, status=500)

    invalidate_comic_pages(comic.pk)
    comic.page_count = len(new_order)
    comic.save(update_fields=["page_count"])

    return JsonResponse({"success": True, "page_count": comic.page_count})


@require_POST
def comic_pages_delete(request, pk):
    """
    POST → JSON: {success, page_count}
    Body: {indices: [0, 2]}  — 0-based page indices to delete.
    """
    import json
    from .cbz_utils import delete_pages
    from .cover_cache import invalidate_comic_pages

    comic = get_object_or_404(Comic, pk=pk)

    if not comic.is_digital or not comic.file_path:
        return JsonResponse({"error": "Not a digital comic with a file"}, status=400)

    try:
        body = json.loads(request.body)
        indices = body.get("indices", [])
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    if not isinstance(indices, list) or not indices:
        return JsonResponse({"error": "indices must be a non-empty list"}, status=400)

    success = delete_pages(comic.file_path, indices)
    if not success:
        return JsonResponse({"error": "Delete failed"}, status=500)

    invalidate_comic_pages(comic.pk)
    new_count = (comic.page_count or 0) - len(set(indices))
    comic.page_count = max(0, new_count)
    comic.save(update_fields=["page_count"])

    return JsonResponse({"success": True, "page_count": comic.page_count})


@require_POST
def comic_pages_add(request, pk):
    """
    POST (multipart) → JSON: {success, page_count}
    Form fields: file (image), position (int, 0-based).
    """
    import os as _os
    from .cbz_utils import add_page_from_upload
    from .cover_cache import invalidate_comic_pages

    comic = get_object_or_404(Comic, pk=pk)

    if not comic.is_digital or not comic.file_path:
        return JsonResponse({"error": "Not a digital comic with a file"}, status=400)

    uploaded = request.FILES.get("file")
    if not uploaded:
        return JsonResponse({"error": "No file uploaded"}, status=400)

    position = request.POST.get("position", "0")
    try:
        position = int(position)
    except ValueError:
        position = 0

    image_bytes = uploaded.read()
    _, ext = _os.path.splitext(uploaded.name.lower())
    if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}:
        ext = ".jpg"

    success = add_page_from_upload(comic.file_path, image_bytes, position, ext)
    if not success:
        return JsonResponse({"error": "Add page failed"}, status=500)

    invalidate_comic_pages(comic.pk)
    comic.page_count = (comic.page_count or 0) + 1
    comic.save(update_fields=["page_count"])

    return JsonResponse({"success": True, "page_count": comic.page_count})


@require_POST
def comic_pages_save(request, pk):
    """
    POST (multipart) → JSON: {success, page_count}
    Form fields:
        layout  – JSON string: [{type, index|key}, ...]
        file_N  – uploaded image files referenced by "new" layout entries
    Replaces the entire page sequence in one atomic operation.
    """
    import json as _json
    import os as _os
    from .cbz_utils import save_page_layout
    from .cover_cache import invalidate_comic_pages

    comic = get_object_or_404(Comic, pk=pk)

    if not comic.is_digital or not comic.file_path:
        return JsonResponse({"error": "Not a digital comic with a file"}, status=400)

    layout_raw = request.POST.get("layout", "")
    try:
        layout = _json.loads(layout_raw)
    except (_json.JSONDecodeError, TypeError):
        return JsonResponse({"error": "Invalid layout JSON"}, status=400)

    if not isinstance(layout, list) or not layout:
        return JsonResponse({"error": "layout must be a non-empty list"}, status=400)

    # Collect uploaded files; derive extension from original filename
    uploaded_files = {}
    for key, f in request.FILES.items():
        _, ext = _os.path.splitext(f.name.lower())
        if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}:
            ext = ".jpg"
        # Store as key+ext so save_page_layout can pick the right extension
        uploaded_files[key] = f.read()
        # Patch layout entries to carry the correct extension in the key
        for entry in layout:
            if entry.get("type") == "new" and entry.get("key") == key:
                entry["_ext"] = ext

    # Re-key upload_files to include extension for the backend function
    keyed = {}
    for key, data in uploaded_files.items():
        ext = next(
            (e.get("_ext", ".jpg") for e in layout if e.get("type") == "new" and e.get("key") == key),
            ".jpg"
        )
        keyed[key + ext] = data

    # Update layout keys to match
    for entry in layout:
        if entry.get("type") == "new":
            entry["key"] = entry["key"] + entry.pop("_ext", ".jpg")

    success = save_page_layout(comic.file_path, layout, keyed)
    if not success:
        return JsonResponse({"error": "Save failed"}, status=500)

    invalidate_comic_pages(comic.pk)
    new_count = len(layout)
    comic.page_count = new_count
    comic.save(update_fields=["page_count"])

    return JsonResponse({"success": True, "page_count": new_count})


@require_GET
def cv_cover(request, issue_id):
    """
    Proxy endpoint for ComicVine cover images.

    Downloads the cover once and caches it locally, serving from cache on
    subsequent requests. Avoids direct hotlinking to ComicVine CDN.
    """
    from .cover_cache import get_cv_cover

    cover_url = request.GET.get("url", "")
    if not cover_url:
        return HttpResponse(status=400)

    cover_data = get_cv_cover(issue_id, cover_url)
    if not cover_data:
        return HttpResponse(status=404)

    response = HttpResponse(cover_data, content_type="image/jpeg")
    response["Cache-Control"] = "public, max-age=604800"
    return response


@require_POST
def scrape_comic(request, pk):
    """
    Scrape a single comic against the ComicVine database.

    If issue_id is provided in POST data (form or JSON), use that specific match.
    Otherwise, auto-select the best match.

    Query params:
        force=1: Skip state check (for re-scraping comics in any state)
    """
    import json

    comic = get_object_or_404(Comic, pk=pk)

    force = request.GET.get("force") == "1"

    # Parse JSON body for manual match selection
    cv_issue_id = request.POST.get("cv_issue_id") or request.POST.get("issue_id")
    inducks_issuecode = None
    inducks_storycode = None
    source = None

    if not cv_issue_id and request.content_type == "application/json":
        try:
            body = json.loads(request.body)
            source = body.get("source")
            cv_issue_id = body.get("issue_id") or body.get("cv_issue_id")
            inducks_issuecode = body.get("issuecode")
            inducks_storycode = body.get("storycode")
            if cv_issue_id or inducks_issuecode or inducks_storycode:
                force = True
        except (json.JSONDecodeError, ValueError):
            pass

    if not force and comic.state != Comic.STATE_IMPORTED:
        return JsonResponse({
            "success": False,
            "error": f"Comic is not in 'imported' state (current: {comic.state})"
        }, status=400)

    # Handle Inducks match
    if source == "inducks" and (inducks_issuecode or inducks_storycode):
        from apps.scraper.services import apply_inducks_match

        scraper = InducksScraper()
        if inducks_storycode and inducks_issuecode:
            match = scraper.get_story_details(inducks_issuecode, inducks_storycode)
        elif inducks_storycode:
            match = scraper.get_story_only(inducks_storycode)
        else:
            match = scraper.get_issue_details(inducks_issuecode)
        if not match:
            label = inducks_storycode or inducks_issuecode
            return JsonResponse({
                "success": False,
                "error": f"Not found in Inducks: {label}"
            }, status=404)

        apply_inducks_match(comic, match)

        msg = f"Matched story: {match.title}" if not match.issuecode else f"Matched: {match.series} #{match.issue_number}"
        return JsonResponse({
            "success": True,
            "message": msg,
            "match": {
                "series": match.series,
                "number": match.issue_number,
                "publisher": match.publisher,
                "year": match.start_year,
                "match_type": "inducks",
                "cover_url": match.cover_url,
            }
        })

    # ComicVine match (existing flow)
    from apps.scraper.cv_sources import is_cv_db_available

    scraper = ComicVineScraper()
    match = None

    if cv_issue_id:
        if is_cv_db_available():
            match = scraper.get_issue_details(int(cv_issue_id))
        if not match:
            match = scraper.get_issue_from_api(int(cv_issue_id))
        if match:
            match.match_type = "manual"
    else:
        match = _find_best_match(comic, scraper)

    if not match:
        return JsonResponse({
            "success": False,
            "error": "No match found in ComicVine database"
        }, status=404)

    _apply_match(comic, match, scraper)

    return JsonResponse({
        "success": True,
        "message": f"Matched: {match.series} #{match.issue_number}",
        "match": {
            "series": match.series,
            "number": match.issue_number,
            "publisher": match.publisher,
            "year": match.start_year,
            "match_type": match.match_type,
            "cover_url": match.cover_url,
        }
    })


@require_POST
def scrape_all_comics(request):
    """
    Dispatch a Celery task to scrape all comics in 'imported' state.
    """
    from celery.result import AsyncResult
    from .tasks import scrape_all_task

    active = request.session.get("active_task_id")
    if active and AsyncResult(active).state in ("PENDING", "STARTED", "PROGRESS"):
        return JsonResponse({"success": False, "error": "A task is already running", "task_id": active}, status=409)

    total = Comic.objects.filter(state=Comic.STATE_IMPORTED).count()
    result = scrape_all_task.delay()
    request.session["active_task_id"] = result.id
    request.session["active_task_label"] = "Scraping comics"
    return JsonResponse({"success": True, "task_id": result.id, "total": total, "message": f"Scraping {total} comics in background"})




def _populate_missing_counts():
    """
    Find comics with a comicvine_volume but null count,
    and populate count from the CV SQLite DB.
    """
    import sqlite3
    from django.conf import settings

    comics = Comic.objects.filter(
        count__isnull=True,
    ).exclude(
        custom_values__comicvine_volume__isnull=True,
    ).exclude(
        custom_values__comicvine_volume="",
    )

    if not comics.exists():
        return {"populated": 0, "failed": 0, "total": 0}

    # Collect unique volume IDs
    volume_ids = set()
    comic_list = list(comics)
    for c in comic_list:
        vid = c.custom_values.get("comicvine_volume")
        if vid:
            volume_ids.add(int(vid))

    # Batch query CV DB for count_of_issues
    db_path = getattr(settings, "CV_DB_PATH", "/cv_db/comicvine.db")
    volume_counts = {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)
        cursor = conn.cursor()
        # Chunk into batches of 500 to avoid large IN clauses
        volume_id_list = list(volume_ids)
        for i in range(0, len(volume_id_list), 500):
            chunk = volume_id_list[i:i + 500]
            placeholders = ",".join("?" * len(chunk))
            cursor.execute(
                f"SELECT id, count_of_issues FROM cv_volume WHERE id IN ({placeholders})",
                chunk,
            )
            for row in cursor.fetchall():
                if row[1] is not None:
                    volume_counts[row[0]] = row[1]
        conn.close()
    except Exception:
        pass

    populated = 0
    failed = 0
    for comic in comic_list:
        vid = comic.custom_values.get("comicvine_volume")
        if not vid:
            continue
        count = volume_counts.get(int(vid))
        if count is not None:
            comic.count = count
            comic.custom_values["comicvine_issue_count"] = str(count)
            comic.remove_flag("missing_count")
            comic.save()
            populated += 1
        else:
            comic.add_flag("missing_count")
            comic.save()
            failed += 1

    return {"populated": populated, "failed": failed, "total": populated + failed}


def _detect_count_mismatches():
    """
    Find volumes where comics disagree on count value.
    Flag comics in mismatched volumes with 'count_mismatch'.
    """
    comics_with_volume = Comic.objects.filter(
        count__isnull=False,
    ).exclude(
        custom_values__comicvine_volume__isnull=True,
    ).exclude(
        custom_values__comicvine_volume="",
    )

    # Group by volume
    volume_comics = {}
    for comic in comics_with_volume:
        vid = comic.custom_values.get("comicvine_volume")
        if not vid:
            continue
        if vid not in volume_comics:
            volume_comics[vid] = []
        volume_comics[vid].append(comic)

    flagged = 0
    cleared = 0
    mismatched_volumes = 0

    for vid, comics_in_vol in volume_comics.items():
        counts = set(c.count for c in comics_in_vol)
        if len(counts) > 1:
            mismatched_volumes += 1
            for comic in comics_in_vol:
                if not comic.has_flag("count_mismatch") and not comic.is_flag_accepted("count_mismatch"):
                    comic.add_flag("count_mismatch")
                    comic.save()
                    flagged += 1
        else:
            for comic in comics_in_vol:
                if comic.has_flag("count_mismatch"):
                    comic.remove_flag("count_mismatch")
                    comic.save()
                    cleared += 1

    return {
        "mismatched_volumes": mismatched_volumes,
        "flagged": flagged,
        "cleared": cleared,
    }


def _detect_format_conflicts():
    """
    Detect two types of format conflicts:

    P5.7 — format_mismatch_in_volume:
        Comics linked to the same CV volume but with different format values.

    P5.8 — cv_volume_conflict:
        Comics with the same (series, volume, format) but linked to different CV volumes.

    Respects accepted_flags — skips setting a flag if the comic has already accepted it.
    """
    # P5.7: group by comicvine_volume, look for multiple distinct formats
    comics_with_vol_and_fmt = list(
        Comic.objects.exclude(
            custom_values__comicvine_volume__isnull=True,
        ).exclude(
            custom_values__comicvine_volume="",
        ).exclude(
            format__isnull=True,
        ).exclude(
            format="",
        )
    )

    volume_formats = {}
    for comic in comics_with_vol_and_fmt:
        vid = comic.custom_values.get("comicvine_volume")
        if not vid:
            continue
        if vid not in volume_formats:
            volume_formats[vid] = []
        volume_formats[vid].append(comic)

    flagged_57 = 0
    cleared_57 = 0
    conflicting_volumes = 0

    for vid, vol_comics in volume_formats.items():
        formats = set(c.format for c in vol_comics)
        if len(formats) > 1:
            conflicting_volumes += 1
            for comic in vol_comics:
                if not comic.has_flag("format_mismatch_in_volume") and not comic.is_flag_accepted("format_mismatch_in_volume"):
                    comic.add_flag("format_mismatch_in_volume")
                    comic.save(update_fields=["flags"])
                    flagged_57 += 1
        else:
            for comic in vol_comics:
                if comic.has_flag("format_mismatch_in_volume"):
                    comic.remove_flag("format_mismatch_in_volume")
                    comic.save(update_fields=["flags"])
                    cleared_57 += 1

    # P5.8: group by (series, volume, format), look for multiple distinct CV volumes
    comics_with_all = list(
        Comic.objects.exclude(
            series__isnull=True,
        ).exclude(
            series="",
        ).exclude(
            format__isnull=True,
        ).exclude(
            format="",
        ).exclude(
            custom_values__comicvine_volume__isnull=True,
        ).exclude(
            custom_values__comicvine_volume="",
        )
    )

    series_groups = {}
    for comic in comics_with_all:
        vid = comic.custom_values.get("comicvine_volume")
        if not vid:
            continue
        key = (comic.series, comic.volume, comic.format)
        if key not in series_groups:
            series_groups[key] = []
        series_groups[key].append(comic)

    flagged_58 = 0
    cleared_58 = 0
    conflicting_groups = 0

    for key, group_comics in series_groups.items():
        cv_volumes = set(c.custom_values.get("comicvine_volume") for c in group_comics)
        if len(cv_volumes) > 1:
            conflicting_groups += 1
            for comic in group_comics:
                if not comic.has_flag("cv_volume_conflict") and not comic.is_flag_accepted("cv_volume_conflict"):
                    comic.add_flag("cv_volume_conflict")
                    comic.save(update_fields=["flags"])
                    flagged_58 += 1
        else:
            for comic in group_comics:
                if comic.has_flag("cv_volume_conflict"):
                    comic.remove_flag("cv_volume_conflict")
                    comic.save(update_fields=["flags"])
                    cleared_58 += 1

    return {
        "conflicting_volumes": conflicting_volumes,
        "flagged_format_mismatch": flagged_57,
        "cleared_format_mismatch": cleared_57,
        "conflicting_groups": conflicting_groups,
        "flagged_cv_conflict": flagged_58,
        "cleared_cv_conflict": cleared_58,
    }


@require_POST
def fix_count_mismatches(request):
    """
    Force-repopulate counts from CV DB for all comics flagged count_mismatch.
    Unlike populate_counts_task, this overwrites existing count values.
    Then re-runs mismatch detection to clear resolved flags.
    """
    from apps.scraper.cv_sources import is_cv_db_available
    import sqlite3

    from django.conf import settings

    if not is_cv_db_available():
        return JsonResponse({"success": False, "error": "ComicVine database not available"}, status=400)

    comics = list(Comic.objects.filter(flags__count_mismatch=True).exclude(
        custom_values__comicvine_volume__isnull=True,
    ).exclude(
        custom_values__comicvine_volume="",
    ))

    if not comics:
        return JsonResponse({"success": True, "updated": 0, "message": "No count_mismatch comics found"})

    # Batch-fetch counts from CV DB
    volume_ids = {int(c.custom_values["comicvine_volume"]) for c in comics if c.custom_values.get("comicvine_volume")}
    db_path = getattr(settings, "CV_DB_PATH", "/cv_db/comicvine.db")
    volume_counts = {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)
        cursor = conn.cursor()
        for i in range(0, len(volume_ids), 500):
            chunk = list(volume_ids)[i:i + 500]
            placeholders = ",".join("?" * len(chunk))
            cursor.execute(f"SELECT id, count_of_issues FROM cv_volume WHERE id IN ({placeholders})", chunk)
            for row in cursor.fetchall():
                if row[1] is not None:
                    volume_counts[row[0]] = row[1]
        conn.close()
    except Exception as e:
        return JsonResponse({"success": False, "error": f"CV DB error: {e}"}, status=500)

    updated = 0
    for comic in comics:
        vid = comic.custom_values.get("comicvine_volume")
        if not vid:
            continue
        count = volume_counts.get(int(vid))
        if count is not None and comic.count != count:
            comic.count = count
            comic.custom_values["comicvine_issue_count"] = str(count)
            comic.save(update_fields=["count", "custom_values"])
            updated += 1

    # Re-run mismatch detection to clear resolved flags
    _detect_count_mismatches()

    return JsonResponse({
        "success": True,
        "updated": updated,
        "message": f"Updated {updated} comic{'s' if updated != 1 else ''} from CV DB, re-ran mismatch detection",
    })


@require_POST
def detect_format_conflicts(request):
    """Detect and flag format mismatches within volumes and CV volume conflicts."""
    result = _detect_format_conflicts()
    return JsonResponse({
        "success": True,
        "message": (
            f"Format mismatches: {result['conflicting_volumes']} volumes "
            f"({result['flagged_format_mismatch']} flagged, {result['cleared_format_mismatch']} cleared). "
            f"CV volume conflicts: {result['conflicting_groups']} groups "
            f"({result['flagged_cv_conflict']} flagged, {result['cleared_cv_conflict']} cleared)."
        ),
        **result,
    })


@require_POST
def reformat_flagged(request):
    """
    Re-run format detection only on comics with needs_reformat=True.
    Does not touch comics in 'tagged' state — only fixes flagged upgrades.
    """
    from apps.core.services import detect_and_set_format

    comics = list(Comic.objects.filter(needs_reformat=True))
    processed = 0
    for comic in comics:
        detect_and_set_format(comic)
        processed += 1

    return JsonResponse({
        "success": True,
        "processed": processed,
        "message": f"Re-formatted {processed} comic{'s' if processed != 1 else ''}",
    })


@require_POST
def detect_format_upgrades(request):
    """
    Scan all comics with a count set and a count-based format (not format_ok).
    Sets needs_reformat=True for any comic where the expected format differs from current.
    Clears it for comics that are already on the right format.
    """
    from .models import get_setting

    one_shot_max = get_setting("one_shot_max_count", 1)
    limited_max = get_setting("limited_series_max_count", 15)

    candidates = Comic.objects.filter(
        count__isnull=False,
        format__in=Comic.COUNT_BASED_FORMATS,
        format_ok=False,
    )

    flagged = 0
    cleared = 0

    for comic in candidates:
        expected = (
            "One-Shot" if comic.count <= one_shot_max
            else "Limited Series" if comic.count <= limited_max
            else "Main Series"
        )
        if comic.format != expected:
            if not comic.needs_reformat:
                comic.needs_reformat = True
                comic.save(update_fields=["needs_reformat"])
                flagged += 1
        else:
            if comic.needs_reformat:
                comic.needs_reformat = False
                comic.save(update_fields=["needs_reformat"])
                cleared += 1

    return JsonResponse({
        "success": True,
        "flagged": flagged,
        "cleared": cleared,
        "message": f"Format upgrades: {flagged} flagged, {cleared} cleared",
    })


@require_POST
def accept_flag_view(request, pk):
    """Permanently suppress a flag for a specific comic."""
    comic = get_object_or_404(Comic, pk=pk)
    flag = request.POST.get("flag", "").strip()
    if not flag:
        return JsonResponse({"success": False, "error": "No flag specified"}, status=400)
    comic.accept_flag(flag)
    comic.save(update_fields=["flags", "accepted_flags"])
    # Return empty HTML so HTMX outerHTML swap removes the row cleanly
    from django.http import HttpResponse
    return HttpResponse("")


@require_POST
def unaccept_flag_view(request, pk):
    """Remove the suppression for a flag on a specific comic."""
    comic = get_object_or_404(Comic, pk=pk)
    flag = request.POST.get("flag", "").strip()
    if not flag:
        return JsonResponse({"success": False, "error": "No flag specified"}, status=400)
    comic.unaccept_flag(flag)
    comic.save(update_fields=["accepted_flags"])
    return JsonResponse({"success": True})


@require_POST
def populate_counts(request):
    """Populate missing issue counts from the CV SQLite DB."""
    result = _populate_missing_counts()
    return JsonResponse({
        "success": True,
        "populated": result["populated"],
        "failed": result["failed"],
        "total": result["total"],
        "message": f"Populated {result['populated']} counts, {result['failed']} still missing",
    })


@require_POST
def detect_count_mismatches(request):
    """Detect and flag comics with count mismatches within volumes."""
    result = _detect_count_mismatches()
    return JsonResponse({
        "success": True,
        "mismatched_volumes": result["mismatched_volumes"],
        "flagged": result["flagged"],
        "cleared": result["cleared"],
        "message": f"Found {result['mismatched_volumes']} volumes with count mismatches",
    })


@require_POST
def populate_counts_all(request):
    """Dispatch Celery task to populate missing counts and detect mismatches."""
    from celery.result import AsyncResult
    from .tasks import populate_counts_task

    active = request.session.get("active_task_id")
    if active and AsyncResult(active).state in ("PENDING", "STARTED", "PROGRESS"):
        return JsonResponse({"success": False, "error": "A task is already running", "task_id": active}, status=409)

    total = Comic.objects.filter(count__isnull=True).exclude(
        custom_values__comicvine_volume__isnull=True,
    ).exclude(custom_values__comicvine_volume="").count()

    result = populate_counts_task.delay()
    request.session["active_task_id"] = result.id
    request.session["active_task_label"] = "Populating counts"
    return JsonResponse({"success": True, "task_id": result.id, "total": total, "message": f"Populating counts for {total} comics in background"})


# =============================================================================
# Phase 4: DataManager Tagging (Publisher Management)
# =============================================================================


@require_POST
def tag_comic(request, pk):
    """
    Apply DataManager rules to a single comic.

    This is Phase 4 of the workflow: counted -> tagged
    """
    from apps.tagging.services import tag_comic as tagging_service_tag_comic

    comic = get_object_or_404(Comic, pk=pk)

    result = tagging_service_tag_comic(comic)

    if not result["success"]:
        return JsonResponse({
            "success": False,
            "error": result["message"]
        }, status=400)

    return JsonResponse({
        "success": True,
        "message": result["message"],
        "matched_rulesets": result["matched_rulesets"],
        "changes": result["changes"],
        "changes_count": len(result["changes"]),
        "state": comic.state,
    })


@require_POST
def tag_all_comics(request):
    """
    Dispatch a Celery task to apply DataManager rules to all comics in 'counted' state.
    """
    from celery.result import AsyncResult
    from .tasks import tag_all_task

    active = request.session.get("active_task_id")
    if active and AsyncResult(active).state in ("PENDING", "STARTED", "PROGRESS"):
        return JsonResponse({"success": False, "error": "A task is already running", "task_id": active}, status=409)

    total = Comic.objects.filter(state=Comic.STATE_COUNTED).count()
    result = tag_all_task.delay()
    request.session["active_task_id"] = result.id
    request.session["active_task_label"] = "Tagging comics"
    return JsonResponse({"success": True, "task_id": result.id, "total": total, "message": f"Tagging {total} comics in background"})


@require_POST
def retag_flagged(request):
    """
    Dispatch a Celery task to re-tag all comics with a specific flag.
    """
    from celery.result import AsyncResult
    from .tasks import retag_flagged_task

    flag = request.POST.get("flag", "").strip()
    if not flag:
        return JsonResponse({"success": False, "error": "No flag specified"}, status=400)

    active = request.session.get("active_task_id")
    if active and AsyncResult(active).state in ("PENDING", "STARTED", "PROGRESS"):
        return JsonResponse({"success": False, "error": "A task is already running", "task_id": active}, status=409)

    total = Comic.objects.filter(**{f"flags__{flag}": True}).count()
    result = retag_flagged_task.delay(flag)
    request.session["active_task_id"] = result.id
    request.session["active_task_label"] = f"Re-tagging {flag} comics"
    return JsonResponse({"success": True, "task_id": result.id, "total": total, "message": f"Re-tagging {total} comics in background"})


def tag_preview(request, pk):
    """
    Preview which DataManager rules would match a comic.

    Returns matching rulesets and their potential changes without applying them.
    """
    from apps.tagging.services import preview_tagging

    comic = get_object_or_404(Comic, pk=pk)
    preview = preview_tagging(comic)

    return JsonResponse({
        "success": True,
        **preview,
    })


# =============================================================================
# Phase 5: Format Detection (TPB, Annual, etc.)
# =============================================================================

from .services import detect_format as _detect_format, OMNIBUS_MIN_PAGES, TPB_MIN_PAGES, TPB_ISSUE_RANGE_RE


def _apply_format_detection(comic):
    """
    Apply format detection to a comic.

    This is Phase 5 of the workflow: tagged -> formatted
    """
    detected_format = _detect_format(comic)
    if detected_format:
        comic.format = detected_format
        comic.flags.pop("missing_format", None)
    elif not comic.format:
        comic.flags["missing_format"] = True

    if comic.medium == Comic.MEDIUM_PHYSICAL:
        comic.state = Comic.STATE_WRITTEN
    else:
        comic.state = Comic.STATE_FORMATTED
    comic.save()


@require_POST
def format_comic(request, pk):
    """
    Apply format detection to a single comic.

    This is Phase 5 of the workflow: tagged -> formatted
    """
    comic = get_object_or_404(Comic, pk=pk)

    if comic.state != Comic.STATE_TAGGED:
        return JsonResponse({
            "success": False,
            "error": f"Comic is not in 'tagged' state (current: {comic.state})"
        }, status=400)

    old_format = comic.format
    detected_format = _detect_format(comic)

    if detected_format:
        comic.format = detected_format
        comic.flags.pop("missing_format", None)
    elif not comic.format:
        comic.flags["missing_format"] = True

    if comic.medium == Comic.MEDIUM_PHYSICAL:
        comic.state = Comic.STATE_WRITTEN
    else:
        comic.state = Comic.STATE_FORMATTED
    comic.save()

    _text = f"{comic.series or ''} {comic.title or ''}"
    _summary = comic.summary or ""
    _pages = comic.page_count or 0
    patterns_checked = [
        {"pattern": "Director's Cut (text)", "matched": detected_format == "Director's Cut"},
        {"pattern": "Black & White (text)", "matched": detected_format == "Black & White"},
        {"pattern": "Omnibus (keyword in title/summary)", "matched": detected_format == "Omnibus" and bool(re.search(r"\bOmnibus\b", _text + " " + _summary, re.IGNORECASE))},
        {"pattern": f"Omnibus (≥{OMNIBUS_MIN_PAGES} pages, no TPB signals)", "matched": detected_format == "Omnibus" and _pages >= OMNIBUS_MIN_PAGES and not re.search(r"\bOmnibus\b", _text + " " + _summary, re.IGNORECASE)},
        {"pattern": "TPB (keyword)", "matched": detected_format == "TPB" and bool(re.search(r"\bTPB\b|\bTrade Paperback\b", _text, re.IGNORECASE))},
        {"pattern": f"TPB (≥{TPB_MIN_PAGES} pages + issue range in summary)", "matched": detected_format == "TPB" and _pages >= TPB_MIN_PAGES and bool(TPB_ISSUE_RANGE_RE.search(_summary))},
        {"pattern": "Annual (keyword)", "matched": detected_format == "Annual"},
        {"pattern": "One-Shot (count=1)", "matched": detected_format == "One-Shot"},
        {"pattern": "Limited Series (count 2-15)", "matched": detected_format == "Limited Series"},
        {"pattern": "Main Series (count>15)", "matched": detected_format == "Main Series"},
    ]

    return JsonResponse({
        "success": True,
        "old_format": old_format,
        "new_format": comic.format,
        "detected_format": detected_format,
        "format_changed": old_format != comic.format,
        "patterns_checked": patterns_checked,
        "series": comic.series,
        "title": comic.title,
        "count": comic.count,
        "page_count": comic.page_count,
        "state": comic.state,
    })


@require_POST
def format_all_comics(request):
    """
    Dispatch a Celery task to apply format detection to all comics in 'tagged' state.
    """
    from celery.result import AsyncResult
    from .tasks import format_all_task

    active = request.session.get("active_task_id")
    if active and AsyncResult(active).state in ("PENDING", "STARTED", "PROGRESS"):
        return JsonResponse({"success": False, "error": "A task is already running", "task_id": active}, status=409)

    total = Comic.objects.filter(state=Comic.STATE_TAGGED).count()
    result = format_all_task.delay()
    request.session["active_task_id"] = result.id
    request.session["active_task_label"] = "Formatting comics"
    return JsonResponse({"success": True, "task_id": result.id, "total": total, "message": f"Formatting {total} comics in background"})


# Format types in display order: (display_name, url_slug)
FORMAT_DISPLAY_ORDER = [
    ("TPB", "tpb"),
    ("Omnibus", "omnibus"),
    ("Director's Cut", "directors-cut"),
    ("Black & White", "black-and-white"),
    ("Annual", "annual"),
    ("One-Shot", "one-shot"),
    ("Limited Series", "limited-series"),
    ("Main Series", "main-series"),
    (None, "unknown"),  # No format detected
]

# Reverse mapping: slug -> format name
FORMAT_SLUG_TO_NAME = {slug: name for name, slug in FORMAT_DISPLAY_ORDER}


def format_review(request):
    """
    Display grouped format review page.

    Shows all comics in 'tagged' state grouped by their detected format,
    plus any comics needing re-format (from any state).
    """
    from collections import defaultdict

    # Get comics in 'tagged' state
    tagged_comics = Comic.objects.filter(state=Comic.STATE_TAGGED).annotate(
        number_sort_key=natural_number_annotation()
    ).order_by("series", "volume", "number_sort_key", "number")

    # Get comics needing re-format (any state)
    reformat_comics = list(Comic.objects.filter(needs_reformat=True).annotate(
        number_sort_key=natural_number_annotation()
    ).order_by("series", "volume", "number_sort_key", "number"))

    # Group tagged comics by detected format
    grouped = defaultdict(list)
    for comic in tagged_comics:
        detected = _detect_format(comic)
        grouped[detected].append(comic)

    # Build format groups in display order with comics included
    format_groups = []
    for format_name, slug in FORMAT_DISPLAY_ORDER:
        comics = grouped.get(format_name, [])
        if comics:
            # Determine if this is a count-based or text-based format
            is_count_based = format_name in Comic.COUNT_BASED_FORMATS if format_name else False
            format_groups.append({
                "name": format_name or "Unknown",
                "slug": slug,
                "count": len(comics),
                "comics": comics,
                "is_count_based": is_count_based,
            })

    # Build re-format group if any
    reformat_group = None
    if reformat_comics:
        reformat_group = {
            "name": "Needs Re-format",
            "slug": "needs-reformat",
            "count": len(reformat_comics),
            "comics": reformat_comics,
        }

    return render(request, "core/format_review.html", {
        "format_groups": format_groups,
        "reformat_group": reformat_group,
        "total_tagged": tagged_comics.count(),
        "total_reformat": len(reformat_comics),
    })


def format_group_comics(request, format_type):
    """
    HTMX partial: return comics table for a format group.
    """
    format_name = FORMAT_SLUG_TO_NAME.get(format_type)

    if format_type == "needs-reformat":
        comics = Comic.objects.filter(needs_reformat=True).annotate(
            number_sort_key=natural_number_annotation()
        ).order_by("series", "number_sort_key", "number")
    else:
        # Get tagged comics and filter by detected format
        tagged_comics = Comic.objects.filter(state=Comic.STATE_TAGGED)
        comics = [c for c in tagged_comics if _detect_format(c) == format_name]
        comics.sort(key=natural_sort_key)

    return render(request, "core/partials/format_group_comics.html", {
        "comics": comics,
        "format_type": format_type,
    })


@require_POST
def accept_format_group(request, format_type):
    """
    Accept all comics of a specific format type.

    For regular formats: applies the format and advances to STATE_FORMATTED.
    For "needs-reformat": recalculates format and clears the flag.
    """
    format_name = FORMAT_SLUG_TO_NAME.get(format_type)

    if format_type == "needs-reformat":
        # Handle re-format: recalculate and clear flag
        comics = Comic.objects.filter(needs_reformat=True)
        processed = 0
        for comic in comics:
            new_format = _detect_format(comic)
            if new_format:
                comic.format = new_format
            comic.needs_reformat = False
            comic.save()
            processed += 1

        return render(request, "core/partials/format_accepted.html", {
            "processed": processed,
            "format": "Re-formatted",
            "is_reformat": True,
        })

    # Regular format acceptance
    tagged_comics = Comic.objects.filter(state=Comic.STATE_TAGGED)

    processed = 0
    for comic in tagged_comics:
        detected = _detect_format(comic)
        # Only process comics matching this format type
        if detected == format_name:
            if format_name:
                comic.format = format_name
            if comic.medium == Comic.MEDIUM_PHYSICAL:
                comic.state = Comic.STATE_WRITTEN
            else:
                comic.state = Comic.STATE_FORMATTED
            comic.save()
            processed += 1

    return render(request, "core/partials/format_accepted.html", {
        "processed": processed,
        "format": format_name or "Unknown",
        "is_reformat": False,
    })


# =============================================================================
# Comic Detail / Edit Views
# =============================================================================

def comic_edit(request, pk):
    """
    Edit a comic's metadata.

    GET: Display edit form
    POST: Save changes to DB. Writes ComicInfo.xml only if write_xml=1 is submitted.
    """
    from django.contrib import messages
    from .utils import (
        read_comicinfo_xml,
        compare_db_vs_xml,
        update_comic_from_form,
        write_comicinfo_xml,
        EDITABLE_FIELDS,
        _STANDARD_XML_FIELDS,
    )

    comic = get_object_or_404(Comic, pk=pk)

    if request.method == "POST":
        # Clear flags submitted for removal
        for flag_key in request.POST.getlist("clear_flag"):
            if flag_key in FLAG_LABELS:
                comic.remove_flag(flag_key)

        # Update standard fields from form data
        update_comic_from_form(comic, request.POST)

        # Handle format_ok toggle (checkbox — present means True, absent means False)
        comic.format_ok = "format_ok" in request.POST

        # Handle state reset
        new_state = request.POST.get("state")
        if new_state and new_state in dict(Comic.STATE_CHOICES):
            comic.state = new_state

        # Rebuild custom_values: keep standard XML keys untouched, replace display keys
        standard_values = {
            k: v for k, v in (comic.custom_values or {}).items()
            if k in _STANDARD_XML_FIELDS
        }
        new_custom = dict(standard_values)

        # Existing rows: cv_key_N / cv_val_N; skip if cv_delete_N is set
        i = 0
        while True:
            key = request.POST.get(f"cv_key_{i}")
            if key is None:
                break
            if not request.POST.get(f"cv_delete_{i}"):
                val = request.POST.get(f"cv_val_{i}", "")
                if key.strip():
                    new_custom[key.strip()] = val
            i += 1

        # New rows: new_cv_key_N / new_cv_val_N
        j = 0
        while True:
            key = request.POST.get(f"new_cv_key_{j}", "").strip()
            if not key:
                break
            new_custom[key] = request.POST.get(f"new_cv_val_{j}", "")
            j += 1

        comic.custom_values = new_custom
        comic.save()

        # Write ComicInfo.xml only when explicitly requested
        xml_updated = False
        if request.POST.get("write_xml") == "1":
            if comic.is_digital and comic.file_path and comic.file_path.lower().endswith('.cbz'):
                xml_updated = write_comicinfo_xml(comic.file_path, comic)

        if xml_updated:
            messages.success(request, "Comic updated successfully (database and ComicInfo.xml).")
        else:
            messages.success(request, "Comic saved to database.")

        # Redirect back to detail page
        from django.shortcuts import redirect
        return redirect("core:detail", pk=comic.pk)

    # GET: Load current data for comparison
    xml_data = None
    comparison = None

    if comic.is_digital and comic.file_path:
        if comic.file_path.lower().endswith('.cbz'):
            xml_data = read_comicinfo_xml(comic.file_path)
            if xml_data is not None:
                comparison = compare_db_vs_xml(comic, xml_data)

    # Build list of editable custom values (exclude standard XML fields)
    custom_values_list = [
        (k, v) for k, v in (comic.custom_values or {}).items()
        if k not in _STANDARD_XML_FIELDS
    ]

    # Build list of active flags with labels for the UI
    active_flags = [
        (key, FLAG_LABELS.get(key, key))
        for key in (comic.flags or {})
        if comic.flags[key]
    ]

    return render(request, "core/comic_edit.html", {
        "comic": comic,
        "xml_data": xml_data,
        "comparison": comparison,
        "editable_fields": EDITABLE_FIELDS,
        "custom_values_list": custom_values_list,
        "state_choices": Comic.STATE_CHOICES,
        "active_flags": active_flags,
    })


# =============================================================================
# Phase 6-8: Deduplicate, Organize, Write
# =============================================================================

@require_POST
def deduplicate_all_comics(request):
    """
    Dispatch a Celery task to run duplicate detection on all formatted comics.
    """
    from celery.result import AsyncResult
    from .tasks import deduplicate_all_task

    active = request.session.get("active_task_id")
    if active and AsyncResult(active).state in ("PENDING", "STARTED", "PROGRESS"):
        return JsonResponse({"success": False, "error": "A task is already running", "task_id": active}, status=409)

    total = Comic.objects.filter(state=Comic.STATE_FORMATTED).count()
    result = deduplicate_all_task.delay()
    request.session["active_task_id"] = result.id
    request.session["active_task_label"] = "Deduplicating"
    return JsonResponse({"success": True, "task_id": result.id, "total": total, "message": f"Running deduplication on {total} comics in background"})


@require_POST
def organize_comic(request, pk):
    """
    Organize a single comic - move file to library location.

    This is Phase 7 of the workflow: deduplicated -> organized
    """
    from apps.organizer.services import organize_comic as organizer_service_organize

    comic = get_object_or_404(Comic, pk=pk)

    result = organizer_service_organize(comic)

    if not result["success"]:
        return JsonResponse({
            "success": False,
            "error": result["message"]
        }, status=400)

    return JsonResponse({
        "success": True,
        "message": result["message"],
        "profile": result["profile"],
        "old_path": result["old_path"],
        "new_path": result["new_path"],
        "moved": result["moved"],
        "state": comic.state,
    })


@require_POST
def organize_all_comics(request):
    """
    Dispatch a Celery task to organize all comics in 'deduplicated' state.
    """
    from celery.result import AsyncResult
    from .tasks import organize_all_task

    active = request.session.get("active_task_id")
    if active and AsyncResult(active).state in ("PENDING", "STARTED", "PROGRESS"):
        return JsonResponse({"success": False, "error": "A task is already running", "task_id": active}, status=409)

    total = Comic.objects.filter(state=Comic.STATE_DEDUPLICATED).count()
    result = organize_all_task.delay()
    request.session["active_task_id"] = result.id
    request.session["active_task_label"] = "Organizing comics"
    return JsonResponse({"success": True, "task_id": result.id, "total": total, "message": f"Organizing {total} comics in background"})


@require_POST
def reorganize_comic(request, pk):
    """
    Re-organize a comic that's already been organized or written.

    This allows moving a comic to a new location if its metadata
    (like format, series_group, etc.) has changed after organization.
    """
    from apps.organizer.services import reorganize_comic as service_reorganize

    comic = get_object_or_404(Comic, pk=pk)

    if comic.state not in (Comic.STATE_ORGANIZED, Comic.STATE_WRITTEN):
        return JsonResponse({
            "success": False,
            "error": f"Comic must be in 'organized' or 'written' state (current: {comic.state})"
        }, status=400)

    result = service_reorganize(comic)

    if not result["success"]:
        return JsonResponse({
            "success": False,
            "error": result.get("error", "Unknown error"),
        }, status=500)

    return JsonResponse({
        "success": True,
        "message": result.get("message", "Comic reorganized successfully") if not result.get("moved") else "Comic reorganized successfully",
        "old_path": result.get("old_path"),
        "new_path": result.get("new_path"),
        "moved": result.get("moved", False),
        "profile": result.get("profile"),
    })


@require_POST
def sync_library_paths(request):
    """
    Sync database file paths with actual filesystem locations.

    Finds comics where file_path doesn't exist on disk, computes the
    organizer's target path, and updates the DB if the file is found there.
    """
    from apps.organizer.services import sync_library_paths as organizer_sync

    result = organizer_sync()

    return JsonResponse({
        "success": result["success"],
        "message": result["message"],
        "total": result["total"],
        "synced": result["synced"],
        "removed_dupes": result["removed_dupes"],
        "already_ok": result["already_ok"],
        "not_found": result["not_found"],
        "errors": result["errors"],
    })


@require_POST
def rewrite_updated_comics(request):
    """
    Dispatch a Celery task to rewrite ComicInfo.xml for all comics
    with the count_updated flag. Returns immediately with a task ID.
    """
    from celery.result import AsyncResult

    # Prevent double-submit (shares session key with write-all)
    active_task_id = request.session.get("write_task_id")
    if active_task_id:
        result = AsyncResult(active_task_id)
        if result.state in ("PENDING", "STARTED", "PROGRESS"):
            return JsonResponse({
                "success": False,
                "error": "A write task is already running",
                "task_id": active_task_id,
            }, status=409)

    count = Comic.objects.filter(
        flags__count_updated=True,
        medium=Comic.MEDIUM_DIGITAL,
    ).count()
    if count == 0:
        return JsonResponse({
            "success": True,
            "written": 0,
            "total": 0,
            "message": "No comics with count_updated flag",
        })

    from .tasks import rewrite_updated_comics_task
    result = rewrite_updated_comics_task.delay()
    request.session["write_task_id"] = result.id

    return JsonResponse({
        "success": True,
        "task_id": result.id,
        "total": count,
        "message": f"Started rewriting {count} comics in background",
    })


@require_POST
def write_comic(request, pk):
    """
    Write ComicInfo.xml for a single comic in 'organized' state.

    This updates the ComicInfo.xml inside the CBZ file with the
    current database values, then advances to 'written' state.
    """
    from .utils import write_comicinfo_xml, validate_comic_for_write
    from django.utils import timezone

    comic = get_object_or_404(Comic, pk=pk)

    if comic.state != Comic.STATE_ORGANIZED:
        return JsonResponse({
            "success": False,
            "error": f"Comic must be in 'organized' state (current: {comic.state})"
        }, status=400)

    validation_errors = validate_comic_for_write(comic)
    if validation_errors:
        return JsonResponse({
            "success": False,
            "error": f"Missing required fields: {', '.join(validation_errors)}",
        }, status=400)

    # For digital comics with CBZ files, write the XML
    if comic.is_digital and comic.file_path and comic.file_path.lower().endswith('.cbz'):
        success = write_comicinfo_xml(comic.file_path, comic)
        if not success:
            return JsonResponse({
                "success": False,
                "error": "Failed to write ComicInfo.xml"
            }, status=500)

    # Advance state and record write time
    from django.db.models import F
    comic.state = Comic.STATE_WRITTEN

    # Clear the count_updated flag if set
    if comic.flags.get("count_updated"):
        comic.flags.pop("count_updated", None)

    comic.save()
    # Sync last_written to updated_at so the comic is not immediately stale
    Comic.objects.filter(pk=comic.pk).update(last_written=F("updated_at"))

    return JsonResponse({
        "success": True,
        "message": "ComicInfo.xml written successfully",
        "state": comic.state,
    })


@require_POST
def write_all_comics(request):
    """
    Dispatch a Celery task to write ComicInfo.xml for all organized comics.
    Returns immediately with the task ID for progress polling.
    """
    from celery.result import AsyncResult

    # Prevent double-submit
    active_task_id = request.session.get("write_task_id")
    if active_task_id:
        result = AsyncResult(active_task_id)
        if result.state in ("PENDING", "STARTED", "PROGRESS"):
            return JsonResponse({
                "success": False,
                "error": "A write task is already running",
                "task_id": active_task_id,
            }, status=409)

    count = Comic.objects.filter(state=Comic.STATE_ORGANIZED).count()
    if count == 0:
        return JsonResponse({
            "success": True,
            "written": 0,
            "total": 0,
            "message": "No comics in organized state",
        })

    from .tasks import write_all_comics_task
    result = write_all_comics_task.delay()
    request.session["write_task_id"] = result.id

    return JsonResponse({
        "success": True,
        "task_id": result.id,
        "total": count,
        "message": f"Started writing {count} comics in background",
    })


@require_POST
def write_stale_comics(request):
    """
    Dispatch a Celery task to rewrite ComicInfo.xml for all stale written comics
    (state=written, updated_at > last_written).
    """
    from celery.result import AsyncResult
    from django.db.models import F

    active_task_id = request.session.get("write_task_id")
    if active_task_id:
        result = AsyncResult(active_task_id)
        if result.state in ("PENDING", "STARTED", "PROGRESS"):
            return JsonResponse({
                "success": False,
                "error": "A write task is already running",
                "task_id": active_task_id,
            }, status=409)

    count = Comic.objects.filter(
        state=Comic.STATE_WRITTEN,
        last_written__isnull=False,
    ).filter(updated_at__gt=F("last_written")).count()

    if count == 0:
        return JsonResponse({
            "success": True,
            "written": 0,
            "total": 0,
            "message": "No stale comics to write",
        })

    from .tasks import write_stale_comics_task
    result = write_stale_comics_task.delay()
    request.session["write_task_id"] = result.id

    return JsonResponse({
        "success": True,
        "task_id": result.id,
        "total": count,
        "message": f"Started writing {count} stale comic(s) in background",
    })


@require_POST
def write_missing_comics(request):
    """
    Dispatch a Celery task to write ComicInfo.xml for digital comics in 'written'
    state that have never had ComicInfo.xml written (last_written is null).
    """
    from celery.result import AsyncResult

    active_task_id = request.session.get("write_task_id")
    if active_task_id:
        result = AsyncResult(active_task_id)
        if result.state in ("PENDING", "STARTED", "PROGRESS"):
            return JsonResponse({
                "success": False,
                "error": "A write task is already running",
                "task_id": active_task_id,
            }, status=409)

    count = Comic.objects.filter(
        state=Comic.STATE_WRITTEN,
        medium=Comic.MEDIUM_DIGITAL,
        last_written__isnull=True,
    ).count()

    if count == 0:
        return JsonResponse({
            "success": True,
            "written": 0,
            "total": 0,
            "message": "No missing ComicInfo.xml to write",
        })

    from .tasks import write_missing_comics_task
    result = write_missing_comics_task.delay()
    request.session["write_task_id"] = result.id

    return JsonResponse({
        "success": True,
        "task_id": result.id,
        "total": count,
        "message": f"Started writing {count} comic(s) missing ComicInfo.xml in background",
    })


@require_GET
def task_progress(request, task_id):
    """
    Poll endpoint for Celery task progress.
    Returns current state and progress metadata.
    """
    from celery.result import AsyncResult

    result = AsyncResult(task_id)
    response = {"task_id": task_id, "state": result.state}

    if result.state == "PROGRESS":
        info = result.info or {}
        response.update(info)
        response["current"] = info.get("current", 0)
        response["total"] = info.get("total", 0)
    elif result.state == "SUCCESS":
        response["result"] = result.result
        _clear_task_session(request, task_id)
    elif result.state == "FAILURE":
        response["error"] = str(result.result)
        _clear_task_session(request, task_id)
    elif result.state == "STARTED":
        response.update({"current": 0, "total": 0})

    return JsonResponse(response)


def _clear_task_session(request, task_id):
    """Remove a completed/failed task ID from all session slots."""
    session_keys = (
        "write_task_id",
        "audit_task_id",
        "reorganize_task_id",
        "smartlist_action_task_id",
        "active_task_id",
    )
    for key in session_keys:
        if request.session.get(key) == task_id:
            del request.session[key]
            if key == "active_task_id":
                request.session.pop("active_task_label", None)


@require_POST
def cancel_task(request, task_id):
    """
    Request cooperative cancellation of a running Celery task.
    Sets a Redis flag that tasks check before processing each item.
    """
    from .tasks import request_cancel
    request_cancel(task_id)
    return JsonResponse({"success": True})


# =============================================================================
# Force Actions - Allow re-running workflow steps on any comic
# =============================================================================

@require_POST
def force_scrape(request, pk):
    """
    Force re-scrape a comic against ComicVine, regardless of current state.
    Uses the stored comicvine_issue ID if available, otherwise tries matching.
    """
    comic = get_object_or_404(Comic, pk=pk)

    from apps.scraper.cv_sources import is_cv_db_available

    scraper = ComicVineScraper()
    match = None

    # If we have a stored CV issue ID, use it directly
    cv_issue_id = comic.custom_values.get("comicvine_issue")
    if cv_issue_id:
        if is_cv_db_available():
            match = scraper.get_issue_details(int(cv_issue_id))
        if not match:
            match = scraper.get_issue_from_api(int(cv_issue_id))
        if match:
            match.match_type = "refresh"

    # Otherwise find the best match using the unified strategy (DB or API)
    if not match:
        match = _find_best_match(comic, scraper)

    if not match:
        return JsonResponse({
            "success": False,
            "error": "No match found in ComicVine database"
        }, status=404)

    # Apply the match (this also enriches with credits)
    _apply_match(comic, match, scraper)

    return JsonResponse({
        "success": True,
        "message": f"Re-scraped: {match.series} #{match.issue_number}",
        "new_state": comic.state,
    })


@require_POST
def force_tag(request, pk):
    """
    Force re-tag a comic with DataManager rules, regardless of current state.

    Unlike the normal tag_comic service, this bypasses the state check
    and applies rules to comics in any state.
    """
    from apps.tagging.engine import apply_datamanager_rules

    comic = get_object_or_404(Comic, pk=pk)

    # Apply tagging rules directly (bypassing state check)
    result = apply_datamanager_rules(comic, save=False)

    # Mark as processed by DataManager
    comic.custom_values["DataManager_Processed"] = "Yes"

    # Clear unknown_publisher if this publisher is now covered by a ruleset
    if comic.publisher and comic.has_flag("unknown_publisher"):
        from apps.tagging.engine import is_publisher_known
        if is_publisher_known(comic.publisher):
            comic.remove_flag("unknown_publisher")

    # Advance state if needed (to at least tagged)
    if comic.state in (Comic.STATE_NEW, Comic.STATE_IMPORTED, Comic.STATE_SCRAPED, Comic.STATE_COUNTED):
        comic.state = Comic.STATE_TAGGED

    comic.save()

    matched_count = result.get("matched_count", len(result.get("matched_rulesets", [])))
    changes_count = result.get("changes_count", len(result.get("changes", [])))

    if matched_count > 0:
        message = f"Applied {matched_count} ruleset(s), made {changes_count} change(s)"
    else:
        message = "No matching rulesets found"

    return JsonResponse({
        "success": True,
        "message": message,
        "matched_rulesets": result.get("matched_rulesets", []),
        "changes": result.get("changes", []),
        "new_state": comic.state,
    })


@require_POST
def force_format(request, pk):
    """
    Force re-detect format for a comic, regardless of current state.
    """
    from .services import detect_and_set_format

    comic = get_object_or_404(Comic, pk=pk)
    result = detect_and_set_format(comic)
    detected = result["detected_format"]

    _text = f"{comic.series or ''} {comic.title or ''}"
    _summary = comic.summary or ""
    _pages = comic.page_count or 0
    patterns_checked = [
        {"pattern": "Director's Cut (text)", "matched": detected == "Director's Cut"},
        {"pattern": "Black & White (text)", "matched": detected == "Black & White"},
        {"pattern": "Omnibus (keyword in title/summary)", "matched": detected == "Omnibus" and bool(re.search(r"\bOmnibus\b", _text + " " + _summary, re.IGNORECASE))},
        {"pattern": f"Omnibus (≥{OMNIBUS_MIN_PAGES} pages, no TPB signals)", "matched": detected == "Omnibus" and _pages >= OMNIBUS_MIN_PAGES and not re.search(r"\bOmnibus\b", _text + " " + _summary, re.IGNORECASE)},
        {"pattern": "TPB (keyword)", "matched": detected == "TPB" and bool(re.search(r"\bTPB\b|\bTrade Paperback\b", _text, re.IGNORECASE))},
        {"pattern": f"TPB (≥{TPB_MIN_PAGES} pages + issue range in summary)", "matched": detected == "TPB" and _pages >= TPB_MIN_PAGES and bool(TPB_ISSUE_RANGE_RE.search(_summary))},
        {"pattern": "Annual (keyword)", "matched": detected == "Annual"},
        {"pattern": "One-Shot (count=1)", "matched": detected == "One-Shot"},
        {"pattern": "Limited Series (count 2-15)", "matched": detected == "Limited Series"},
        {"pattern": "Main Series (count>15)", "matched": detected == "Main Series"},
    ]

    return JsonResponse({
        "success": True,
        "message": f"Format: {comic.format or 'None'}",
        "old_format": result["old_format"],
        "new_format": result["new_format"],
        "detected_format": detected,
        "format_changed": result["format_changed"],
        "patterns_checked": patterns_checked,
        "series": comic.series,
        "title": comic.title,
        "count": comic.count,
        "page_count": comic.page_count,
        "new_state": comic.state,
    })


@require_POST
def force_organize(request, pk):
    """
    Force re-organize a comic (move to correct library path), regardless of current state.
    """
    from apps.organizer.services import preview_organization, LIBRARY_BASE
    import shutil

    comic = get_object_or_404(Comic, pk=pk)

    if not comic.is_digital or not comic.file_path:
        return JsonResponse({
            "success": False,
            "error": "Cannot organize physical comics or comics without file path"
        }, status=400)

    # Verify file exists
    if not os.path.exists(comic.file_path):
        return JsonResponse({
            "success": False,
            "error": f"File not found: {comic.file_path}"
        }, status=400)

    # Get the preview to determine destination path
    try:
        preview = preview_organization(comic)
    except Exception as e:
        return JsonResponse({
            "success": False,
            "error": f"Failed to calculate destination: {str(e)}"
        }, status=500)

    old_path = comic.file_path
    new_path = preview["new_path"]

    # Check if file needs to move
    if os.path.abspath(old_path) == os.path.abspath(new_path):
        # Still advance state even if no move needed
        if comic.state in (Comic.STATE_NEW, Comic.STATE_IMPORTED, Comic.STATE_SCRAPED,
                           Comic.STATE_COUNTED, Comic.STATE_TAGGED, Comic.STATE_FORMATTED,
                           Comic.STATE_DEDUPLICATED):
            comic.state = Comic.STATE_ORGANIZED
            comic.save()
        return JsonResponse({
            "success": True,
            "message": "File is already in the correct location",
            "moved": False,
            "old_path": old_path,
            "new_path": new_path,
            "profile": preview.get("selected_profile", "(fallback)"),
            "new_state": comic.state,
        })

    # Perform the move
    try:
        # Create destination directory
        new_folder = os.path.dirname(new_path)
        os.makedirs(new_folder, exist_ok=True)

        # Handle collision
        if os.path.exists(new_path):
            base, ext = os.path.splitext(new_path)
            counter = 1
            while os.path.exists(new_path):
                new_path = f"{base}_{counter}{ext}"
                counter += 1

        # Move the file
        shutil.move(old_path, new_path)

        # Try to remove empty source directories
        try:
            old_dir = os.path.dirname(old_path)
            while old_dir and old_dir != LIBRARY_BASE and old_dir != "/comics/untagged":
                if os.path.isdir(old_dir) and not os.listdir(old_dir):
                    os.rmdir(old_dir)
                    old_dir = os.path.dirname(old_dir)
                else:
                    break
        except OSError:
            pass  # Ignore errors when cleaning up directories

        # Update comic record
        comic.file_path = new_path
        comic.last_organized_path = new_path
        # Advance state if needed (to at least organized)
        if comic.state in (Comic.STATE_NEW, Comic.STATE_IMPORTED, Comic.STATE_SCRAPED,
                           Comic.STATE_COUNTED, Comic.STATE_TAGGED, Comic.STATE_FORMATTED,
                           Comic.STATE_DEDUPLICATED):
            comic.state = Comic.STATE_ORGANIZED
        comic.save()

        return JsonResponse({
            "success": True,
            "message": "Comic organized",
            "moved": True,
            "old_path": old_path,
            "new_path": new_path,
            "profile": preview.get("selected_profile", "(fallback)"),
            "new_state": comic.state,
        })

    except Exception as e:
        return JsonResponse({
            "success": False,
            "error": f"Failed to move file: {str(e)}"
        }, status=500)


@require_POST
def refresh_credits(request, pk):
    """
    Refresh credits from ComicVine database without re-scraping other metadata.
    """
    comic = get_object_or_404(Comic, pk=pk)

    cv_issue_id = comic.custom_values.get("comicvine_issue")
    if not cv_issue_id:
        return JsonResponse({
            "success": False,
            "error": "No ComicVine issue ID stored for this comic"
        }, status=400)

    scraper = ComicVineScraper()
    match = scraper.get_issue_details(int(cv_issue_id))

    if not match:
        return JsonResponse({
            "success": False,
            "error": f"Issue {cv_issue_id} not found in ComicVine database"
        }, status=404)

    # Update only credits and web URL
    changes = []

    if match.characters and match.characters != comic.characters:
        comic.characters = match.characters
        changes.append("characters")
    if match.writer and match.writer != comic.writer:
        comic.writer = match.writer
        changes.append("writer")
    if match.penciller and match.penciller != comic.penciller:
        comic.penciller = match.penciller
        changes.append("penciller")
    if match.inker and match.inker != comic.inker:
        comic.inker = match.inker
        changes.append("inker")
    if match.colorist and match.colorist != comic.colorist:
        comic.colorist = match.colorist
        changes.append("colorist")
    if match.letterer and match.letterer != comic.letterer:
        comic.letterer = match.letterer
        changes.append("letterer")
    if match.cover_artist and match.cover_artist != comic.cover_artist:
        comic.cover_artist = match.cover_artist
        changes.append("cover_artist")
    if match.editor and match.editor != comic.editor:
        comic.editor = match.editor
        changes.append("editor")
    if match.web and match.web != comic.web:
        comic.web = match.web
        changes.append("web")

    comic.save()

    return JsonResponse({
        "success": True,
        "message": f"Updated {len(changes)} field(s)" if changes else "No changes needed",
        "changes": changes,
    })


@require_POST
def force_write(request, pk):
    """
    Force write ComicInfo.xml for a comic, regardless of current state.
    """
    from .utils import write_comicinfo_xml
    from django.utils import timezone

    comic = get_object_or_404(Comic, pk=pk)

    if not comic.is_digital:
        return JsonResponse({
            "success": False,
            "error": "Cannot write to physical comics"
        }, status=400)

    if not comic.file_path or not comic.file_path.lower().endswith('.cbz'):
        return JsonResponse({
            "success": False,
            "error": "Comic has no CBZ file"
        }, status=400)

    success = write_comicinfo_xml(comic.file_path, comic)
    if not success:
        return JsonResponse({
            "success": False,
            "error": "Failed to write ComicInfo.xml"
        }, status=500)

    # Advance state to written
    from django.db.models import F
    if comic.state != Comic.STATE_WRITTEN:
        comic.state = Comic.STATE_WRITTEN

    # Clear the count_updated flag if set
    if comic.flags.get("count_updated"):
        comic.flags.pop("count_updated", None)

    comic.save()
    # Sync last_written to updated_at so the comic is not immediately stale
    Comic.objects.filter(pk=comic.pk).update(last_written=F("updated_at"))

    return JsonResponse({
        "success": True,
        "message": "ComicInfo.xml written successfully",
        "new_state": comic.state,
    })


# =============================================================================
# Scan Untagged Folder
# =============================================================================

@require_POST
def scan_untagged(request):
    """
    Dispatch a Celery task to scan the untagged folder and import new comics.
    """
    from celery.result import AsyncResult
    from .tasks import scan_untagged_task

    active = request.session.get("active_task_id")
    if active and AsyncResult(active).state in ("PENDING", "STARTED", "PROGRESS"):
        return JsonResponse({"success": False, "error": "A task is already running", "task_id": active}, status=409)

    result = scan_untagged_task.delay()
    request.session["active_task_id"] = result.id
    request.session["active_task_label"] = "Scanning untagged"
    return JsonResponse({"success": True, "task_id": result.id, "message": "Scanning untagged folder in background"})


# =============================================================================
# Refresh File Info
# =============================================================================

@require_POST
def refresh_file_info(request, pk):
    """
    Re-read page count, file size, and cover hashes from disk and update the DB record.
    """
    from .services import refresh_file_info as _refresh

    comic = get_object_or_404(Comic, pk=pk)

    if not comic.is_digital or not comic.file_path:
        return JsonResponse({"success": False, "error": "Not a digital comic with a file."}, status=400)

    result = _refresh(comic)

    if result["error"]:
        return JsonResponse({"success": False, "error": result["error"]}, status=404)

    updated = result["updated"]
    count = len(updated)
    message = f"Refreshed {count} field(s): {', '.join(updated.keys())}." if updated else "No changes detected — file info is already up to date."

    return JsonResponse({"success": True, "updated": updated, "message": message})


# =============================================================================
# Delete Comic
# =============================================================================

@require_POST
def delete_comic(request, pk):
    """
    Hard delete a comic: remove file from disk AND delete DB record.
    """
    comic = get_object_or_404(Comic, pk=pk)

    comic_str = str(comic)
    file_path = comic.file_path
    file_deleted = False

    # Delete file from disk if it exists
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
            file_deleted = True

            # Try to remove empty parent directories
            parent_dir = os.path.dirname(file_path)
            while parent_dir and parent_dir not in ("/comics", "/comics/library", "/comics/untagged"):
                if os.path.isdir(parent_dir) and not os.listdir(parent_dir):
                    os.rmdir(parent_dir)
                    parent_dir = os.path.dirname(parent_dir)
                else:
                    break
        except OSError as e:
            return JsonResponse({
                "success": False,
                "error": f"Failed to delete file: {str(e)}"
            }, status=500)

    # Delete the comic record
    comic.delete()

    return JsonResponse({
        "success": True,
        "message": f"Deleted: {comic_str}" + (" (file removed)" if file_deleted else " (no file)"),
        "file_deleted": file_deleted,
    })


@require_GET
def series_completion(request, pk):
    """
    HTMX endpoint that returns a series completion progress bar partial.

    Queries comicvine.db to determine how many issues exist in the volume,
    then checks the library for owned issues. Returns an HTML partial with
    a segmented progress bar.
    """
    from .models import get_setting
    from apps.dashboard.services import get_volume_completion

    if not get_setting("show_series_completion", True):
        return HttpResponse("")

    comic = get_object_or_404(Comic, pk=pk)
    cv_volume_id = (comic.custom_values or {}).get("comicvine_volume")
    if not cv_volume_id:
        return HttpResponse("")

    data = get_volume_completion(cv_volume_id)
    if not data:
        return HttpResponse("")

    return render(request, "core/partials/series_completion.html", {
        "comic": comic,
        "data": data,
    })


@require_GET
def series_audit(request, pk):
    """
    Full-page series audit view showing a grid of all issues in a volume.

    Owned issues show their cover image and link to the comic detail page.
    Missing issues show the ComicVine cover (or a placeholder) and link to ComicVine.
    """
    from apps.dashboard.services import get_volume_completion

    comic = get_object_or_404(Comic, pk=pk)
    cv_volume_id = (comic.custom_values or {}).get("comicvine_volume")
    if not cv_volume_id:
        from django.shortcuts import redirect
        return redirect("core:detail", pk=pk)

    data = get_volume_completion(cv_volume_id)
    if not data:
        from django.shortcuts import redirect
        return redirect("core:detail", pk=pk)

    if data.get("unavailable"):
        return render(request, "core/series_audit.html", {
            "comic": comic,
            "unavailable": True,
            "unavailable_reason": data.get("reason", "No local CV data source available."),
        })

    return render(request, "core/series_audit.html", {
        "comic": comic,
        "data": data,
    })


@require_POST
def search_alt_covers(request, pk):
    """
    Search for variant cover URLs (fast, synchronous DB/API lookup) then dispatch
    a Celery task to download and insert them into the CBZ file.
    """
    comic = get_object_or_404(Comic, pk=pk)

    if not comic.is_digital or not comic.file_path:
        return JsonResponse({"success": False, "error": "Comic has no digital file"})

    if comic.custom_values.get("scrape_source") == "inducks":
        return JsonResponse({"success": False, "error": "Alt covers not available for Inducks-scraped comics"})

    if comic.custom_values.get("HasAltCovers") == "Yes":
        return JsonResponse({"success": False, "error": "Comic already has alt covers marked"})

    cv_issue_id = comic.custom_values.get("comicvine_issue")
    if not cv_issue_id:
        return JsonResponse({"success": False, "error": "No ComicVine issue ID associated with this comic"})

    scraper = ComicVineScraper()

    variant_urls = scraper.get_all_covers(int(cv_issue_id))

    if not variant_urls:
        match = scraper.get_issue_from_api(int(cv_issue_id))
        if match and match.cover_urls:
            variant_urls = match.cover_urls

    if not variant_urls:
        return JsonResponse({"success": False, "error": "No alternate covers found in local DB or API"})

    variants = list(dict.fromkeys(url for url in variant_urls if url))

    if not variants:
        return JsonResponse({"success": False, "error": "No new alternate covers found"})

    from .tasks import search_alt_covers_task
    result = search_alt_covers_task.delay(str(comic.pk), variants)
    request.session["active_task_id"] = result.id
    request.session["active_task_label"] = "Inserting covers"
    return JsonResponse({
        "success": True,
        "task_id": result.id,
        "total": len(variants),
        "message": f"Downloading {len(variants)} cover(s) in background",
    })


@require_POST
def save_column_layout(request):
    """
    Save the current column selection as the default for the current view context.
    Context is determined by the 'state' or 'flag' parameter.
    """
    from .models import Setting
    
    state = request.POST.get("state")
    flag = request.POST.get("flag")
    columns = request.POST.getlist("col")
    
    if not columns:
        return JsonResponse({"success": False, "error": "No columns selected"})
    
    # Determine the setting key
    if state:
        key = f"layout_state_{state}"
        label = f"Column Layout: State {state.title()}"
    elif flag:
        key = f"layout_flag_{flag}"
        label = f"Column Layout: Flag {flag.replace('_', ' ').title()}"
    else:
        key = "layout_default"
        label = "Default Column Layout"
        
    # Save to Settings
    setting, created = Setting.objects.get_or_create(
        key=key,
        defaults={
            "label": label,
            "group": Setting.GROUP_APPEARANCE,
            "type": Setting.TYPE_TEXT,
        }
    )
    setting.value = ",".join(columns)
    setting.save()
    
    return JsonResponse({"success": True})


# =============================================================================
# Inline Field Editing (STATE_NEW list)
# =============================================================================

_INLINE_FORMAT_CHOICES = [
    "Main Series", "Limited Series", "One-Shot", "TPB", "HC",
    "Annual", "Special", "Giant-Size", "King-Size", "Omnibus", "Deluxe",
    "Director's Cut",
]


def comic_inline_field(request, pk):
    """
    GET  ?field=X           -> return editable input fragment
    GET  ?field=X&cancel=1  -> return display fragment (cancel without saving)
    POST field=X&value=V    -> save field, return display fragment
    """
    comic = get_object_or_404(Comic, pk=pk)

    if request.method == "POST":
        field = request.POST.get("field", "")
        value = request.POST.get("value", "").strip()

        if field not in _INLINE_EDITABLE_FIELDS:
            return HttpResponse("Invalid field", status=400)

        if field == "proposed_volume":
            try:
                value = int(value) if value else None
            except ValueError:
                value = None
        elif not value:
            value = None

        setattr(comic, field, value)
        comic.save(update_fields=[field])

        display_value = getattr(comic, field) or ""
        return render(request, "core/partials/inline_display.html", {
            "comic": comic,
            "field": field,
            "display_value": display_value,
        })

    # GET
    field = request.GET.get("field", "")
    if field not in _INLINE_EDITABLE_FIELDS:
        return HttpResponse("Invalid field", status=400)

    cancel = request.GET.get("cancel") == "1"
    if cancel:
        display_value = getattr(comic, field) or ""
        return render(request, "core/partials/inline_display.html", {
            "comic": comic,
            "field": field,
            "display_value": display_value,
        })

    current_value = getattr(comic, field) or ""
    return render(request, "core/partials/inline_input.html", {
        "comic": comic,
        "field": field,
        "current_value": current_value,
        "is_format": field == "format",
        "format_choices": _INLINE_FORMAT_CHOICES,
    })


# =============================================================================
# Rollback
# =============================================================================

_VALID_ROLLBACK_STATES = {"new", "scrape", "count", "tagging"}


@require_POST
def comic_rollback(request, pk):
    """Reset a comic to a previous workflow state and clear the associated data."""
    comic = get_object_or_404(Comic, pk=pk)
    to_state = request.POST.get("to_state", "")

    if to_state not in _VALID_ROLLBACK_STATES:
        return HttpResponse(f"<tr><td colspan='6' class='text-error text-xs'>Invalid state: {to_state}</td></tr>")

    cv = comic.custom_values or {}

    if to_state in ("new", "scrape"):
        for key in ("comicvine_issue", "comicvine_volume", "scrape_score", "scrape_source"):
            cv.pop(key, None)
        for flag in ("scrape_no_match", "scrape_error", "scrape_error_detail", "metadata_mismatch"):
            comic.flags.pop(flag, None)
        comic.custom_values = cv
        comic.state = Comic.STATE_NEW if to_state == "new" else Comic.STATE_IMPORTED

    elif to_state == "count":
        comic.series_group = None
        comic.main_character_or_team = None
        cv.pop("DataManager_Processed", None)
        comic.custom_values = cv
        comic.state = Comic.STATE_COUNTED

    elif to_state == "tagging":
        comic.format = None
        comic.state = Comic.STATE_TAGGED

    comic.save()

    label_map = {
        "new":     "New (phase 1)",
        "scrape":  "Scrape (phase 2)",
        "count":   "Add Count (phase 3)",
        "tagging": "Tagging (phase 4)",
    }
    return HttpResponse(
        f'<tr class="opacity-50">'
        f'<td colspan="5" class="text-xs text-base-content/50 italic">'
        f'Rolled back to <span class="font-medium text-warning">{label_map.get(to_state, to_state)}</span>'
        f'</td>'
        f'<td></td>'
        f'</tr>'
    )


def series_audit_volume(request, cv_volume_id):
    """
    Volume-centric series audit view.
    """
    from apps.dashboard.services import get_volume_completion

    data = get_volume_completion(cv_volume_id)
    if not data:
        from django.http import Http404
        raise Http404("Volume not found")

    if data.get("unavailable"):
        return render(request, "core/series_audit.html", {
            "unavailable": True,
            "unavailable_reason": data.get("reason", "No local CV data source available."),
        })

    return render(request, "core/series_audit.html", {
        "data": data,
    })


def character_audit_search(request):
    """
    Search for series by main character/team and show completion status for each.
    """
    from apps.dashboard.services import get_volume_completion_bulk
    from apps.scraper.cv_sources import get_cv_source_status

    cv_status = get_cv_source_status()
    audit_available = cv_status["db"] or cv_status["mcl"]

    query = request.GET.get("q", "").strip()
    volumes_data = []

    if query and audit_available:
        volume_ids = list(
            Comic.objects.filter(
                main_character_or_team__iexact=query
            ).exclude(
                custom_values__comicvine_volume__isnull=True
            ).exclude(
                custom_values__comicvine_volume=""
            ).values_list("custom_values__comicvine_volume", flat=True).distinct()
        )

        volumes_data = get_volume_completion_bulk(volume_ids)
        volumes_data.sort(key=lambda x: (x["completion"], x["volume_info"]["name"]))

    return render(request, "core/character_audit_search.html", {
        "query": query,
        "volumes_data": volumes_data,
        "audit_available": audit_available,
        "cv_status": cv_status,
    })


@require_POST
def audit_metadata_mismatches(request):
    """
    Dispatch a Celery task to audit metadata mismatches between local DB and ComicVine.
    """
    from celery.result import AsyncResult
    from .tasks import audit_metadata_task

    active = request.session.get("active_task_id")
    if active and AsyncResult(active).state in ("PENDING", "STARTED", "PROGRESS"):
        return JsonResponse({"success": False, "error": "A task is already running", "task_id": active}, status=409)

    result = audit_metadata_task.delay()
    request.session["active_task_id"] = result.id
    request.session["active_task_label"] = "Auditing metadata"
    return JsonResponse({"success": True, "task_id": result.id, "message": "Auditing metadata mismatches in background"})


def comic_download(request, pk):
    """Serve the comic CBZ file as a download attachment."""
    comic = get_object_or_404(Comic, pk=pk)

    if not comic.is_digital or not comic.file_path:
        return HttpResponse("No file available", status=404)

    file_path = Path(comic.file_path)
    if not file_path.exists():
        return HttpResponse("File not found on disk", status=404)

    import mimetypes
    from django.http import FileResponse

    mime_type, _ = mimetypes.guess_type(str(file_path))
    if not mime_type:
        mime_type = "application/octet-stream"

    response = FileResponse(open(file_path, "rb"), content_type=mime_type)
    response["Content-Disposition"] = f'attachment; filename="{file_path.name}"'
    return response


def comic_reader(request, pk):
    """Full-page browser reader for a digital comic."""
    comic = get_object_or_404(Comic, pk=pk)

    if not comic.is_digital or not comic.file_path:
        return HttpResponse("No digital file available for this comic.", status=404)

    page_count = comic.page_count or 0

    return render(request, "core/comic_reader.html", {
        "comic": comic,
        "page_count": page_count,
        "page_range": range(page_count),
    })
