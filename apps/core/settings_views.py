import json

from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.http import require_POST
from .models import Setting, UserPreference


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

    return render(request, "core/settings.html", {
        "grouped": grouped,
        "cv_status": cv_status,
        "api_calls_remaining": api_remaining,
        "api_calls_remaining_pct": round(api_remaining / CV_API_BUDGET_LIMIT * 100),
        "api_budget_limit": CV_API_BUDGET_LIMIT,
        "api_calls_per_path": get_api_calls_per_path(),
        "scrape_api_fallback": get_setting("scrape_api_fallback", False),
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
    prefs.save()
    return HttpResponse(status=204)


def settings_log(request):
    """Display the batch audit log, newest first, with optional action filter."""
    from django.conf import settings as django_settings

    log_path = getattr(django_settings, "AUDIT_LOG_PATH", "/app/logs/batch_actions.jsonl")
    action_filter = request.GET.get("action", "")

    entries = []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # Take last 2000 lines to avoid loading huge files
        lines = lines[-2000:]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if action_filter and entry.get("action") != action_filter:
                    continue
                entries.append(entry)
            except (json.JSONDecodeError, ValueError):
                continue
    except FileNotFoundError:
        entries = []

    # Newest first
    entries.reverse()

    paginator = Paginator(entries, 50)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(request, "core/settings_log.html", {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "action_filter": action_filter,
        "actions": ["scrape_all", "tag_all", "format_all", "deduplicate_all", "organize_all", "write_all", "audit_metadata", "convert_zip", "organize_error", "write_error"],
    })
