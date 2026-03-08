"""
Duplicate Detection Views.

Provides UI for reviewing and resolving duplicate groups.
"""

from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET

from .models import DuplicateGroup, DuplicateGroupMembership
from .services import (
    run_duplicate_detection,
    scan_all_for_duplicates,
    resolve_keep,
    resolve_keep_and_delete_rest,
    resolve_requeue,
    resolve_delete,
    resolve_keep_all,
    get_pending_groups,
    get_duplicate_stats,
    get_resolution_history,
)


def duplicate_review(request):
    """
    Main duplicate review page.

    Shows pending duplicate groups, filterable by detection method.
    """
    stats = get_duplicate_stats()
    all_groups = get_pending_groups()
    method_filter = request.GET.get("method", "all")

    groups = all_groups if method_filter == "all" else [
        g for g in all_groups if g["detection_method"] == method_filter
    ]

    method_counts = {
        "all": len(all_groups),
        "cv_id": sum(1 for g in all_groups if g["detection_method"] == "cv_id"),
        "metadata": sum(1 for g in all_groups if g["detection_method"] == "metadata"),
        "phash": sum(1 for g in all_groups if g["detection_method"] == "phash"),
        "filename": sum(1 for g in all_groups if g["detection_method"] == "filename"),
    }

    return render(request, "duplicates/review.html", {
        "stats": stats,
        "groups": groups,
        "method_filter": method_filter,
        "method_counts": method_counts,
        "method_tabs": [
            ("All", "all"),
            ("CV ID", "cv_id"),
            ("Series/Number", "metadata"),
            ("Cover Hash", "phash"),
            ("Filename", "filename"),
        ],
        "total_pending": len(all_groups),
    })


def duplicate_group_detail(request, pk):
    """
    Detailed view of a single duplicate group.

    Shows side-by-side comparison of all comics in the group.
    """
    group = get_object_or_404(DuplicateGroup, pk=pk)
    memberships = group.memberships.filter(
        resolution=DuplicateGroupMembership.RESOLUTION_PENDING
    ).select_related("comic").order_by("phash_distance", "added_at")

    comics = []
    for membership in memberships:
        comic = membership.comic
        comics.append({
            "comic": comic,
            "membership": membership,
        })

    return render(request, "duplicates/group_detail.html", {
        "group": group,
        "comics": comics,
    })


@require_POST
def run_detection(request):
    """
    Trigger duplicate detection on all formatted comics.
    """
    result = run_duplicate_detection()

    return JsonResponse(result)


@require_POST
def scan_all(request):
    """
    Scan ALL digital comics for duplicates, regardless of state.

    Useful for catching duplicates that already passed through workflow.
    """
    result = scan_all_for_duplicates()

    return JsonResponse(result)


@require_POST
def resolve_group(request, pk):
    """
    Resolve a single comic in a duplicate group.

    POST params:
    - action: "keep" | "requeue" | "delete" | "keep_all"
    - comic_id: UUID of comic (required for keep/requeue/delete)
    - reason: Optional resolution reason
    """
    group = get_object_or_404(DuplicateGroup, pk=pk)

    if group.status != DuplicateGroup.STATUS_PENDING:
        return JsonResponse({
            "success": False,
            "error": f"Group already resolved with status: {group.status}"
        }, status=400)

    action = request.POST.get("action")
    reason = request.POST.get("reason", "")
    comic_id = request.POST.get("comic_id")

    if action == "keep":
        if not comic_id:
            return JsonResponse({
                "success": False,
                "error": "comic_id is required for keep action"
            }, status=400)
        result = resolve_keep(group, comic_id, reason)

    elif action == "requeue":
        if not comic_id:
            return JsonResponse({
                "success": False,
                "error": "comic_id is required for requeue action"
            }, status=400)
        result = resolve_requeue(group, comic_id, reason)

    elif action == "delete":
        if not comic_id:
            return JsonResponse({
                "success": False,
                "error": "comic_id is required for delete action"
            }, status=400)
        result = resolve_delete(group, comic_id, reason)

    elif action == "keep_all":
        result = resolve_keep_all(group, reason)

    else:
        return JsonResponse({
            "success": False,
            "error": f"Invalid action: {action}"
        }, status=400)

    return JsonResponse(result)


