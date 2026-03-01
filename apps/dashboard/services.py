import sqlite3
from django.conf import settings
from django.db.models import BooleanField, Case, F, Value, When
from apps.core.models import Comic
from apps.core.utils import natural_number_annotation


# Whitelist of allowed Comic model fields for filtering
ALLOWED_FIELDS = {
    "series", "title", "number", "volume", "year", "month",
    "publisher", "format", "medium", "state", "genre",
    "series_group", "main_character_or_team", "characters",
    "writer", "penciller", "inker", "colorist", "letterer",
    "cover_artist", "editor", "page_count", "count",
    "is_duplicate", "file_format", "file_path", "summary", "notes",
    # Proposed fields (filename-parsed, populated for STATE_NEW)
    "proposed_series", "proposed_number", "proposed_volume", "proposed_year",
    # Workflow tracking
    "needs_reorganize", "needs_reformat", "last_written", "imported_at", "updated_at",
    # Computed annotations
    "is_stale",
}

# Also allow JSONField nested lookups
ALLOWED_JSON_PREFIXES = {"custom_values", "flags"}

# Whitelist of allowed Django ORM lookups
ALLOWED_LOOKUPS = {
    "exact", "iexact", "icontains", "contains",
    "gt", "gte", "lt", "lte",
    "isnull",
    "not_exact", "not_icontains", "not_isnull",
}

# Sort field mapping (reuse pattern from comic_list view)
SORT_FIELDS = {
    "series": ["series", "volume", "number_sort_key", "number"],
    "number": ["number_sort_key", "number"],
    "publisher": ["publisher", "series", "volume", "number_sort_key", "number"],
    "year": ["year", "series", "volume", "number_sort_key", "number"],
    "state": ["state", "series", "volume", "number_sort_key", "number"],
    "format": ["format", "series", "volume", "number_sort_key", "number"],
    "pages": ["page_count", "series", "volume", "number_sort_key", "number"],
    "updated": ["updated_at"],
    "count": ["count", "series", "volume", "number_sort_key", "number"],
    "imported": ["imported_at"],
    "last_written": ["last_written"],
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

    # Annotate is_stale: True when written before but DB has since changed
    qs = qs.annotate(
        is_stale=Case(
            When(last_written__isnull=False, updated_at__gt=F("last_written"), then=Value(True)),
            default=Value(False),
            output_field=BooleanField(),
        )
    )

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

        # Handle negated lookups (not_exact → exclude with exact, etc.)
        negate = lookup.startswith("not_")
        if negate:
            lookup = lookup[4:]  # strip "not_" prefix

        # Coerce value
        value = _coerce_value(value, lookup, field)

        # Build ORM filter key
        if lookup == "exact":
            orm_key = field
        else:
            orm_key = f"{field}__{lookup}"

        if negate:
            qs = qs.exclude(**{orm_key: value})
        else:
            qs = qs.filter(**{orm_key: value})

    # Annotate for natural number sorting (1, 2, 10 instead of 1, 10, 2)
    qs = qs.annotate(number_sort_key=natural_number_annotation())

    # Apply sorting
    order_fields = SORT_FIELDS.get(smart_list.sort_field, ["series", "volume", "number_sort_key", "number"])
    if smart_list.sort_direction == "desc":
        order_fields = [f"-{f}" for f in order_fields]

    return qs.order_by(*order_fields)


def get_volume_completion(cv_volume_id):
    """
    Compare library holdings against a ComicVine volume to find missing issues.

    Takes a ComicVine volume ID directly.
    Returns dict with volume_info, owned_issues, missing_issues, completion stats.

    Data source precedence:
    1. comicvine.db SQLite index (full metadata + cover URLs)
    2. latest.mcl CSV index (issue IDs and numbers only, no covers)
    3. Neither available: returns {"unavailable": True, "reason": "..."}
    """
    from apps.scraper.cv_sources import is_cv_db_available, is_mcl_available, get_volume_completion_from_mcl

    if not is_cv_db_available():
        if is_mcl_available():
            return get_volume_completion_from_mcl(cv_volume_id)
        return {
            "unavailable": True,
            "reason": "No local ComicVine data source available (comicvine.db or latest.mcl).",
        }

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
        SELECT id, issue_number, name, cover_date, image_url, site_detail_url
        FROM cv_issue
        WHERE volume_id = ?
        ORDER BY
            CASE WHEN issue_number GLOB '[0-9]*'
                 THEN CAST(issue_number AS INTEGER)
                 ELSE 999999 END,
            issue_number
    """, (cv_volume_id,))

    all_issues = []
    issue_ids = []
    for row in cursor.fetchall():
        all_issues.append({
            "issue_id": row[0],
            "issue_number": row[1],
            "title": row[2],
            "cover_date": row[3],
            "image_url": row[4],
            "site_detail_url": row[5],
        })
        issue_ids.append(row[0])

    # Batch fetch best cover URL per issue from comic_covers table
    cover_by_issue = {}
    if issue_ids:
        placeholders = ",".join("?" * len(issue_ids))
        cursor.execute(f"""
            SELECT cvid, cv_url FROM comic_covers
            WHERE cvid IN ({placeholders}) AND cv_url IS NOT NULL
            ORDER BY
                CASE WHEN cv_url LIKE '%/0/4/%' THEN 0 ELSE 1 END,
                id ASC
        """, issue_ids)
        for row in cursor.fetchall():
            # Keep only the first (best) cover per issue
            if row[0] not in cover_by_issue:
                cover_by_issue[row[0]] = row[1]

    conn.close()

    # Set cover_url on each issue (prefer comic_covers, fallback to image_url)
    for issue in all_issues:
        issue["cover_url"] = cover_by_issue.get(issue["issue_id"]) or issue.get("image_url")

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
        "volume_id": cv_volume_id,
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


def get_missing_issues(smart_list):
    """
    Compare library holdings against a ComicVine volume to find missing issues.

    Thin wrapper around get_volume_completion() that reads the volume ID
    from a smart list object.
    Returns None if no CV volume is linked.
    """
    if not smart_list.comicvine_volume_id:
        return None
    return get_volume_completion(smart_list.comicvine_volume_id)


def search_cv_volumes(query, limit=20):
    """
    Search ComicVine volumes by name. Returns list of dicts.
    Used by the HTMX search endpoint in the smart list form.

    Returns empty list when comicvine.db is unavailable (MCL does not contain
    volume names, so text search is not possible without the DB).
    """
    from apps.scraper.cv_sources import is_cv_db_available

    if not query or len(query) < 2:
        return []

    if not is_cv_db_available():
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
