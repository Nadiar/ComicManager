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
