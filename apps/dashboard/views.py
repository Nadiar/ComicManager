from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.db.models import Count, Q
from apps.core.models import Comic
from .models import SmartList
from apps.core.utils import COLUMNS_REGISTRY, DEFAULT_COLUMNS, active_task_conflict
from .services import build_queryset, get_missing_issues, search_cv_volumes


def index(request):
    stats = {
        "total":     Comic.objects.count(),
        "digital":   Comic.objects.filter(medium="digital").count(),
        "physical":  Comic.objects.filter(medium="physical").count(),
        "new":       Comic.objects.filter(state="new").count(),
        "written":   Comic.objects.filter(state="done").count(),
        "new_cbr_count": Comic.objects.filter(state="new", flags__needs_conversion=True).count(),
        "scrape_skipped": Comic.objects.filter(state="scrape", flags__scrape_skipped=True).count(),
    }

    # Get counts per workflow state
    state_counts = dict(
        Comic.objects.values("state").annotate(count=Count("id")).values_list("state", "count")
    )
    stats["scrape_scrapeable"] = state_counts.get("scrape", 0) - stats["scrape_skipped"]

    # Workflow pipeline stages
    pipeline = [
        {"state": "new",         "label": "1. New",          "description": "Awaiting import",                        "action": "Accept All",     "count": state_counts.get("new",         0)},
        {"state": "scrape",      "label": "2. Scrape",        "description": "Match & scrape ComicVine metadata",      "action": "Scrape All",     "count": state_counts.get("scrape",      0)},
        {"state": "tagging",     "label": "3. Tagging",       "description": "Apply publisher tagging rules",          "action": "Tag All",        "count": state_counts.get("tagging",     0)},
        {"state": "formats",     "label": "4. Add Formats",   "description": "Detect format (TPB, One-Shot, etc.)",    "action": "Format All",     "count": state_counts.get("formats",     0)},
        {"state": "deduplicate", "label": "5. Deduplicate",   "description": "Identify and resolve duplicates",        "action": "Detect Dupes",   "count": state_counts.get("deduplicate", 0)},
        {"state": "move",        "label": "6. Move Files",    "description": "Move files to library folder",           "action": "Organize All",   "count": state_counts.get("move",        0)},
        {"state": "write",       "label": "7. Write to CBZ",  "description": "Write ComicInfo.xml into CBZ",           "action": "Write All",      "count": state_counts.get("write",       0)},
        {"state": "done",        "label": "8. Done",          "description": "Written — sync library paths if needed", "action": "Sync Paths",     "count": state_counts.get("done",        0)},
    ]

    # Review queue
    review_queue = [
        {
            "flag": "corrupted_archive",
            "label": "Corrupted Archive",
            "description": "CBZ file is corrupted or truncated and cannot be opened",
            "count": Comic.objects.filter(flags__corrupted_archive=True).count(),
            "action": "review",
        },
        {
            "flag": "low_page_count",
            "label": "Low Page Count",
            "description": "Less than 5 pages - likely incomplete",
            "count": Comic.objects.filter(flags__low_page_count=True).count(),
            "action": "delete",
        },
        {
            "flag": "is_pdf",
            "label": "PDF Files",
            "description": "PDF format needs manual review",
            "count": Comic.objects.filter(flags__is_pdf=True).count(),
            "action": "review",
        },
        {
            "flag": "no_series",
            "label": "No Series Parsed",
            "description": "Couldn't extract series name from filename",
            "count": Comic.objects.filter(flags__no_series=True).count(),
            "action": "edit",
        },
        {
            "flag": "cover_only",
            "label": "Cover Only",
            "description": "Likely just a cover image (≤3 pages)",
            "count": Comic.objects.filter(flags__cover_only=True).count(),
            "action": "delete",
        },
        {
            "flag": "needs_conversion",
            "label": "Needs Conversion",
            "description": "CBR/CB7 files need conversion to CBZ",
            "count": Comic.objects.filter(flags__needs_conversion=True).count(),
            "action": "convert",
        },
        {
            "flag": "is_zip",
            "label": "ZIP Files",
            "description": "ZIP files that can be renamed to CBZ (same format)",
            "count": Comic.objects.filter(flags__is_zip=True).count(),
            "action": "convert",
        },
        {
            "flag": "missing_count",
            "label": "Missing Issue Count",
            "description": "Scraped but missing issue count from ComicVine",
            "count": Comic.objects.filter(flags__missing_count=True).count(),
            "action": "populate",
        },
        {
            "flag": "count_mismatch",
            "label": "Count Mismatch",
            "description": "Comics in same volume disagree on issue count",
            "count": Comic.objects.filter(flags__count_mismatch=True).count(),
            "action": "review",
        },
        {
            "flag": "count_updated",
            "label": "Count Updated",
            "description": "Issue count changed - needs ComicInfo.xml rewrite",
            "count": Comic.objects.filter(flags__count_updated=True).count(),
            "action": "rewrite",
        },
        {
            "flag": "metadata_mismatch",
            "label": "Metadata Mismatch",
            "description": "Series name doesn't match the ComicVine volume — needs re-scrape",
            "count": Comic.objects.filter(flags__metadata_mismatch=True).count(),
            "action": "review",
        },
        {
            "flag": "scrape_no_match",
            "label": "Scrape: No Match",
            "description": "No ComicVine match found — needs manual matching or skip",
            "count": Comic.objects.filter(flags__scrape_no_match=True).count(),
            "action": "review",
        },
        {
            "flag": "scrape_error",
            "label": "Scrape: Error",
            "description": "Exception during scraping (API unavailable, hash failure, etc.)",
            "count": Comic.objects.filter(flags__scrape_error=True).count(),
            "action": "review",
        },
        {
            "flag": "missing_format",
            "label": "Missing Format",
            "description": "Format detection returned no result — needs manual format assignment",
            "count": Comic.objects.filter(flags__missing_format=True).count(),
            "action": "edit",
        },
        {
            "flag": "scrape_skipped",
            "label": "Scrape: Skipped",
            "description": "Marked to be skipped by batch scraping — review or un-skip when ready",
            "count": Comic.objects.filter(flags__scrape_skipped=True).count(),
            "action": "review",
        },
        {
            "flag": "unknown_publisher",
            "label": "Unknown Publisher",
            "description": "Publisher not covered by any tagging ruleset — create a ruleset or review",
            "count": Comic.objects.filter(flags__unknown_publisher=True).count(),
            "action": "review",
        },
        {
            "flag": "format_mismatch_in_volume",
            "label": "Format Mismatch in Volume",
            "description": "Comics linked to the same CV volume have conflicting formats",
            "count": Comic.objects.filter(flags__format_mismatch_in_volume=True).count(),
            "action": "detect_format_conflicts",
        },
        {
            "flag": "cv_volume_conflict",
            "label": "CV Volume Conflict",
            "description": "Comics with the same Series+Volume+Format are linked to different CV volumes",
            "count": Comic.objects.filter(flags__cv_volume_conflict=True).count(),
            "action": "detect_format_conflicts",
        },
        {
            "flag": "needs_reformat",
            "link": "/comics/format/",
            "label": "Format Upgrade Needed",
            "description": "Issue count changed — format should be upgraded (e.g. One-Shot to Limited Series)",
            "count": Comic.objects.filter(needs_reformat=True).count(),
            "action": "reformat",
        },
    ]

    # Active flags only — excludes maintenance flags (count_mismatch, format_mismatch_in_volume,
    # cv_volume_conflict, needs_reformat) which live in the Maintenance tab
    _active_flags_q = (
        Q(flags__corrupted_archive=True) |
        Q(flags__low_page_count=True) |
        Q(flags__is_pdf=True) |
        Q(flags__no_series=True) |
        Q(flags__cover_only=True) |
        Q(flags__needs_conversion=True) |
        Q(flags__is_zip=True) |
        Q(flags__missing_count=True) |
        Q(flags__count_updated=True) |
        Q(flags__metadata_mismatch=True) |
        Q(flags__scrape_no_match=True) |
        Q(flags__scrape_error=True) |
        Q(flags__missing_format=True) |
        Q(flags__scrape_skipped=True) |
        Q(flags__unknown_publisher=True)
    )
    flagged_count = Comic.objects.filter(_active_flags_q).count()

    # Maintenance: moved from Active tab
    count_mismatch_count = Comic.objects.filter(flags__count_mismatch=True).count()
    format_mismatch_count = Comic.objects.filter(flags__format_mismatch_in_volume=True).count()
    cv_volume_conflict_count = Comic.objects.filter(flags__cv_volume_conflict=True).count()
    needs_reformat_count = Comic.objects.filter(needs_reformat=True).count()

    # Needs-reorganize queue
    needs_reorganize_count = Comic.objects.filter(needs_reorganize=True).count()

    # Stale metadata queue (written before but DB updated since)
    from django.db.models import BooleanField, Case, F, Value, When
    stale_count = Comic.objects.annotate(
        is_stale=Case(
            When(last_written__isnull=False, updated_at__gt=F("last_written"), then=Value(True)),
            default=Value(False),
            output_field=BooleanField(),
        )
    ).filter(is_stale=True).count()

    # Maintenance: duplicates
    from apps.duplicates.models import DuplicateGroup
    dup_total = DuplicateGroup.objects.filter(status=DuplicateGroup.STATUS_PENDING).count()
    dup_by_method = dict(
        DuplicateGroup.objects.filter(status=DuplicateGroup.STATUS_PENDING)
        .values("detection_method")
        .annotate(c=Count("id"))
        .values_list("detection_method", "c")
    )

    # Maintenance: written digital comics that have never had ComicInfo.xml written
    missing_comicinfo_count = Comic.objects.filter(
        state=Comic.STATE_WRITTEN,
        medium=Comic.MEDIUM_DIGITAL,
        last_written__isnull=True,
    ).count()

    maintenance_count = (
        dup_total + needs_reorganize_count + stale_count + missing_comicinfo_count +
        count_mismatch_count + format_mismatch_count + cv_volume_conflict_count + needs_reformat_count
    )

    # New comics panel (CBZ only, non-empty proposed_series)
    from apps.core.models import get_setting
    from django.utils import timezone
    from datetime import timedelta

    _new_qs = (
        Comic.objects.filter(state=Comic.STATE_NEW, file_format="cbz", medium=Comic.MEDIUM_DIGITAL)
        .exclude(proposed_series__isnull=True).exclude(proposed_series="")
        .order_by("-imported_at")
    )
    new_comics = list(_new_qs[:8])
    new_comics_total = _new_qs.count()
    new_comics_non_cbz = Comic.objects.filter(
        state=Comic.STATE_NEW, medium=Comic.MEDIUM_DIGITAL
    ).exclude(file_format="cbz").count()

    zero_day_hours = int(get_setting("scrape_0day_hours", 24))
    _0day_cutoff = timezone.now() - timedelta(hours=zero_day_hours)
    new_comics_0day_count = _new_qs.filter(imported_at__gte=_0day_cutoff).count()

    # Smart lists for dashboard
    dashboard_smartlists = []
    for sl in SmartList.objects.filter(show_on_dashboard=True):
        qs = build_queryset(sl)
        entry = {"smartlist": sl, "count": qs.count()}
        if sl.has_cv_volume:
            missing_data = get_missing_issues(sl)
            if missing_data:
                entry["completion"] = missing_data["completion"]
                entry["owned"] = missing_data["owned_count"]
                entry["total_issues"] = missing_data["total_count"]
        dashboard_smartlists.append(entry)

    # Severity for "Needs your attention" card
    _severity = {
        "corrupted_archive": "err", "low_page_count": "err",
        "cover_only": "err",        "scrape_error": "err",
        "is_pdf": "warn",           "no_series": "warn",
        "missing_count": "warn",    "count_updated": "warn",
        "metadata_mismatch": "warn","scrape_no_match": "warn",
        "missing_format": "warn",   "unknown_publisher": "warn",
        "needs_conversion": "info", "is_zip": "info",
        "scrape_skipped": "info",
    }
    for item in review_queue:
        item["sev"] = _severity.get(item["flag"], "warn")

    # In-flight: comics actively in the pipeline (all stages except done)
    stats["in_flight"] = sum(
        state_counts.get(s, 0)
        for s in ["new", "scrape", "tagging", "formats", "deduplicate", "move", "write"]
    )
    stats["complete_pct"] = round(stats["written"] / max(stats["total"], 1) * 100)

    from apps.scraper.cv_sources import get_cv_source_status
    cv_status = get_cv_source_status()
    hide_zero_maintenance_rows = get_setting("hide_zero_maintenance_rows", False)

    return render(request, "dashboard/index.html", {
        "stats": stats,
        "pipeline": pipeline,
        "review_queue": review_queue,
        "flagged_count": flagged_count,
        "needs_reorganize_count": needs_reorganize_count,
        "stale_count": stale_count,
        "dup_total": dup_total,
        "dup_by_method": dup_by_method,
        "missing_comicinfo_count": missing_comicinfo_count,
        "count_mismatch_count": count_mismatch_count,
        "format_mismatch_count": format_mismatch_count,
        "cv_volume_conflict_count": cv_volume_conflict_count,
        "needs_reformat_count": needs_reformat_count,
        "maintenance_count": maintenance_count,
        "dashboard_smartlists": dashboard_smartlists,
        "cv_status": cv_status,
        "hide_zero_maintenance_rows": hide_zero_maintenance_rows,
        "new_comics": new_comics,
        "new_comics_total": new_comics_total,
        "new_comics_non_cbz": new_comics_non_cbz,
        "zero_day_hours": zero_day_hours,
        "new_comics_0day_count": new_comics_0day_count,
    })


