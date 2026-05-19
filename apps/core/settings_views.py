import json

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

    from .audit import AUDIT_ACTIONS

    return render(request, "core/settings_log.html", {
        "page_obj": page_obj,
        "total_count": paginator.count,
        "action_filter": action_filter,
        "actions": AUDIT_ACTIONS,
    })
