"""
Library Organizer Views - Profile management and organization operations.
"""

import json
import os
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST, require_GET
from django.contrib import messages

from apps.core.models import Comic

from .models import OrganizerProfile
from .parser import import_profiles
from .engine import FIELD_MAP, NUMERIC_FIELDS
from .services import (
    organize_comic,
    organize_all_comics,
    preview_organization,
    get_organization_stats,
)

# Available fields for rule editor (deduplicated, user-friendly names)
RULE_FIELDS = sorted(set(FIELD_MAP.keys()) - {"SeriesGroup", "MainCharacterOrTeam", "Main Character"})

# Available operators for rule editor
RULE_OPERATORS = ["is", "is not", "contains", "does not contain", "starts with", "ends with"]
NUMERIC_OPERATORS = ["greater than", "less than", "greater than or equal to", "less than or equal to"]


def _get_custom_value_keys():
    """Get sorted list of distinct keys used in custom_values across all comics."""
    all_cv = Comic.objects.exclude(custom_values={}).values_list("custom_values", flat=True)
    return sorted({k for cv in all_cv for k in cv.keys()})


def _parse_exclude_rules(post_data) -> dict:
    """Parse exclude_rules JSON from POST data."""
    raw = post_data.get("exclude_rules", "")
    if not raw or raw.strip() == "":
        return {}
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        # Validate structure
        return {
            "mode": data.get("mode", "Only"),
            "operator": data.get("operator", "All"),
            "rules": data.get("rules", []),
        }
    except (json.JSONDecodeError, TypeError):
        return {}


# ============================================================================
# Profile CRUD Views
# ============================================================================

def profile_list(request):
    """List all organizer profiles."""
    profiles = OrganizerProfile.objects.all().order_by('priority')
    stats = get_organization_stats()

    return render(request, 'organizer/profile_list.html', {
        'profiles': profiles,
        'stats': stats,
    })


def profile_detail(request, pk):
    """View a single profile's details."""
    profile = get_object_or_404(OrganizerProfile, pk=pk)

    return render(request, 'organizer/profile_detail.html', {
        'profile': profile,
    })


def profile_create(request):
    """Create a new profile."""
    if request.method == 'POST':
        exclude_rules = _parse_exclude_rules(request.POST)
        profile = OrganizerProfile.objects.create(
            name=request.POST.get('name', 'New Profile'),
            priority=OrganizerProfile.objects.count(),
            folder_template=request.POST.get('folder_template', '{<publisher>}/{<series>}'),
            file_template=request.POST.get('file_template', '{<series>} #{<number3>}'),
            base_folder=request.POST.get('base_folder', '/comics/library'),
            exclude_rules=exclude_rules,
            illegal_characters=OrganizerProfile.get_default_illegal_characters(),
            months=OrganizerProfile.get_default_months(),
        )
        messages.success(request, f'Profile "{profile.name}" created.')
        return redirect('organizer:profile_detail', pk=profile.pk)

    return render(request, 'organizer/profile_form.html', {
        'profile': None,
        'is_create': True,
        'rule_fields': json.dumps(RULE_FIELDS),
        'rule_operators': json.dumps(RULE_OPERATORS),
        'numeric_operators': json.dumps(NUMERIC_OPERATORS),
        'numeric_fields': json.dumps(sorted(NUMERIC_FIELDS)),
        'exclude_rules_json': '{}',
        'custom_value_keys': json.dumps(_get_custom_value_keys()),
    })


def profile_edit(request, pk):
    """Edit an existing profile."""
    profile = get_object_or_404(OrganizerProfile, pk=pk)

    if request.method == 'POST':
        profile.name = request.POST.get('name', profile.name)
        profile.folder_template = request.POST.get('folder_template', profile.folder_template)
        profile.file_template = request.POST.get('file_template', profile.file_template)
        profile.base_folder = request.POST.get('base_folder', profile.base_folder)
        profile.is_enabled = request.POST.get('is_enabled') == 'on'
        profile.exclude_rules = _parse_exclude_rules(request.POST)
        profile.save()

        messages.success(request, f'Profile "{profile.name}" updated.')
        return redirect('organizer:profile_list')

    return render(request, 'organizer/profile_form.html', {
        'profile': profile,
        'is_create': False,
        'rule_fields': json.dumps(RULE_FIELDS),
        'rule_operators': json.dumps(RULE_OPERATORS),
        'numeric_operators': json.dumps(NUMERIC_OPERATORS),
        'numeric_fields': json.dumps(sorted(NUMERIC_FIELDS)),
        'exclude_rules_json': json.dumps(profile.exclude_rules or {}),
        'custom_value_keys': json.dumps(_get_custom_value_keys()),
    })


@require_POST
def profile_delete(request, pk):
    """Delete a profile."""
    profile = get_object_or_404(OrganizerProfile, pk=pk)
    name = profile.name
    profile.delete()

    messages.success(request, f'Profile "{name}" deleted.')
    return redirect('organizer:profile_list')


@require_POST
def profile_duplicate(request, pk):
    """Duplicate a profile."""
    profile = get_object_or_404(OrganizerProfile, pk=pk)

    new_profile = OrganizerProfile.objects.create(
        name=f"{profile.name} (Copy)",
        priority=OrganizerProfile.objects.count(),
        folder_template=profile.folder_template,
        file_template=profile.file_template,
        base_folder=profile.base_folder,
        exclude_rules=profile.exclude_rules,
        illegal_characters=profile.illegal_characters,
        months=profile.months,
        remove_empty_folder=profile.remove_empty_folder,
        auto_space_fields=profile.auto_space_fields,
        replace_multiple_spaces=profile.replace_multiple_spaces,
    )

    messages.success(request, f'Profile duplicated as "{new_profile.name}".')
    return redirect('organizer:profile_edit', pk=new_profile.pk)