def new_comics_partial(request):
    """HTMX: load the next page of New comics cards for the dashboard panel."""
    from apps.core.models import get_setting
    from django.utils import timezone
    from datetime import timedelta

    PAGE = 8
    try:
        offset = int(request.GET.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0

    _new_qs = (
        Comic.objects.filter(state=Comic.STATE_NEW, file_format="cbz", medium=Comic.MEDIUM_DIGITAL)
        .exclude(proposed_series__isnull=True).exclude(proposed_series="")
        .order_by("-imported_at")
    )
    comics = list(_new_qs[offset : offset + PAGE])
    total = _new_qs.count()
    next_offset = offset + PAGE
    has_more = next_offset < total

    return render(request, "dashboard/_new_comics_partial.html", {
        "comics": comics,
        "next_offset": next_offset,
        "has_more": has_more,
    })


# =============================================================================
# Smart List Views
# =============================================================================

# Field options for the filter form
FILTER_FIELD_OPTIONS = [
    # Core metadata
    ("series", "Series"),
    ("title", "Title"),
    ("number", "Number"),
    ("volume", "Volume"),
    ("year", "Year"),
    ("publisher", "Publisher"),
    ("format", "Format"),
    ("medium", "Medium"),
    ("state", "State"),
    ("count", "Issue Count"),
    ("page_count", "Page Count"),
    ("characters", "Characters"),
    ("main_character_or_team", "Main Character/Team"),
    ("series_group", "Series Group"),
    ("genre", "Genre"),
    ("writer", "Writer"),
    ("penciller", "Penciller"),
    ("is_duplicate", "Is Duplicate"),
    ("file_path", "File Path"),
    ("file_format", "File Format"),
    # Proposed fields (filename-parsed, populated for STATE_NEW)
    ("proposed_series", "Proposed Series"),
    ("proposed_number", "Proposed Number"),
    ("proposed_volume", "Proposed Volume"),
    ("proposed_year", "Proposed Year"),
    # Workflow tracking
    ("needs_reorganize", "Needs Reorganize"),
    ("needs_reformat", "Needs Reformat"),
    ("last_written", "Last Written"),
    ("imported_at", "Import Date"),
    # Flags (stored in JSONField — use flags__<key> syntax)
    ("flags__corrupted_archive", "Flag: Corrupted Archive"),
    ("flags__low_page_count", "Flag: Low Page Count"),
    ("flags__is_pdf", "Flag: PDF"),
    ("flags__no_series", "Flag: No Series"),
    ("flags__cover_only", "Flag: Cover Only"),
    ("flags__needs_conversion", "Flag: Needs Conversion"),
    ("flags__is_zip", "Flag: ZIP File"),
    ("flags__missing_count", "Flag: Missing Count"),
    ("flags__count_mismatch", "Flag: Count Mismatch"),
    ("flags__scrape_no_match", "Flag: No Scrape Match"),
    ("flags__scrape_error", "Flag: Scrape Error"),
    ("flags__scrape_skipped", "Flag: Scrape Skipped"),
    ("flags__unknown_publisher", "Flag: Unknown Publisher"),
    # ComicVine custom values
    ("custom_values__comicvine_volume", "CV Volume ID"),
    ("custom_values__comicvine_issue", "CV Issue ID"),
    ("custom_values__comicvine_issue_count", "CV Issue Count"),
    ("custom_values__scrape_source", "Scrape Source"),
    ("custom_values__scrape_score", "Scrape Score"),
    # DataManager custom values
    ("custom_values__DataManager_Processed", "DataManager Processed"),
    ("custom_values__Original Format", "Original Format"),
    ("custom_values__Leading Numbers", "Leading Numbers"),
    ("custom_values__First Series", "First Series"),
    ("custom_values__Second Series", "Second Series"),
    ("custom_values__IsStarWars", "IsStarWars"),
    ("custom_values__HasAltCovers", "Has Alt Covers"),
]

FILTER_LOOKUP_OPTIONS = [
    ("exact", "equals"),
    ("not_exact", "not equals"),
    ("icontains", "contains"),
    ("not_icontains", "not contains"),
    ("istartswith", "starts with"),
    ("not_istartswith", "not starts with"),
    ("iendswith", "ends with"),
    ("not_iendswith", "not ends with"),
    ("gt", "greater than"),
    ("lt", "less than"),
    ("gte", "at least"),
    ("lte", "at most"),
    ("isnull", "is empty"),
    ("not_isnull", "is not empty"),
]

SORT_OPTIONS = [
    ("series", "Series"),
    ("number", "Number"),
    ("publisher", "Publisher"),
    ("year", "Year"),
    ("state", "State"),
    ("format", "Format"),
    ("pages", "Pages"),
    ("count", "Issue Count"),
    ("updated", "Updated"),
    ("imported", "Import Date"),
    ("last_written", "Last Written"),
]


def smartlist_index(request):
    """List all smart lists with their comic counts."""
    smart_lists = []
    for sl in SmartList.objects.all():
        qs = build_queryset(sl)
        entry = {"smartlist": sl, "count": qs.count()}
        if sl.has_cv_volume:
            missing_data = get_missing_issues(sl)
            if missing_data:
                entry["completion"] = missing_data["completion"]
                entry["owned"] = missing_data["owned_count"]
                entry["missing"] = missing_data["missing_count"]
                entry["total_issues"] = missing_data["total_count"]
        smart_lists.append(entry)

    return render(request, "dashboard/smartlist_index.html", {
        "smart_lists": smart_lists,
    })


def _parse_filters_from_post(post_data):
    """Parse filter data from POST into JSON list via the filters_json hidden field."""
    import json
    filters_json = post_data.get("filters_json", "")
    if filters_json:
        try:
            return json.loads(filters_json)
        except (json.JSONDecodeError, ValueError):
            pass
    return []


def _parse_cbl(xml_bytes):
    """
    Parse a ComicRack CBL file into (name, filters, warnings).

    filters: list of SmartList filter dicts (leaf or group).
    warnings: list of strings for skipped/unsupported matchers.
    """
    import defusedxml.ElementTree as ET

    XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"

    FIELD_MAP = {
        "ComicBookPublisherMatcher": "publisher",
        "ComicBookSeriesMatcher": "series",
        "ComicBookTitleMatcher": "title",
        "ComicBookNumberMatcher": "number",
        "ComicBookVolumeMatcher": "volume",
        "ComicBookYearMatcher": "year",
        "ComicBookFullPathMatcher": "file_path",
        "ComicBookFileMatcher": "file_path",
        "ComicBookFormatMatcher": "format",
        "ComicBookMainCharacterOrTeamMatcher": "main_character_or_team",
        "ComicBookTagsMatcher": "genre",
        "ComicBookSummaryMatcher": "summary",
    }

    # FormatMatcher and MainCharacterOrTeamMatcher treat empty MatchValue as isnull
    ISNULL_ON_EMPTY = {"ComicBookFormatMatcher", "ComicBookMainCharacterOrTeamMatcher"}

    OPERATOR_MAP = {
        None: "exact",
        "0": "exact",
        "1": "icontains",
        "3": "iendswith",
        "4": "istartswith",
    }

    warnings = []

    def parse_matcher(el):
        short_type = el.get(XSI_TYPE, "").split(":")[-1]
        negated = el.get("Not") == "true"

        if short_type == "ComicBookGroupMatcher":
            mode_attr = el.get("MatcherMode", "And")
            mode = "or" if mode_attr == "Or" else "and"
            sub_filters = []
            matchers_el = el.find("Matchers")
            if matchers_el is not None:
                for sub_el in matchers_el:
                    result = parse_matcher(sub_el)
                    if result is not None:
                        sub_filters.append(result)
            return {"mode": mode, "filters": sub_filters} if sub_filters else None

        if short_type == "ComicBookCustomValuesMatcher":
            key = (el.findtext("MatchValue") or "").strip()
            if not key:
                return None
            field = f"custom_values__{key}"
            val2_el = el.find("MatchValue2")
            if val2_el is None:
                lookup = "isnull" if negated else "not_isnull"
                return {"field": field, "lookup": lookup, "value": "true"}
            lookup = "not_exact" if negated else "exact"
            return {"field": field, "lookup": lookup, "value": (val2_el.text or "").strip()}

        field = FIELD_MAP.get(short_type)
        if field is None:
            if short_type:
                warnings.append(f"Skipped unsupported matcher: {short_type}")
            return None

        op = el.get("MatchOperator")
        base_lookup = OPERATOR_MAP.get(op, "icontains")
        match_value = (el.findtext("MatchValue") or "").strip()

        if not match_value and short_type in ISNULL_ON_EMPTY:
            lookup = "isnull" if negated else "not_isnull"
            return {"field": field, "lookup": lookup, "value": "true"}

        if not match_value:
            return None

        lookup = f"not_{base_lookup}" if negated else base_lookup
        return {"field": field, "lookup": lookup, "value": match_value}

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise ValueError(f"Invalid XML: {e}")

    name = (root.findtext("Name") or "Imported Smart List").strip()

    # ComicManager complete exports embed the full filter JSON for lossless round-trips.
    cm_filters_el = root.find("ComicManagerFilters")
    if cm_filters_el is not None and cm_filters_el.text:
        import json as _json
        try:
            filters = _json.loads(cm_filters_el.text)
            return name, filters, []
        except (ValueError, TypeError):
            pass  # Fall through to standard CBL parsing

    filters = []
    matchers_el = root.find("Matchers")
    if matchers_el is not None:
        for el in matchers_el:
            result = parse_matcher(el)
            if result is not None:
                filters.append(result)

    return name, filters, warnings


def _collect_unknown_fields(filters, known_fields):
    """Return a set of field values in the filter tree that are not in known_fields."""
    unknown = set()
    for item in (filters or []):
        if "mode" in item:
            unknown |= _collect_unknown_fields(item.get("filters", []), known_fields)
        else:
            field = item.get("field", "")
            if field and field not in known_fields:
                unknown.add(field)
    return unknown


def _apply_field_mappings(filters, mappings):
    """
    Walk the filter tree and apply field substitutions from mappings dict.
    mappings: {old_field: new_field}  — empty string new_field means skip that filter.
    """
    result = []
    for item in (filters or []):
        if "mode" in item:
            sub = _apply_field_mappings(item.get("filters", []), mappings)
            if sub:
                result.append({"mode": item["mode"], "filters": sub})
        else:
            field = item.get("field", "")
            if field in mappings:
                new_field = mappings[field]
                if new_field:
                    result.append({**item, "field": new_field})
                # empty string → skip
            else:
                result.append(item)
    return result


def smartlist_import_cbl(request):
    """Import a ComicRack CBL file as a new SmartList."""
    import json
    from django.contrib import messages

    known_fields = {v for v, _ in FILTER_FIELD_OPTIONS}

    if request.method == "POST":
        step = request.POST.get("step", "upload")

        # ── Step 2: user has resolved unknown field mappings ──────────────────
        if step == "map":
            try:
                cbl_name = request.POST.get("cbl_name", "Imported Smart List")
                cbl_warnings = json.loads(request.POST.get("cbl_warnings", "[]"))
                filters = json.loads(request.POST.get("cbl_filters", "[]"))
            except (json.JSONDecodeError, ValueError):
                messages.error(request, "Invalid mapping data. Please re-upload the file.")
                return render(request, "dashboard/smartlist_import_cbl.html")

            # Build mappings from posted fields: mapping_<old_field> = new_field
            mappings = {}
            for key, val in request.POST.items():
                if key.startswith("mapping_"):
                    old_field = key[len("mapping_"):]
                    mappings[old_field] = val  # empty string = skip

            filters = _apply_field_mappings(filters, mappings)
            sl = SmartList.objects.create(name=cbl_name, filters=filters)

            for warning in cbl_warnings:
                messages.warning(request, warning)
            messages.success(request, f"Imported '{cbl_name}' successfully.")
            return redirect("dashboard:smartlist_edit", pk=sl.pk)

        # ── Step 1: file upload ───────────────────────────────────────────────
        uploaded = request.FILES.get("cbl_file")
        if not uploaded:
            messages.error(request, "No file uploaded.")
            return render(request, "dashboard/smartlist_import_cbl.html")

        try:
            name, filters, warnings = _parse_cbl(uploaded.read())
        except ValueError as e:
            messages.error(request, f"Failed to parse CBL file: {e}")
            return render(request, "dashboard/smartlist_import_cbl.html")

        unknown_fields = _collect_unknown_fields(filters, known_fields)

        if unknown_fields:
            return render(request, "dashboard/smartlist_import_cbl_map.html", {
                "cbl_name": name,
                "cbl_filters": json.dumps(filters),
                "cbl_warnings": json.dumps(warnings),
                "unknown_fields": sorted(unknown_fields),
                "field_options": FILTER_FIELD_OPTIONS,
            })

        sl = SmartList.objects.create(name=name, filters=filters)
        for warning in warnings:
            messages.warning(request, warning)
        messages.success(request, f"Imported '{name}' successfully.")
        return redirect("dashboard:smartlist_edit", pk=sl.pk)

    return render(request, "dashboard/smartlist_import_cbl.html")


def _export_cbl_xml(smart_list, complete=False):
    """
    Convert a SmartList's filters to CBL XML bytes.

    Returns (xml_bytes, warnings) where warnings is a list of strings describing
    filters that could not be mapped to CBL and were skipped.

    When complete=True, the full filter JSON is embedded in a <ComicManagerFilters>
    element so the file can be re-imported into ComicManager without any data loss.
    """
    import xml.etree.ElementTree as ET

    FIELD_MAP = {
        "publisher": "ComicBookPublisherMatcher",
        "series": "ComicBookSeriesMatcher",
        "title": "ComicBookTitleMatcher",
        "number": "ComicBookNumberMatcher",
        "volume": "ComicBookVolumeMatcher",
        "year": "ComicBookYearMatcher",
        "file_path": "ComicBookFullPathMatcher",
        "format": "ComicBookFormatMatcher",
        "main_character_or_team": "ComicBookMainCharacterOrTeamMatcher",
        "genre": "ComicBookTagsMatcher",
        "summary": "ComicBookSummaryMatcher",
    }

    # These fields support isnull/not_isnull via empty MatchValue
    ISNULL_ON_EMPTY = {"format", "main_character_or_team"}

    OPERATOR_MAP = {
        "exact": None,
        "icontains": "1",
        "iendswith": "3",
        "istartswith": "4",
    }

    XSI = "http://www.w3.org/2001/XMLSchema-instance"
    XSD = "http://www.w3.org/2001/XMLSchema"
    warnings = []

    def make_matcher_el(xsi_type, not_attr=False, operator=None, match_value="", match_value2=None):
        el = ET.Element("ComicBookMatcher")
        el.set(f"{{{XSI}}}type", xsi_type)
        if not_attr:
            el.set("Not", "true")
        if operator is not None:
            el.set("MatchOperator", operator)
        mv = ET.SubElement(el, "MatchValue")
        mv.text = match_value
        if match_value2 is not None:
            mv2 = ET.SubElement(el, "MatchValue2")
            mv2.text = match_value2
        return el

    def convert_leaf(f):
        field = f.get("field", "")
        lookup = f.get("lookup", "exact")
        value = str(f.get("value", ""))

        negated = lookup.startswith("not_")
        base_lookup = lookup[4:] if negated else lookup

        # Custom values
        if field.startswith("custom_values__"):
            key = field[len("custom_values__"):]
            if base_lookup == "isnull":
                return make_matcher_el(
                    "ComicBookCustomValuesMatcher",
                    not_attr=not negated,  # isnull=True means key absent; Not="true" = key absent
                    match_value=key,
                )
            if base_lookup == "exact":
                return make_matcher_el(
                    "ComicBookCustomValuesMatcher",
                    not_attr=negated,
                    match_value=key,
                    match_value2=value,
                )
            warnings.append(f"Skipped custom_values__{key}: lookup '{lookup}' not supported in CBL")
            return None

        # isnull/not_isnull on special fields
        if base_lookup == "isnull":
            if field in ISNULL_ON_EMPTY:
                xsi_type = FIELD_MAP[field]
                # Import maps: Not="true" → isnull, No Not → not_isnull.
                # Export reverses: isnull → Not="true" (not_attr=True), not_isnull → no Not (not_attr=False).
                # negated=False for isnull, negated=True for not_isnull → not_attr = not negated.
                return make_matcher_el(xsi_type, not_attr=not negated, match_value="")
            warnings.append(f"Skipped '{field}': 'is empty' not supported in CBL for this field")
            return None

        xsi_type = FIELD_MAP.get(field)
        if xsi_type is None:
            warnings.append(f"Skipped '{field}': no CBL matcher equivalent")
            return None

        operator = OPERATOR_MAP.get(base_lookup)
        if operator is None and base_lookup != "exact":
            warnings.append(f"Skipped '{field}': lookup '{lookup}' not supported in CBL")
            return None

        return make_matcher_el(xsi_type, not_attr=negated, operator=operator, match_value=value)

    def convert_items(filter_list, parent_el):
        for item in (filter_list or []):
            if "mode" in item:
                mode = item.get("mode", "and")
                group_el = ET.SubElement(parent_el, "ComicBookMatcher")
                group_el.set(f"{{{XSI}}}type", "ComicBookGroupMatcher")
                if mode == "or":
                    group_el.set("MatcherMode", "Or")
                sub_matchers = ET.SubElement(group_el, "Matchers")
                convert_items(item.get("filters", []), sub_matchers)
                if len(sub_matchers) == 0:
                    parent_el.remove(group_el)
            else:
                el = convert_leaf(item)
                if el is not None:
                    parent_el.append(el)

    ET.register_namespace("xsd", XSD)
    ET.register_namespace("xsi", XSI)

    root = ET.Element("ReadingList")
    # Set xsd manually (never used in attributes so ET won't auto-declare it).
    # xsi is auto-declared by ET when it serialises the xsi:type attributes.
    root.set("xmlns:xsd", XSD)

    name_el = ET.SubElement(root, "Name")
    name_el.text = smart_list.name

    ET.SubElement(root, "Books")

    matchers_el = ET.SubElement(root, "Matchers")
    convert_items(smart_list.filters or [], matchers_el)

    if complete:
        import json as _json
        cm_el = ET.SubElement(root, "ComicManagerFilters")
        cm_el.text = _json.dumps(smart_list.filters or [])

    ET.indent(root, space="  ")
    xml_bytes = b'<?xml version="1.0"?>\n' + ET.tostring(root, encoding="unicode").encode("utf-8")
    return xml_bytes, warnings


def smartlist_export_cbl(request, pk):
    """Export a SmartList as a ComicRack CBL file."""
    sl = get_object_or_404(SmartList, pk=pk)
    mode = request.GET.get("mode", "")

    if mode == "complete":
        xml_bytes, _ = _export_cbl_xml(sl, complete=True)
        safe_name = "".join(c if c.isalnum() or c in " .-_" else "_" for c in sl.name)
        response = HttpResponse(xml_bytes, content_type="application/octet-stream")
        response["Content-Disposition"] = f'attachment; filename="{safe_name}.cbl"'
        return response

    xml_bytes, warnings = _export_cbl_xml(sl, complete=False)

    if mode == "comicrak" or not warnings:
        safe_name = "".join(c if c.isalnum() or c in " .-_" else "_" for c in sl.name)
        response = HttpResponse(xml_bytes, content_type="application/octet-stream")
        response["Content-Disposition"] = f'attachment; filename="{safe_name}.cbl"'
        return response

    return render(request, "dashboard/smartlist_export_cbl_warn.html", {
        "smart_list": sl,
        "warnings": warnings,
    })


def smartlist_create(request):
    """Create a new smart list."""
    if request.method == "POST":
        filters = _parse_filters_from_post(request.POST)
        cv_volume_id = request.POST.get("comicvine_volume_id") or None
        cv_volume_name = request.POST.get("comicvine_volume_name", "")

        sl = SmartList.objects.create(
            name=request.POST.get("name", "Untitled"),
            description=request.POST.get("description", ""),
            filters=filters,
            comicvine_volume_id=int(cv_volume_id) if cv_volume_id else None,
            comicvine_volume_name=cv_volume_name,
            sort_field=request.POST.get("sort_field", "series"),
            sort_direction=request.POST.get("sort_direction", "asc"),
            columns=request.POST.getlist("columns"),
            icon=request.POST.get("icon", ""),
            show_on_dashboard="show_on_dashboard" in request.POST,
        )
        return redirect("dashboard:smartlist_detail", pk=sl.pk)

    return render(request, "dashboard/smartlist_form.html", {
        "mode": "create",
        "field_options": FILTER_FIELD_OPTIONS,
        "lookup_options": FILTER_LOOKUP_OPTIONS,
        "sort_options": SORT_OPTIONS,
        "all_columns": COLUMNS_REGISTRY,
        "default_columns": DEFAULT_COLUMNS,
    })


def smartlist_edit(request, pk):
    """Edit an existing smart list."""
    sl = get_object_or_404(SmartList, pk=pk)

    if request.method == "POST":
        filters = _parse_filters_from_post(request.POST)
        cv_volume_id = request.POST.get("comicvine_volume_id") or None
        cv_volume_name = request.POST.get("comicvine_volume_name", "")

        sl.name = request.POST.get("name", sl.name)
        sl.description = request.POST.get("description", "")
        sl.filters = filters
        sl.comicvine_volume_id = int(cv_volume_id) if cv_volume_id else None
        sl.comicvine_volume_name = cv_volume_name
        sl.sort_field = request.POST.get("sort_field", "series")
        sl.sort_direction = request.POST.get("sort_direction", "asc")
        sl.columns = request.POST.getlist("columns")
        sl.icon = request.POST.get("icon", "")
        sl.show_on_dashboard = "show_on_dashboard" in request.POST
        sl.save()

        return redirect("dashboard:smartlist_detail", pk=sl.pk)

    return render(request, "dashboard/smartlist_form.html", {
        "mode": "edit",
        "smart_list": sl,
        "field_options": FILTER_FIELD_OPTIONS,
        "lookup_options": FILTER_LOOKUP_OPTIONS,
        "sort_options": SORT_OPTIONS,
        "all_columns": COLUMNS_REGISTRY,
        "default_columns": DEFAULT_COLUMNS,
    })


@require_POST
def smartlist_delete(request, pk):
    """Delete a smart list."""
    sl = get_object_or_404(SmartList, pk=pk)
    sl.delete()
    return redirect("dashboard:smartlist_index")


def smartlist_detail(request, pk):
    """View the comics matching a smart list's filters."""
    from django.core.paginator import Paginator
    from apps.dashboard.services import SORT_FIELDS
    from django.db.models import F

    sl = get_object_or_404(SmartList, pk=pk)

    # Use GET col params if provided, else smart list saved columns, else default
    get_cols = request.GET.getlist("col")
    active_columns = get_cols if get_cols else (sl.columns if sl.columns else DEFAULT_COLUMNS)

    # Allow runtime sort override via GET params
    sort = request.GET.get("sort", sl.sort_field or "series")
    sort_dir = request.GET.get("dir", sl.sort_direction or "asc")

    comics = build_queryset(sl)

    # Override ordering with runtime sort
    if sort == "page_count":
        page_order = F("page_count").desc(nulls_last=True) if sort_dir == "desc" else F("page_count").asc(nulls_last=True)
        comics = comics.order_by(page_order, "series", "volume", "number_sort_key", "number")
    else:
        order_fields = SORT_FIELDS.get(sort, [sort, "series", "volume", "number_sort_key", "number"])
        if sort_dir == "desc":
            order_fields = [f"-{f}" for f in order_fields]
        comics = comics.order_by(*order_fields)

    total_count = comics.count()

    # Paginate
    per_page = int(request.GET.get("per_page", 100))
    per_page = min(max(per_page, 25), 500)
    paginator = Paginator(comics, per_page)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    # Get completion info if CV volume is linked
    completion_data = None
    if sl.has_cv_volume:
        missing_data = get_missing_issues(sl)
        if missing_data:
            completion_data = {
                "completion": missing_data["completion"],
                "owned": missing_data["owned_count"],
                "missing": missing_data["missing_count"],
                "total": missing_data["total_count"],
            }

    query_params = request.GET.copy()
    query_params.pop("page", None)
    query_string = query_params.urlencode()

    return render(request, "dashboard/smartlist_detail.html", {
        "smart_list": sl,
        "comics": page_obj,
        "page_obj": page_obj,
        "comic_count": total_count,
        "completion_data": completion_data,
        "active_columns": active_columns,
        "all_columns": dict(sorted(COLUMNS_REGISTRY.items(), key=lambda x: x[1]["label"])),
        "current_sort": sort,
        "current_dir": sort_dir,
        "query_string": query_string,
    })


def smartlist_missing(request, pk):
    """Show missing issues comparison for a smart list with a CV volume."""
    sl = get_object_or_404(SmartList, pk=pk)

    if not sl.has_cv_volume:
        return redirect("dashboard:smartlist_detail", pk=pk)

    missing_data = get_missing_issues(sl)

    return render(request, "dashboard/smartlist_missing.html", {
        "smart_list": sl,
        "data": missing_data,
    })


def smartlist_cv_search(request):
    """HTMX endpoint: search CV volumes by name."""
    query = request.GET.get("q", "").strip()
    results = search_cv_volumes(query)

    # Return HTML partial for HTMX
    html = ""
    if not results:
        if query:
            html = '<div class="p-3 text-base-content/50 text-sm">No volumes found</div>'
    else:
        for vol in results:
            vol_id = vol["id"]
            vol_name = _escape_js(vol["name"])
            vol_year = _escape_js(str(vol["start_year"] or ""))
            publisher = vol["publisher"] or "Unknown"
            pub_js = _escape_js(publisher)
            count = vol["count_of_issues"] or 0
            label = "{} ({})".format(vol["name"], vol["start_year"] or "?")
            onclick = "selectCvVolume({}, '{}', '{}', '{}')".format(
                vol_id, vol_name, vol_year, pub_js
            )
            html += (
                '<button type="button" '
                'class="w-full text-left p-2 hover:bg-base-300 rounded flex justify-between items-center" '
                'onclick="{}">'
                '<div>'
                '<div class="font-medium text-sm">{}</div>'
                '<div class="text-xs text-base-content/60">{} - {} issues</div>'
                '</div>'
                '<span class="badge badge-sm badge-ghost">#{}</span>'
                '</button>'
            ).format(
                _escape_html(onclick),
                _escape_html(label),
                _escape_html(publisher), count,
                vol_id,
            )

    return HttpResponse(html)


def _escape_html(text):
    """Escape HTML special characters."""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;"))


def _escape_js(text):
    """Escape text for use in JS string literals."""
    return (str(text)
            .replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace('"', '\\"'))


@require_POST
def smartlist_run_action(request, pk):
    """
    Dispatch a Celery task to run a workflow action on all comics in a Smart List.

    POST params:
        action: 'tag' | 'format' | 'organize' | 'write'
    """
    from celery.result import AsyncResult

    sl = get_object_or_404(SmartList, pk=pk)
    action = request.POST.get("action", "")

    if action not in ("tag", "format", "organize", "write"):
        return JsonResponse({"success": False, "error": f"Invalid action: {action}"}, status=400)

    conflict = active_task_conflict(request, session_key="smartlist_action_task_id", error="An action is already running")
    if conflict:
        return conflict

    # Count comics
    qs = build_queryset(sl)
    count = qs.count()
    if count == 0:
        return JsonResponse({
            "success": True,
            "processed": 0,
            "total": 0,
            "message": "No comics in this smart list",
        })

    from .tasks import run_smartlist_action_task
    result = run_smartlist_action_task.delay(str(sl.pk), action)
    request.session["smartlist_action_task_id"] = result.id

    action_labels = {"tag": "Re-tagging", "format": "Re-formatting", "organize": "Re-organizing", "write": "Writing"}
    return JsonResponse({
        "success": True,
        "task_id": result.id,
        "total": count,
        "message": f"{action_labels.get(action, action)} {count} comics in background",
    })


