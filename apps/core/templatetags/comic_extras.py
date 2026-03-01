from django import template
from django.utils.safestring import mark_safe
from apps.core.utils import COLUMNS_REGISTRY

register = template.Library()

@register.filter
def get_col_value(comic, col_id):
    """
    Dynamically retrieve a value from a Comic instance based on column registry.
    Supports nested attributes (e.g. custom_values.comicvine_issue).
    """
    col_cfg = COLUMNS_REGISTRY.get(col_id)
    if not col_cfg:
        return ""
    
    attr_path = col_cfg.get("attr")
    if not attr_path:
        return ""
    
    # Handle nested lookups (e.g. custom_values.some_key)
    parts = attr_path.split('.')
    val = comic
    for part in parts:
        if isinstance(val, dict):
            val = val.get(part, "")
        else:
            val = getattr(val, part, "")
        
        if val is None:
            return ""
            
    # Format specific types
    if col_id == "file_size" and val:
        try:
            val = f"{int(val) / (1024*1024):.1f} MB"
        except (ValueError, TypeError):
            pass
    elif col_id in ["updated", "imported"] and val:
        val = val.strftime("%Y-%m-%d")
    elif col_id == "last_written" and val:
        val = val.strftime("%Y-%m-%d %H:%M:%S")
        
    return val

@register.filter
def get_col_label(col_id):
    return COLUMNS_REGISTRY.get(col_id, {}).get("label", col_id)

@register.filter
def get_col_sort(col_id):
    return COLUMNS_REGISTRY.get(col_id, {}).get("sort", col_id)
