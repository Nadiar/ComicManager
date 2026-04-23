def active_tasks(request):
    """Inject active background task IDs into template context."""
    return {
        "active_write_task_id": request.session.get("write_task_id", ""),
        "active_audit_task_id": request.session.get("audit_task_id", ""),
        "active_reorganize_task_id": request.session.get("reorganize_task_id", ""),
        "active_smartlist_action_task_id": request.session.get("smartlist_action_task_id", ""),
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
