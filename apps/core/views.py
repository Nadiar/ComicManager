import os
import re
import tempfile
import zipfile
from pathlib import Path

from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST

from .models import Comic
from apps.scraper.comicvine import ComicVineScraper
from apps.scraper.hasher import extract_cover_hashes, extract_cover_image


# Flag display names for the UI
FLAG_LABELS = {
    "low_page_count": "Low Page Count",
    "is_pdf": "PDF File",
    "no_series": "No Series Parsed",
    "cover_only": "Cover Only",
    "needs_conversion": "Needs Conversion",
}


def comic_list(request):
    comics = Comic.objects.all()

    # Filter by state if provided
    state = request.GET.get("state")
    if state:
        comics = comics.filter(state=state)

    # Filter by flag if provided
    flag = request.GET.get("flag")
    if flag:
        # JSONField lookup: flags__<flag_name>=True
        comics = comics.filter(**{f"flags__{flag}": True})

    comics = comics.order_by("series", "volume", "number")

    # Count comics needing conversion (for "Convert All" button)
    needs_conversion_count = Comic.objects.filter(flags__needs_conversion=True).count()

    return render(request, "core/comic_list.html", {
        "comics": comics,
        "current_state": state,
        "current_flag": flag,
        "flag_label": FLAG_LABELS.get(flag, flag),
        "needs_conversion_count": needs_conversion_count,
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

    # For digital comics, try to read ComicInfo.xml from the file
    if comic.is_digital and comic.file_path:
        if comic.file_path.lower().endswith('.cbz'):
            xml_data = read_comicinfo_xml(comic.file_path)
            if xml_data is not None:
                comparison = compare_db_vs_xml(comic, xml_data)

    return render(request, "core/comic_detail.html", {
        "comic": comic,
        "xml_data": xml_data,
        "comparison": comparison,
    })


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
    Convert all CBR/CB7 files to CBZ format.

    Returns a JSON response with the count of converted files.
    """
    comics = Comic.objects.filter(flags__needs_conversion=True)

    converted = 0
    errors = []

    for comic in comics:
        if comic.file_format not in ("cbr", "cb7"):
            continue

        if not comic.file_path or not os.path.exists(comic.file_path):
            errors.append(f"{comic.proposed_series} #{comic.proposed_number}: file not found")
            continue

        original_path = Path(comic.file_path)
        new_path = original_path.with_suffix(".cbz")

        if new_path.exists():
            errors.append(f"{comic.proposed_series} #{comic.proposed_number}: target exists")
            continue

        try:
            # Import patoolib lazily
            import patoolib

            with tempfile.TemporaryDirectory() as temp_dir:
                patoolib.extract_archive(str(original_path), outdir=temp_dir, verbosity=-1)

                with zipfile.ZipFile(new_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for root, dirs, files in os.walk(temp_dir):
                        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__MACOSX"]

                        for file in sorted(files):
                            if file.startswith(".") or file == "Thumbs.db":
                                continue

                            file_path = Path(root) / file
                            arc_path = file_path.relative_to(temp_dir)
                            zf.write(file_path, arc_path)

            comic.file_path = str(new_path)
            comic.file_format = "cbz"

            if comic.flags and "needs_conversion" in comic.flags:
                del comic.flags["needs_conversion"]
                # Keep as empty dict, not None (NOT NULL constraint)
                if not comic.flags:
                    comic.flags = {}

            comic.save()
            original_path.unlink()
            converted += 1

        except Exception as e:
            if new_path.exists():
                new_path.unlink()
            errors.append(f"{comic.proposed_series} #{comic.proposed_number}: {str(e)}")

    return JsonResponse({
        "success": True,
        "converted": converted,
        "errors": errors,
    })


def scrape_preview(request, pk):
    """
    Preview scrape matches for a comic without applying them.

    Returns a list of potential matches with cover URLs for user review.
    """
    comic = get_object_or_404(Comic, pk=pk)

    if comic.state != Comic.STATE_IMPORTED:
        return JsonResponse({
            "success": False,
            "error": f"Comic is not in 'imported' state (current: {comic.state})"
        }, status=400)

    scraper = ComicVineScraper()
    max_distance = 10
    all_matches = []

    # Collect raw matches first
    raw_matches = []

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


def comic_cover(request, pk):
    """
    Serve the cover image of a comic file.

    Returns JPEG image data for display in the UI.
    """
    comic = get_object_or_404(Comic, pk=pk)

    if not comic.file_path:
        return HttpResponse(status=404)

    cover_data = extract_cover_image(comic.file_path)
    if not cover_data:
        return HttpResponse(status=404)

    return HttpResponse(cover_data, content_type="image/jpeg")


@require_POST
def scrape_comic(request, pk):
    """
    Scrape a single comic against the ComicVine database.

    If cv_issue_id is provided in POST data, use that specific match.
    Otherwise, auto-select the best match.
    """
    comic = get_object_or_404(Comic, pk=pk)

    if comic.state != Comic.STATE_IMPORTED:
        return JsonResponse({
            "success": False,
            "error": f"Comic is not in 'imported' state (current: {comic.state})"
        }, status=400)

    scraper = ComicVineScraper()
    match = None

    # Check if a specific CV issue ID was provided
    cv_issue_id = request.POST.get("cv_issue_id")
    if cv_issue_id:
        # User selected a specific match
        match = scraper.get_issue_details(int(cv_issue_id))
        if match:
            match.match_type = "manual"
    else:
        # Auto-select best match
        max_distance = 10

        # Try hash matching first
        if comic.file_path:
            match = _try_hash_match(comic, scraper, max_distance)

        # Fall back to metadata matching
        if not match:
            match = _try_metadata_match(comic, scraper)

    if not match:
        return JsonResponse({
            "success": False,
            "error": "No match found in ComicVine database"
        }, status=404)

    # Apply match to comic
    _apply_match(comic, match)

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
    Scrape all comics in 'imported' state against the ComicVine database.
    """
    comics = Comic.objects.filter(
        state=Comic.STATE_IMPORTED,
        medium=Comic.MEDIUM_DIGITAL,
    )

    scraper = ComicVineScraper()
    max_distance = 10

    matched = 0
    failed = 0
    errors = []

    for comic in comics:
        match = None

        # Try hash matching first
        if comic.file_path:
            match = _try_hash_match(comic, scraper, max_distance)

        # Fall back to metadata matching
        if not match:
            match = _try_metadata_match(comic, scraper)

        if match:
            _apply_match(comic, match)
            matched += 1
        else:
            failed += 1
            errors.append(f"{comic.series} #{comic.number}: no match found")

    return JsonResponse({
        "success": True,
        "matched": matched,
        "failed": failed,
        "errors": errors[:10],  # Limit error list
    })


def _try_hash_match(comic, scraper, max_distance):
    """Try to match comic by cover image hash with metadata cross-validation."""
    hashes = extract_cover_hashes(comic.file_path)
    if not hashes:
        return None

    # Store hashes on comic
    comic.phash = hashes.phash_hex
    comic.ahash = hashes.ahash_hex

    matches = scraper.match_by_hash_fast(
        hashes.phash,
        hashes.ahash,
        max_distance=max_distance,
        limit=10,
    )

    if not matches:
        return None

    # Cross-validate against parsed metadata
    validated = []
    for match in matches:
        score = _metadata_alignment_score(comic, match)
        if score > 0:
            validated.append((match, score))

    if validated:
        validated.sort(key=lambda x: (-x[1], x[0].match_score))
        best = validated[0][0]
        best.match_type = f"{best.match_type}+meta"
        return best

    return None


def _try_metadata_match(comic, scraper):
    """Try to match comic by series name and issue number."""
    if not comic.series or not comic.number:
        return None

    matches = scraper.match_by_metadata(
        series=comic.series,
        issue_number=comic.number,
        year=comic.year,
    )

    return matches[0] if matches else None


def _metadata_alignment_score(comic, match):
    """Score how well a CV match aligns with parsed metadata."""
    if not comic.series and not comic.number:
        return 1

    score = 0

    # Normalize issue numbers
    comic_num = (comic.number or "").lstrip("0").lower() or "0"
    match_num = (match.issue_number or "").lstrip("0").lower() or "0"

    if comic_num and match_num:
        if comic_num != match_num:
            return 0
        score = 1

    if comic.series and match.series:
        if _series_matches(comic.series, match.series):
            score = 2
            if comic.year and match.start_year:
                try:
                    if abs(int(comic.year) - int(match.start_year)) <= 2:
                        score = 3
                except (ValueError, TypeError):
                    pass
    elif not comic.series and score == 0:
        score = 1

    return score


def _series_matches(proposed, matched):
    """Check if series names are similar enough."""
    def normalize(s):
        s = s.lower()
        s = re.sub(r"[^\w\s]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    proposed_norm = normalize(proposed)
    matched_norm = normalize(matched)

    if proposed_norm == matched_norm:
        return True
    if proposed_norm in matched_norm or matched_norm in proposed_norm:
        return True

    proposed_words = proposed_norm.split()
    matched_words = matched_norm.split()
    if proposed_words and matched_words and proposed_words[0] == matched_words[0]:
        return True

    return False


def _apply_match(comic, match):
    """Apply ComicVine match data to comic and update state."""
    comic.series = match.series
    comic.number = match.issue_number
    comic.title = match.title
    comic.publisher = match.publisher
    comic.count = match.issue_count

    if match.start_year:
        try:
            comic.volume = int(match.start_year)
        except ValueError:
            pass

    if match.cover_date:
        try:
            parts = match.cover_date.split("-")
            comic.year = int(parts[0])
            if len(parts) > 1:
                comic.month = int(parts[1])
            if len(parts) > 2:
                comic.day = int(parts[2])
        except (ValueError, IndexError):
            pass

    if match.description:
        comic.summary = match.description

    comic.custom_values["comicvine_issue"] = str(match.issue_id)
    comic.custom_values["comicvine_volume"] = str(match.volume_id)
    if match.issue_count:
        comic.custom_values["comicvine_issue_count"] = str(match.issue_count)

    comic.custom_values["scrape_source"] = match.match_type
    comic.custom_values["scrape_score"] = str(match.match_score)

    # Transition through scraped -> counted
    comic.state = Comic.STATE_COUNTED
    comic.save()

    # Update issue count for all other comics in the same volume
    if match.issue_count and match.volume_id:
        _update_volume_issue_count(str(match.volume_id), match.issue_count, exclude_pk=comic.pk)


def _update_volume_issue_count(volume_id: str, new_count: int, exclude_pk=None):
    """
    Update issue count for all comics in a ComicVine volume.

    When a new issue is scraped with an updated count, all other issues
    in the same volume need their count updated. The actual ComicInfo.xml
    files will be updated during the 'write' phase.
    """
    # Find all comics with the same comicvine_volume
    comics_in_volume = Comic.objects.filter(
        custom_values__comicvine_volume=volume_id
    )

    if exclude_pk:
        comics_in_volume = comics_in_volume.exclude(pk=exclude_pk)

    updated = 0
    for comic in comics_in_volume:
        old_count = comic.count
        if old_count != new_count:
            comic.count = new_count
            comic.custom_values["comicvine_issue_count"] = str(new_count)
            # Mark that this comic needs its ComicInfo.xml rewritten
            comic.flags["count_updated"] = True
            comic.save()
            updated += 1

    return updated


# =============================================================================
# Phase 4-5: Tagging (Publisher Management + Format Detection)
# =============================================================================

# Format patterns for auto-detection
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


def _detect_format(comic) -> str | None:
    """Auto-detect comic format from series name or title."""
    text_to_check = f"{comic.series or ''} {comic.title or ''}"

    for pattern, format_name in FORMAT_PATTERNS:
        if re.search(pattern, text_to_check, re.IGNORECASE):
            return format_name

    return None


def _apply_tagging(comic):
    """
    Apply publisher rules and format detection to a comic.

    Phase 4: Publisher Management (DataManager rules) - placeholder for now
    Phase 5: Format Tagging - auto-detect TPB, Annual, etc.
    """
    # Phase 5: Format detection
    detected_format = _detect_format(comic)
    if detected_format:
        comic.format = detected_format

    # Transition to formatted state (skipping tagged since we combine phases)
    comic.state = Comic.STATE_FORMATTED
    comic.save()


@require_POST
def tag_comic(request, pk):
    """Tag a single comic (apply publisher rules + format detection)."""
    comic = get_object_or_404(Comic, pk=pk)

    if comic.state != Comic.STATE_COUNTED:
        return JsonResponse({
            "success": False,
            "error": f"Comic is not in 'counted' state (current: {comic.state})"
        }, status=400)

    _apply_tagging(comic)

    return JsonResponse({
        "success": True,
        "format": comic.format,
        "state": comic.state,
    })


@require_POST
def tag_all_comics(request):
    """Tag all comics in 'counted' state."""
    comics = Comic.objects.filter(state=Comic.STATE_COUNTED)
    total = comics.count()

    tagged = 0
    for comic in comics:
        _apply_tagging(comic)
        tagged += 1

    return JsonResponse({
        "success": True,
        "tagged": tagged,
        "total": total,
    })


# =============================================================================
# Comic Detail / Edit Views
# =============================================================================

def comic_edit(request, pk):
    """
    Edit a comic's metadata.

    GET: Display edit form
    POST: Save changes to DB and (for digital comics) to ComicInfo.xml in the CBZ
    """
    from django.contrib import messages
    from .utils import (
        read_comicinfo_xml,
        compare_db_vs_xml,
        update_comic_from_form,
        write_comicinfo_xml,
        EDITABLE_FIELDS,
    )

    comic = get_object_or_404(Comic, pk=pk)

    if request.method == "POST":
        # Update comic from form data
        update_comic_from_form(comic, request.POST)
        comic.save()

        # For digital comics with CBZ files, also update the XML
        xml_updated = False
        if comic.is_digital and comic.file_path and comic.file_path.lower().endswith('.cbz'):
            xml_updated = write_comicinfo_xml(comic.file_path, comic)

        if xml_updated:
            messages.success(request, "Comic updated successfully (database and ComicInfo.xml).")
        else:
            messages.success(request, "Comic updated successfully (database only).")

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

    return render(request, "core/comic_edit.html", {
        "comic": comic,
        "xml_data": xml_data,
        "comparison": comparison,
        "editable_fields": EDITABLE_FIELDS,
    })


# =============================================================================
# Phase 6-8: Deduplicate, Organize, Write
# =============================================================================

@require_POST
def deduplicate_all_comics(request):
    """
    Process all comics in 'formatted' state through deduplication.

    For now, this is a placeholder that simply advances the state.
    Real duplicate detection logic can be added later.
    """
    comics = Comic.objects.filter(state=Comic.STATE_FORMATTED)
    total = comics.count()

    deduplicated = 0
    for comic in comics:
        # TODO: Implement actual duplicate detection logic
        # For now, just advance the state
        comic.state = Comic.STATE_DEDUPLICATED
        comic.save()
        deduplicated += 1

    return JsonResponse({
        "success": True,
        "deduplicated": deduplicated,
        "total": total,
    })


@require_POST
def organize_all_comics(request):
    """
    Process all comics in 'deduplicated' state through organization.

    For now, this is a placeholder that simply advances the state.
    Real file organization logic can be added later.
    """
    comics = Comic.objects.filter(state=Comic.STATE_DEDUPLICATED)
    total = comics.count()

    organized = 0
    for comic in comics:
        # TODO: Implement actual file organization logic
        # For now, just advance the state
        comic.state = Comic.STATE_ORGANIZED
        comic.save()
        organized += 1

    return JsonResponse({
        "success": True,
        "organized": organized,
        "total": total,
    })


@require_POST
def write_all_comics(request):
    """
    Write ComicInfo.xml for all comics in 'organized' state.

    This updates the ComicInfo.xml inside each CBZ file with the
    current database values, then advances to 'written' state.
    """
    from .utils import write_comicinfo_xml
    from django.utils import timezone

    comics = Comic.objects.filter(state=Comic.STATE_ORGANIZED)
    total = comics.count()

    written = 0
    errors = []

    for comic in comics:
        # For digital comics with CBZ files, write the XML
        if comic.is_digital and comic.file_path and comic.file_path.lower().endswith('.cbz'):
            success = write_comicinfo_xml(comic.file_path, comic)
            if not success:
                errors.append(f"{comic.series} #{comic.number}: Failed to write XML")
                continue

        # Advance state and record write time
        comic.state = Comic.STATE_WRITTEN
        comic.last_written = timezone.now()

        # Clear the count_updated flag if set
        if comic.flags.get("count_updated"):
            comic.flags.pop("count_updated", None)

        comic.save()
        written += 1

    return JsonResponse({
        "success": True,
        "written": written,
        "total": total,
        "errors": errors,
    })
