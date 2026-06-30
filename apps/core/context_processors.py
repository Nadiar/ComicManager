def active_tasks(request):
    """Inject the active background task into template context.

    All dispatchers now lock on a single `active_task_id` (one batch at a time),
    so the global toast only needs that one id and its label. Pages that show
    per-button state (e.g. the organizer audit page) pass their own task ids
    through their view context.
    """
    return {
        "active_task_id": request.session.get("active_task_id", ""),
        "active_task_label": request.session.get("active_task_label", ""),
    }


def user_preferences(request):
    """Inject display preferences into every template as `prefs`."""
    from .models import UserPreference
    return {"prefs": UserPreference.get()}


def scraper_settings(request):
    """Inject Inducks/scraper settings into every template."""
    from .models import get_setting
    return {
        "inducks_enabled": get_setting("inducks_enabled", False),
        "inducks_country_lock": get_setting("inducks_country_lock", ""),
        "inducks_country_codes": [
            c.strip()
            for c in get_setting("inducks_country_codes", "dk,de,nl,se,no,fi,us,it,fr,br").split(",")
            if c.strip()
        ],
    }


def nav_settings(request):
    """Inject navigation visibility settings into every template."""
    from .models import get_setting
    return {
        "show_au_scan": get_setting("show_au_scan", True),
    }
