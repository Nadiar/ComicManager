import json as _json

from django import template

register = template.Library()


@register.filter
def max_val(lst):
    """Return max of a list, 1 if empty/all-zero (avoids div-by-zero)."""
    return max(lst, default=0) or 1


@register.filter
def bar_height(value, maximum):
    """Return bar height as a percentage string (min 2 so bars are always visible)."""
    if not maximum:
        return 2
    pct = round((value / maximum) * 100)
    return max(pct, 2)


@register.filter
def week_bar_class(index, total):
    """Return True if this bar index is in the current week (last 7 of 14)."""
    return index >= total - 7


@register.filter(is_safe=True)
def json_counts(pipeline):
    """Serialize pipeline counts as a JSON array for the flow-node JS."""
    return _json.dumps([s.get("count", 0) for s in pipeline])