@require_POST
def resolve_group_htmx(request, pk):
    """
    HTMX endpoint for resolving a comic/group and returning updated partial.
    """
    group = get_object_or_404(DuplicateGroup, pk=pk)

    action = request.POST.get("action")
    reason = request.POST.get("reason", "")
    comic_id = request.POST.get("comic_id")

    result = None

    if action == "keep" and comic_id:
        result = resolve_keep(group, comic_id, reason)
    elif action == "keep_and_delete_rest" and comic_id:
        result = resolve_keep_and_delete_rest(group, comic_id, reason)
    elif action == "requeue" and comic_id:
        result = resolve_requeue(group, comic_id, reason)
    elif action == "delete" and comic_id:
        result = resolve_delete(group, comic_id, reason)
    elif action == "keep_all":
        result = resolve_keep_all(group, reason)

    # Refresh group from DB
    group.refresh_from_db()

    # Check if group is fully resolved
    if group.status != DuplicateGroup.STATUS_PENDING:
        return render(request, "duplicates/partials/group_resolved.html", {
            "group": group,
            "action": action,
            "result": result,
        })

    # Group still has pending comics - return updated card
    memberships = group.memberships.filter(
        resolution=DuplicateGroupMembership.RESOLUTION_PENDING
    ).select_related("comic").order_by("phash_distance", "added_at")

    comics_data = []
    for membership in memberships:
        comic = membership.comic
        comics_data.append({
            "id": str(comic.pk),
            "series": comic.series,
            "number": comic.number,
            "volume": comic.volume,
            "title": comic.title,
            "publisher": comic.publisher,
            "format": comic.format,
            "file_path": comic.file_path,
            "file_size": comic.file_size,
            "page_count": comic.page_count,
            "phash": comic.phash,
            "medium": comic.medium,
            "scrape_source": comic.custom_values.get("scrape_source"),
            "cv_issue": comic.custom_values.get("comicvine_issue"),
            "phash_distance": membership.phash_distance,
        })

    group_data = {
        "id": str(group.pk),
        "detection_method": group.detection_method,
        "detection_method_display": group.get_detection_method_display(),
        "match_key": group.match_key,
        "comic_count": len(comics_data),
        "comics": comics_data,
    }

    return render(request, "duplicates/partials/group_card.html", {
        "group": group_data,
        "result": result,
    })


def resolution_history(request):
    """
    View audit log of resolution decisions.
    """
    resolutions = get_resolution_history(limit=100)

    return render(request, "duplicates/history.html", {
        "resolutions": resolutions,
    })


@require_GET
def group_comics_partial(request, pk):
    """
    HTMX partial: Return just the comics table for a group.
    """
    group = get_object_or_404(DuplicateGroup, pk=pk)

    memberships = group.memberships.filter(
        resolution=DuplicateGroupMembership.RESOLUTION_PENDING
    ).select_related("comic").order_by("phash_distance", "added_at")

    comics_data = []
    for membership in memberships:
        comic = membership.comic
        comics_data.append({
            "id": str(comic.pk),
            "series": comic.series,
            "number": comic.number,
            "volume": comic.volume,
            "title": comic.title,
            "publisher": comic.publisher,
            "format": comic.format,
            "file_path": comic.file_path,
            "file_size": comic.file_size,
            "page_count": comic.page_count,
            "medium": comic.medium,
            "scrape_source": comic.custom_values.get("scrape_source"),
            "cv_issue": comic.custom_values.get("comicvine_issue"),
            "phash_distance": membership.phash_distance,
        })

    group_data = {
        "id": str(group.pk),
        "detection_method": group.detection_method,
        "comics": comics_data,
    }

    return render(request, "duplicates/partials/comics_table.html", {
        "group": group_data,
    })
