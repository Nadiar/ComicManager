"""
Dashboard helper functions: greeting, bottleneck derivation, 14-day throughput, since-visit counts.
"""

from datetime import timedelta

from django.utils import timezone
from django.db.models import Count
from django.db.models.functions import TruncDate


# ── Greeting ─────────────────────────────────────────────────────────────────

def get_greeting():
    h = timezone.localtime().hour
    if h < 5:
        return "Late night"
    if h < 12:
        return "Good morning"
    if h < 17:
        return "Good afternoon"
    if h < 22:
        return "Good evening"
    return "Late night"


# ── Bottleneck ────────────────────────────────────────────────────────────────

def get_bottleneck(pipeline):
    """Return the first pipeline stage dict with count > 0 that is not 'done'."""
    return next(
        (s for s in pipeline if s["count"] > 0 and s["state"] != "done"),
        None,
    )


# ── 14-day throughput ─────────────────────────────────────────────────────────

def get_week_history():
    """Return a list of 14 ints — daily count of comics written to CBZ over the last 14 days."""
    from apps.core.models import Comic

    today = timezone.now().date()
    start = today - timedelta(days=13)

    by_day = dict(
        Comic.objects.filter(
            last_written__isnull=False,
            last_written__date__gte=start,
        )
        .annotate(written_day=TruncDate("last_written"))
        .values("written_day")
        .annotate(c=Count("id"))
        .values_list("written_day", "c")
    )

    return [by_day.get(today - timedelta(days=13 - i), 0) for i in range(14)]


# ── Series tone (consistent color per series name) ────────────────────────────

_TONES = ["red", "blue", "purple", "green", "amber", "cyan", "neutral"]

def series_tone(name: str) -> str:
    """Return a deterministic tone name for a series title (for cover placeholders)."""
    h = 0
    for ch in (name or ""):
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return _TONES[h % len(_TONES)]
