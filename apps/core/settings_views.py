
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.http import require_POST
from .models import Setting, UserPreference


MOOD_SWATCHES = [
    ("warm",   "Warm",   "#c8861a"),
    ("cool",   "Cool",   "#22d3ee"),
    ("forest", "Forest", "#4ade80"),
    ("rose",   "Rose",   "#f472b6"),
]

COLOR_PICKER_DEFS = [
    ("accent", "Accent"),
    ("bg",     "Background"),
    ("bg1",    "Card BG"),
    ("fg",     "Primary text"),
    ("fg1",    "Secondary text"),
]


def settings_index(request):
    settings = Setting.objects.all()
    # Group them for the template
    grouped = {}
    for s in settings:
        grouped.setdefault(s.group, []).append(s)

    from apps.scraper.cv_sources import get_cv_source_status, get_api_calls_remaining, get_api_calls_per_path, CV_API_BUDGET_LIMIT
    from .models import get_setting
    cv_status = get_cv_source_status()
    api_remaining = get_api_calls_remaining()

    prefs = UserPreference.get()
    custom = prefs.custom_colors or {}
    color_pickers = [(key, label, custom.get(key, "")) for key, label in COLOR_PICKER_DEFS]

    return render(request, "core/settings.html", {
        "grouped": grouped,
        "cv_status": cv_status,
        "api_calls_remaining": api_remaining,
        "api_calls_remaining_pct": round(api_remaining / CV_API_BUDGET_LIMIT * 100),
        "api_budget_limit": CV_API_BUDGET_LIMIT,
        "api_calls_per_path": get_api_calls_per_path(),
        "scrape_api_fallback": get_setting("scrape_api_fallback", False),
        "mood_swatches": MOOD_SWATCHES,
        "color_pickers": color_pickers,
    })


def settings_update(request):
    if request.method == "POST":
        # Unchecked checkboxes are absent from POST data, so reset all
        # bool settings to "false" first, then apply submitted values.
        Setting.objects.filter(type="bool").update(value="false")
        for key, value in request.POST.items():
            if key.startswith("csrf"):
                continue
            Setting.objects.filter(key=key).update(value=value)
        messages.success(request, "Settings saved.")
    return redirect("settings:index")


@require_POST
def update_preferences(request):
    prefs = UserPreference.get()
    allowed = {"nav", "mood", "table_density", "dashboard_pipeline"}
    for field in allowed:
        if field in request.POST:
            setattr(prefs, field, request.POST[field])
    prefs.show_covers = "show_covers" in request.POST
    prefs.high_contrast = "high_contrast" in request.POST
    prefs.oled = "oled" in request.POST

    if request.POST.get("clear_custom_colors"):
        prefs.custom_colors = {}
    else:
        custom = dict(prefs.custom_colors or {})
        for key in UserPreference.COLOR_VAR_MAP:
            if f"enable_color_{key}" in request.POST:
                val = request.POST.get(f"custom_color_{key}", "").strip()
                if val:
                    custom[key] = val
            else:
                custom.pop(key, None)
        prefs.custom_colors = custom

    prefs.save()
    return HttpResponse(status=204)


def settings_log(request):
    """Display the batch audit log, newest first, with optional action filter."""
    from .audit import AUDIT_ACTIONS, recent_log_entries

    action_filter = request.GET.get("action", "")

    # Newest entries first; the action filter searches the whole log
    entries, total = recent_log_entries(action_filter)

    paginator = Paginator(entries, 50)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(request, "core/settings_log.html", {
        "page_obj": page_obj,
        "total_count": total,
        "shown_count": paginator.count,
        "action_filter": action_filter,
        "actions": AUDIT_ACTIONS,
    })


@require_POST
def settings_dashboard(request):
    """HTMX endpoint: save dashboard display preferences, return updated section partial."""
    from .models import UserPreference
    from django.shortcuts import render

    prefs = UserPreference.get()
    prefs.dashboard_hero_style       = request.POST.get("dashboard_hero_style",      prefs.dashboard_hero_style)
    prefs.dashboard_attention_style  = request.POST.get("dashboard_attention_style", prefs.dashboard_attention_style)
    prefs.dashboard_show_weekly_card     = "dashboard_show_weekly_card"     in request.POST
    prefs.dashboard_show_priority_banner = "dashboard_show_priority_banner" in request.POST
    prefs.save()

    return render(request, "core/_settings_dashboard_section.html", {"prefs": prefs})


def _find_corrupt_task_results(limit=2000):
    """Return TaskResult rows whose stored result can no longer be decoded.

    Only exception-state rows can fail to decode (celery only converts the
    stored result back into an exception for those statuses), so we scope the
    scan to them. A row counts as corrupt when reading its state/result raises,
    e.g. a stored exception payload missing 'exc_type'. Polling such a task
    500s the progress endpoint, and the user has no other way to clear it.
    """
    from celery.result import AsyncResult
    from django_celery_results.models import TaskResult

    corrupt = []
    rows = (
        TaskResult.objects
        .filter(status__in=["FAILURE", "RETRY", "REVOKED"])
        .order_by("-date_done")[:limit]
    )
    for t in rows:
        try:
            res = AsyncResult(t.task_id)
            _ = res.state
            _ = res.result
        except Exception:
            corrupt.append(t)
    return corrupt


def task_health_check(request):
    from django_celery_results.models import TaskResult
    stuck = list(
        TaskResult.objects.exclude(status__in=["SUCCESS", "FAILURE", "REVOKED"])
        .order_by("-date_done")
    )
    return render(request, "core/_settings_tasks_section.html", {
        "stuck_tasks": stuck,
        "corrupt_tasks": _find_corrupt_task_results(),
        "checked": True,
        "just_cleared": False,
        "cleared_count": 0,
    })


@require_POST
def task_health_clear(request):
    from django_celery_results.models import TaskResult
    from .task_base import request_cancel
    stuck = TaskResult.objects.exclude(status__in=["SUCCESS", "FAILURE", "REVOKED"])
    count = stuck.count()
    for t in stuck:
        request_cancel(t.task_id)
    stuck.update(status="FAILURE")
    return render(request, "core/_settings_tasks_section.html", {
        "stuck_tasks": [],
        "corrupt_tasks": _find_corrupt_task_results(),
        "checked": True,
        "just_cleared": True,
        "cleared_count": count,
    })


@require_POST
def task_health_clear_corrupt(request):
    """Delete task result rows whose stored payload can no longer be decoded."""
    from django_celery_results.models import TaskResult
    corrupt = _find_corrupt_task_results()
    task_ids = [t.task_id for t in corrupt]
    count = len(task_ids)
    if task_ids:
        TaskResult.objects.filter(task_id__in=task_ids).delete()
    return render(request, "core/_settings_tasks_section.html", {
        "stuck_tasks": list(
            TaskResult.objects.exclude(status__in=["SUCCESS", "FAILURE", "REVOKED"])
            .order_by("-date_done")
        ),
        "corrupt_tasks": [],
        "checked": True,
        "just_cleared": True,
        "cleared_count": count,
    })