@require_POST
def profile_toggle(request, pk):
    """Toggle profile enabled/disabled."""
    profile = get_object_or_404(OrganizerProfile, pk=pk)
    profile.is_enabled = not profile.is_enabled
    profile.save()

    status = "enabled" if profile.is_enabled else "disabled"
    return JsonResponse({
        'success': True,
        'message': f'Profile "{profile.name}" {status}.',
        'is_enabled': profile.is_enabled,
    })


@require_POST
def profile_reorder(request):
    """Accept an ordered list of profile PKs and reassign priorities."""
    try:
        body = json.loads(request.body)
        ordered_ids = body.get("order", [])
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    if not isinstance(ordered_ids, list):
        return JsonResponse({"error": "order must be a list"}, status=400)

    profiles = {p.pk: p for p in OrganizerProfile.objects.filter(pk__in=ordered_ids)}
    to_update = []
    for new_priority, pk in enumerate(ordered_ids):
        profile = profiles.get(pk)
        if profile and profile.priority != new_priority:
            profile.priority = new_priority
            to_update.append(profile)

    OrganizerProfile.objects.bulk_update(to_update, ["priority"])
    return JsonResponse({"success": True})


# ============================================================================
# Import/Export Views
# ============================================================================

def import_view(request):
    """Import profiles from a .lop file."""
    if request.method == 'POST':
        uploaded_file = request.FILES.get('lop_file')

        if not uploaded_file:
            messages.error(request, 'No file uploaded.')
            return redirect('organizer:import')

        # Save uploaded file temporarily
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix='.lop') as tmp:
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        try:
            clear_existing = request.POST.get('clear_existing') == 'on'
            result = import_profiles(tmp_path, clear_existing=clear_existing)

            if result['success']:
                messages.success(
                    request,
                    f"Imported {result['imported_count']} profiles. "
                    f"Deleted {result['deleted_count']} existing profiles."
                )
            else:
                messages.error(request, f"Import failed: {result.get('error', 'Unknown error')}")

        except Exception as e:
            messages.error(request, f"Import failed: {str(e)}")

        finally:
            # Clean up temp file
            try:
                os.unlink(tmp_path)
            except:
                pass

        return redirect('organizer:profile_list')

    return render(request, 'organizer/import.html', {
        'existing_count': OrganizerProfile.objects.count(),
    })


# ============================================================================
# Preview View
# ============================================================================

@require_GET
def preview_view(request, pk):
    """Preview where a comic would be organized."""
    comic = get_object_or_404(Comic, pk=pk)
    preview = preview_organization(comic)

    return JsonResponse(preview)


# ============================================================================
# Path Audit Views
# ============================================================================

def path_audit(request):
    """Path Audit page - shows all comics flagged as needing reorganization."""
    from django.core.paginator import Paginator

    comics = (
        Comic.objects.filter(
            needs_reorganize=True,
            medium=Comic.MEDIUM_DIGITAL,
        )
        .order_by("publisher", "series", "number")
    )

    total_flagged = comics.count()
    total_organized = Comic.objects.filter(
        state__in=[Comic.STATE_ORGANIZED, Comic.STATE_WRITTEN],
        medium=Comic.MEDIUM_DIGITAL,
    ).count()

    paginator = Paginator(comics, 50)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(request, "organizer/path_audit.html", {
        "comics": page_obj,
        "page_obj": page_obj,
        "total_flagged": total_flagged,
        "total_organized": total_organized,
    })


@require_POST
def start_audit(request):
    """Dispatch Celery task to audit all organized/written comic paths."""
    from celery.result import AsyncResult

    active_task_id = request.session.get("audit_task_id")
    if active_task_id:
        result = AsyncResult(active_task_id)
        if result.state in ("PENDING", "STARTED", "PROGRESS"):
            return JsonResponse({
                "success": False,
                "error": "An audit task is already running",
                "task_id": active_task_id,
            }, status=409)

    count = Comic.objects.filter(
        state__in=[Comic.STATE_ORGANIZED, Comic.STATE_WRITTEN],
        medium=Comic.MEDIUM_DIGITAL,
    ).count()

    if count == 0:
        return JsonResponse({
            "success": True,
            "total": 0,
            "message": "No organized/written digital comics to audit",
        })

    from .tasks import audit_paths_task

    result = audit_paths_task.delay()
    request.session["audit_task_id"] = result.id

    return JsonResponse({
        "success": True,
        "task_id": result.id,
        "total": count,
        "message": f"Started auditing {count} comics",
    })


@require_POST
def start_reorganize_all(request):
    """Dispatch Celery task to reorganize all flagged comics."""
    from celery.result import AsyncResult

    active_task_id = request.session.get("reorganize_task_id")
    if active_task_id:
        result = AsyncResult(active_task_id)
        if result.state in ("PENDING", "STARTED", "PROGRESS"):
            return JsonResponse({
                "success": False,
                "error": "A reorganize task is already running",
                "task_id": active_task_id,
            }, status=409)

    count = Comic.objects.filter(
        needs_reorganize=True,
        medium=Comic.MEDIUM_DIGITAL,
    ).count()

    if count == 0:
        return JsonResponse({
            "success": True,
            "total": 0,
            "message": "No comics flagged for reorganization",
        })

    from .tasks import reorganize_all_flagged_task

    result = reorganize_all_flagged_task.delay()
    request.session["reorganize_task_id"] = result.id

    return JsonResponse({
        "success": True,
        "task_id": result.id,
        "total": count,
        "message": f"Started reorganizing {count} comics",
    })
