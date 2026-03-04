from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.db.models import Count
from apps.core.models import Comic
from .models import SmartList
from apps.core.utils import COLUMNS_REGISTRY, DEFAULT_COLUMNS
from .services import build_queryset, get_missing_issues, search_cv_volumes


def index(request):
    stats = {
        "total":     Comic.objects.count(),
        "digital":   Comic.objects.filter(medium="digital").count(),
        "physical":  Comic.objects.filter(medium="physical").count(),
        "new":       Comic.objects.filter(state="new").count(),
        "written":   Comic.objects.filter(state="written").count(),
    }

    # Get counts per workflow state
    state_counts = dict(
        Comic.objects.values("state").annotate(count=Count("id")).values_list("state", "count")
    )

    # Workflow pipeline stages
    pipeline = [
        {"state": "new", "label": "1. New", "description": "Awaiting processing", "action": "Accept All", "count": state_counts.get("new", 0)},
        {"state": "imported", "label": "2. Imported", "description": "File info extracted", "action": "Scrape All", "count": state_counts.get("imported", 0)},
        {"state": "counted", "label": "3. Counted", "description": "ComicVine matched + issue count set", "action": "Tag All", "count": state_counts.get("counted", 0)},
        {"state": "tagged", "label": "4. Tagged", "description": "Publisher rules applied", "action": "Format All", "count": state_counts.get("tagged", 0)},
        {"state": "formatted", "label": "5. Formatted", "description": "Format detected", "action": "Deduplicate All", "count": state_counts.get("formatted", 0)},
        {"state": "deduplicated", "label": "6. Deduplicated", "description": "Duplicates resolved", "action": "Organize All", "count": state_counts.get("deduplicated", 0)},
        {"state": "organized", "label": "7. Organized", "description": "Moved to library", "action": "Write All", "count": state_counts.get("organized", 0)},
        {"state": "written", "label": "8. Written", "description": "ComicInfo.xml saved", "action": None, "count": state_counts.get("written", 0)},
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
    ]

    flagged_count = Comic.objects.exclude(flags={}).count()

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

    from apps.scraper.cv_sources import get_cv_source_status, get_api_calls_used, get_api_calls_remaining, CV_API_BUDGET_LIMIT
    cv_status = get_cv_source_status()
    api_remaining = get_api_calls_remaining()
    api_remaining_pct = round(api_remaining / CV_API_BUDGET_LIMIT * 100)

    return render(request, "dashboard/index.html", {
        "stats": stats,
        "pipeline": pipeline,
        "review_queue": review_queue,
        "flagged_count": flagged_count,
        "needs_reorganize_count": needs_reorganize_count,
        "stale_count": stale_count,
        "dashboard_smartlists": dashboard_smartlists,
        "cv_status": cv_status,
        "api_calls_used": get_api_calls_used(),
        "api_calls_remaining": api_remaining,
        "api_calls_remaining_pct": api_remaining_pct,
        "api_budget_limit": CV_API_BUDGET_LIMIT,
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
    ("flags__missing_count", "Flag: Missing Count"),
    ("flags__count_mismatch", "Flag: Count Mismatch"),
    ("flags__scrape_no_match", "Flag: No Scrape Match"),
    ("flags__scrape_error", "Flag: Scrape Error"),
    ("flags__scrape_skipped", "Flag: Scrape Skipped"),
    # ComicVine custom values
    ("custom_values__comicvine_volume", "CV Volume ID"),
    ("custom_values__comicvine_issue", "CV Issue ID"),
    ("custom_values__scrape_source", "Scrape Source"),
]

FILTER_LOOKUP_OPTIONS = [
    ("exact", "equals"),
    ("not_exact", "not equals"),
    ("icontains", "contains"),
    ("not_icontains", "not contains"),
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
    """Parse filter arrays from POST data into JSON list."""
    fields = post_data.getlist("filter_field")
    lookups = post_data.getlist("filter_lookup")
    values = post_data.getlist("filter_value")

    filters = []
    for field, lookup, value in zip(fields, lookups, values):
        if field and value:  # Skip empty rows
            filters.append({
                "field": field,
                "lookup": lookup,
                "value": value,
            })
    return filters


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

    sl = get_object_or_404(SmartList, pk=pk)
    
    # Use SmartList columns if set, otherwise default
    active_columns = sl.columns if sl.columns else DEFAULT_COLUMNS

    comics = build_queryset(sl)
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

    return render(request, "dashboard/smartlist_detail.html", {
        "smart_list": sl,
        "comics": page_obj,
        "page_obj": page_obj,
        "comic_count": total_count,
        "completion_data": completion_data,
        "active_columns": active_columns,
        "all_columns": COLUMNS_REGISTRY,
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

    # Prevent double-submit
    active_task_id = request.session.get("smartlist_action_task_id")
    if active_task_id:
        result = AsyncResult(active_task_id)
        if result.state in ("PENDING", "STARTED", "PROGRESS"):
            return JsonResponse({
                "success": False,
                "error": "An action is already running",
                "task_id": active_task_id,
            }, status=409)

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
