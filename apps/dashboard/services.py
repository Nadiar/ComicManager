import sqlite3
from django.conf import settings
from apps.core.models import Comic


# Whitelist of allowed Comic model fields for filtering
ALLOWED_FIELDS = {
    "series", "title", "number", "volume", "year", "month",
    "publisher", "format", "medium", "state", "genre",
    "series_group", "main_character_or_team", "characters",
    "writer", "penciller", "inker", "colorist", "letterer",
    "cover_artist", "editor", "page_count", "count",
    "is_duplicate", "file_format", "summary", "notes",
}

# Also allow JSONField nested lookups
ALLOWED_JSON_PREFIXES = {"custom_values", "flags"}

# Whitelist of allowed Django ORM lookups
ALLOWED_LOOKUPS = {
    "exact", "iexact", "icontains", "contains",
    "gt", "gte", "lt", "lte",
    "isnull",
}

# Sort field mapping (reuse pattern from comic_list view)
SORT_FIELDS = {
    "series": ["series", "volume", "number"],
    "number": ["number"],
    "publisher": ["publisher", "series", "volume", "number"],
    "year": ["year", "series", "volume", "number"],
    "state": ["state", "series", "volume", "number"],
    "format": ["format", "series", "volume", "number"],
    "pages": ["page_count", "series", "volume", "number"],
    "updated": ["updated_at"],
    "count": ["count", "series", "volume", "number"],
}


def _coerce_value(value, lookup, field=""):
    """Coerce filter value to the appropriate Python type."""
    if lookup == "isnull":
        return str(value).lower() in ("true", "1", "yes")

    # Skip int coercion for JSONField lookups — values are stored as strings
    is_json_field = field.split("__")[0] in ALLOWED_JSON_PREFIXES

    # Try int conversion for numeric lookups (but not JSON fields)
    if not is_json_field and lookup in ("gt", "gte", "lt", "lte", "exact"):
        try:
            return int(value)
        except (ValueError, TypeError):
            pass

    # Boolean
    if isinstance(value, str) and value.lower() in ("true", "false"):
        if lookup == "exact":
            return value.lower() == "true"

    return value


def build_queryset(smart_list):
    """
    Build a Comic queryset from SmartList filter criteria.

    Each filter is a dict with: field, lookup, value.
    Returns an ordered QuerySet.
    """
    qs = Comic.objects.all()

    for f in (smart_list.filters or []):
        field = f.get("field", "")
        lookup = f.get("lookup", "exact")
        value = f.get("value")

        # Validate field
        base_field = field.split("__")[0]
        if base_field not in ALLOWED_FIELDS and base_field not in ALLOWED_JSON_PREFIXES:
            continue

        # Validate lookup
        if lookup not in ALLOWED_LOOKUPS:
            continue

        # Coerce value
        value = _coerce_value(value, lookup, field)

        # Build ORM filter key
        if lookup == "exact":
            orm_key = field
        else:
            orm_key = f"{field}__{lookup}"

        qs = qs.filter(**{orm_key: value})

    # Apply sorting
    order_fields = SORT_FIELDS.get(smart_list.sort_field, ["series", "volume", "number"])
    if smart_list.sort_direction == "desc":
        order_fields = [f"-{f}" for f in order_fields]

    return qs.order_by(*order_fields)


def get_missing_issues(smart_list):
    """
    Compare library holdings against a ComicVine volume to find missing issues.

    Returns dict with volume_info, owned_issues, missing_issues, completion stats.
    Returns None if no CV volume is linked.
    """
    if not smart_list.comicvine_volume_id:
        return None

    cv_volume_id = smart_list.comicvine_volume_id

    # 1. Query CV SQLite DB for volume info and all issues
    db_path = getattr(settings, "CV_DB_PATH", "/cv_db/comicvine.db")
    try:
        conn = sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)
    except Exception:
        return None

    cursor = conn.cursor()

    cursor.execute("""
        SELECT v.name, v.start_year, v.count_of_issues, p.name as publisher
        FROM cv_volume v
        LEFT JOIN cv_publisher p ON v.publisher_id = p.id
        WHERE v.id = ?
    """, (cv_volume_id,))
    vol_row = cursor.fetchone()

    if not vol_row:
        conn.close()
        return None

    volume_info = {
        "name": vol_row[0],
        "start_year": vol_row[1],
        "count_of_issues": vol_row[2],
        "publisher": vol_row[3],
    }

    cursor.execute("""
        SELECT id, issue_number, name, cover_date
        FROM cv_issue
        WHERE volume_id = ?
        ORDER BY
            CASE WHEN issue_number GLOB '[0-9]*'
                 THEN CAST(issue_number AS INTEGER)
                 ELSE 999999 END,
            issue_number
    """, (cv_volume_id,))

    all_issues = []
    for row in cursor.fetchall():
        all_issues.append({
            "issue_id": row[0],
            "issue_number": row[1],
            "title": row[2],
            "cover_date": row[3],
        })

    conn.close()

    # 2. Get owned comics from PostgreSQL that match this CV volume
    owned_comics = Comic.objects.filter(
        custom_values__comicvine_volume=str(cv_volume_id)
    ).values("pk", "number", "series", "custom_values")

    # Build set of owned CV issue IDs
    owned_cv_issue_ids = {}
    for comic in owned_comics:
        cv_issue_id = comic["custom_values"].get("comicvine_issue")
        if cv_issue_id:
            owned_cv_issue_ids[int(cv_issue_id)] = comic["pk"]

    # 3. Split into owned vs missing
    owned_issues = []
    missing_issues = []
    for issue in all_issues:
        comic_pk = owned_cv_issue_ids.get(issue["issue_id"])
        if comic_pk:
            issue["comic_pk"] = comic_pk
            owned_issues.append(issue)
        else:
            missing_issues.append(issue)

    total = len(all_issues)
    owned_count = len(owned_issues)

    return {
        "volume_info": volume_info,
        "all_issues": all_issues,
        "owned_issues": owned_issues,
        "missing_issues": missing_issues,
        "owned_cv_ids": owned_cv_issue_ids,
        "total_count": total,
        "owned_count": owned_count,
        "missing_count": total - owned_count,
        "completion": round((owned_count / total * 100), 1) if total > 0 else 0,
    }


def search_cv_volumes(query, limit=20):
    """
    Search ComicVine volumes by name. Returns list of dicts.
    Used by the HTMX search endpoint in the smart list form.
    """
    if not query or len(query) < 2:
        return []

    db_path = getattr(settings, "CV_DB_PATH", "/cv_db/comicvine.db")
    try:
        conn = sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)
    except Exception:
        return []

    cursor = conn.cursor()
    cursor.execute("""
        SELECT v.id, v.name, v.start_year, v.count_of_issues, p.name as publisher
        FROM cv_volume v
        LEFT JOIN cv_publisher p ON v.publisher_id = p.id
        WHERE LOWER(v.name) LIKE LOWER(?)
        ORDER BY v.count_of_issues DESC
        LIMIT ?
    """, (f"%{query}%", limit))

    results = []
    for row in cursor.fetchall():
        results.append({
            "id": row[0],
            "name": row[1],
            "start_year": row[2],
            "count_of_issues": row[3],
            "publisher": row[4],
        })

    conn.close()
    return results
