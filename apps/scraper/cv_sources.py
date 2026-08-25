"""
ComicVine data source availability and API budget tracking.

Provides helpers to detect which local data sources are available
(comicvine.db SQLite index, latest.mcl issue list) and to track
the ComicVine API call budget (200 calls/hour limit).
"""

import csv
import logging
import os
import sqlite3

from django.core.cache import cache

logger = logging.getLogger(__name__)

# API budget constants
CV_API_BUDGET_KEY = "cv_api_call_count"
CV_API_BUDGET_LIMIT = 200
CV_API_BUDGET_WINDOW = 3600  # 1 hour in seconds

# Per-path budget keys (ComicVine enforces 200/hour per path independently)
CV_API_PATH_KEYS = {
    "search":  "cv_api_calls_search",
    "volume":  "cv_api_calls_volume",
    "issue":   "cv_api_calls_issue",
    "issues":  "cv_api_calls_issues",
}

# Parsed MCL index, kept in process memory and reloaded when the file changes.
# It is too large to round-trip through the shared Redis cache on every call.
_mcl_memo = {"stamp": None, "index": {}}


# ---------------------------------------------------------------------------
# Source availability
# ---------------------------------------------------------------------------

def _get_cv_db_path():
    from apps.core.models import get_setting
    from django.conf import settings as django_settings
    return get_setting(
        "cv_db_path",
        getattr(django_settings, "CV_DB_PATH", "/cv_db/comicvine.db"),
    )


def _get_mcl_path():
    from apps.core.models import get_setting
    return get_setting("cv_mcl_path", "/cv_db/latest.mcl")


def fetch_cv_volume_counts(volume_ids) -> dict:
    """Return {volume_id: count_of_issues} from the local ComicVine DB.

    Queries in chunks of 500 to stay under SQLite's IN-clause limit. Volumes
    with a NULL count or no matching row are omitted. Returns {} (and logs)
    when the DB is unavailable, so callers treat "no count" uniformly instead
    of each re-implementing the same chunked query and swallowing errors.
    """
    ids = [int(v) for v in volume_ids if v not in (None, "")]
    if not ids:
        return {}

    counts: dict[int, int] = {}
    try:
        conn = sqlite3.connect(f"file:{_get_cv_db_path()}?immutable=1", uri=True)
        try:
            cursor = conn.cursor()
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                placeholders = ",".join("?" * len(chunk))
                cursor.execute(
                    f"SELECT id, count_of_issues FROM cv_volume WHERE id IN ({placeholders})",
                    chunk,
                )
                for vid, count in cursor.fetchall():
                    if count is not None:
                        counts[vid] = count
        finally:
            conn.close()
    except Exception:
        logger.exception("fetch_cv_volume_counts: CV DB query failed")
        return {}

    return counts


def is_cv_db_available() -> bool:
    """Return True if comicvine.db exists and SQLite can open it."""
    db_path = _get_cv_db_path()
    if not os.path.exists(db_path):
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)
        conn.execute("SELECT 1 FROM cv_volume LIMIT 1")
        conn.close()
        return True
    except Exception:
        return False


def is_mcl_available() -> bool:
    """Return True if latest.mcl exists and is readable."""
    mcl_path = _get_mcl_path()
    return os.path.isfile(mcl_path) and os.access(mcl_path, os.R_OK)


def get_cv_source_status() -> dict:
    """
    Return the availability status of all CV data sources.

    Returns dict:
    {
        "db": bool,           -- comicvine.db is present and readable
        "mcl": bool,          -- latest.mcl is present and readable
        "mcl_count": int,     -- number of volumes in MCL (0 if unavailable)
        "api_key": bool,      -- CV API key is configured
        "mode": str,          -- "full_db" | "mcl_only" | "api_only" | "none"
    }
    """
    from apps.core.models import get_setting

    db = is_cv_db_available()
    mcl = is_mcl_available()
    api_key = bool(get_setting("cv_api_key", "").strip())

    mcl_count = 0
    if mcl:
        index = load_mcl_index()
        mcl_count = len(index)

    if db:
        mode = "full_db"
    elif mcl:
        mode = "mcl_only"
    elif api_key:
        mode = "api_only"
    else:
        mode = "none"

    return {
        "db": db,
        "mcl": mcl,
        "mcl_count": mcl_count,
        "api_key": api_key,
        "mode": mode,
    }


# ---------------------------------------------------------------------------
# MCL (latest.mcl) index
# ---------------------------------------------------------------------------

def load_mcl_index(force_reload: bool = False) -> dict[str, list[dict]]:
    """
    Parse latest.mcl into a dict keyed by volume_id string.

    The MCL file is a semicolon-delimited file with one row per volume:
        volume_id; comma_separated_issue_ids; comma_separated_issue_numbers

    Example:
        7205;51379,75503,75504;24,1,2

    Issue IDs and numbers are paired by position:
        51379 -> number "24", 75503 -> number "1", 75504 -> number "2"

    Header rows (first field non-numeric) are skipped automatically.

    Returns:
        { "7205": [{"issue_id": "51379", "number": "24"}, ...], ... }

    The result is kept in memory until the file's size or modification time
    changes. Pass force_reload=True to re-read it anyway.
    """
    mcl_path = _get_mcl_path()
    index: dict[str, list[dict]] = {}

    if not is_mcl_available():
        return index

    st = os.stat(mcl_path)
    stamp = (mcl_path, st.st_mtime_ns, st.st_size)
    if not force_reload and _mcl_memo["stamp"] == stamp:
        return _mcl_memo["index"]

    try:
        with open(mcl_path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh, delimiter=";")
            for row in reader:
                if len(row) < 3:
                    continue
                volume_raw = row[0].strip()

                # Skip header rows (first column is non-numeric)
                if not volume_raw.isdigit():
                    continue

                issue_ids = [x.strip() for x in row[1].split(",") if x.strip()]
                numbers = [x.strip() for x in row[2].split(",") if x.strip()]

                # Pair by position; stop at the shorter list
                index[volume_raw] = [
                    {"issue_id": iid, "number": num}
                    for iid, num in zip(issue_ids, numbers)
                ]
    except Exception as exc:
        logger.warning("Failed to parse latest.mcl: %s", exc)
        return {}

    _mcl_memo["stamp"] = stamp
    _mcl_memo["index"] = index
    logger.info("Loaded MCL index: %d volumes", len(index))
    return index


def get_volume_completion_from_mcl(cv_volume_id: str) -> dict | None:
    """
    Build volume completion data using the MCL index.

    Returns a dict in the same shape as dashboard.services.get_volume_completion(),
    but without image URLs (MCL only contains IDs and numbers).
    Returns None if the volume is not in the MCL index.
    """
    from apps.core.models import Comic

    index = load_mcl_index()
    volume_id_str = str(cv_volume_id)

    issues_in_mcl = index.get(volume_id_str)
    if not issues_in_mcl:
        return None

    # Sort by issue number (numeric where possible)
    def _sort_key(entry):
        try:
            return (0, float(entry["number"]))
        except (ValueError, TypeError):
            return (1, entry["number"])

    issues_in_mcl = sorted(issues_in_mcl, key=_sort_key)

    # Build the full issue list (no cover URLs available from MCL)
    all_issues = [
        {
            "issue_id": int(e["issue_id"]) if e["issue_id"].isdigit() else e["issue_id"],
            "issue_number": e["number"],
            "title": None,
            "cover_date": None,
            "image_url": None,
            "cover_url": None,
            "site_detail_url": f"https://comicvine.gamespot.com/issue/4000-{e['issue_id']}/" if e["issue_id"].isdigit() else None,
        }
        for e in issues_in_mcl
    ]
    issue_id_set = {
        int(e["issue_id"]) for e in issues_in_mcl if e["issue_id"].isdigit()
    }

    # Get owned comics from the Django DB that match this volume
    owned_comics = Comic.objects.filter(
        custom_values__comicvine_volume=volume_id_str
    ).values("pk", "number", "series", "custom_values")

    owned_cv_issue_ids: dict[int, str] = {}
    for comic in owned_comics:
        cv_issue_id = (comic["custom_values"] or {}).get("comicvine_issue")
        if cv_issue_id and str(cv_issue_id).isdigit():
            owned_cv_issue_ids[int(cv_issue_id)] = comic["pk"]

    owned_issues = []
    missing_issues = []
    for issue in all_issues:
        issue_id = issue["issue_id"]
        if isinstance(issue_id, int) and issue_id in owned_cv_issue_ids:
            issue["comic_pk"] = owned_cv_issue_ids[issue_id]
            owned_issues.append(issue)
        else:
            missing_issues.append(issue)

    total = len(all_issues)
    owned_count = len(owned_issues)

    return {
        "volume_id": cv_volume_id,
        "volume_info": {
            "name": f"Volume {cv_volume_id}",
            "start_year": None,
            "count_of_issues": total,
            "publisher": None,
        },
        "all_issues": all_issues,
        "owned_issues": owned_issues,
        "missing_issues": missing_issues,
        "owned_cv_ids": owned_cv_issue_ids,
        "total_count": total,
        "owned_count": owned_count,
        "missing_count": total - owned_count,
        "completion": round((owned_count / total * 100), 1) if total > 0 else 0,
        "source": "mcl",
    }


# ---------------------------------------------------------------------------
# API call budget tracker
# ---------------------------------------------------------------------------

def _cache_incr(key: int, n: int = 1) -> int:
    """Increment a Redis counter, creating it with a 1-hour TTL if missing."""
    try:
        return cache.incr(key, delta=n)
    except ValueError:
        cache.set(key, n, CV_API_BUDGET_WINDOW)
        return n


def increment_api_call_count(n: int = 1, path: str = "") -> int:
    """
    Increment the rolling API call counter by n and return the new total.

    path: the endpoint prefix ("search", "volume", "issue") used to also
    update the per-path counter. Pass "" to skip per-path tracking.
    """
    new_value = _cache_incr(CV_API_BUDGET_KEY, n)
    if path and path in CV_API_PATH_KEYS:
        _cache_incr(CV_API_PATH_KEYS[path], n)
    return new_value


def get_api_calls_used() -> int:
    """Return the number of API calls made in the current rolling window."""
    return cache.get(CV_API_BUDGET_KEY, 0)


def get_api_calls_per_path() -> dict:
    """Return per-path call counts for search, volume, and issue."""
    keys = list(CV_API_PATH_KEYS.values())
    cached = cache.get_many(keys)
    return {path: cached.get(key, 0) for path, key in CV_API_PATH_KEYS.items()}


def get_api_calls_remaining() -> int:
    """Return remaining API call budget for the current window."""
    return max(0, CV_API_BUDGET_LIMIT - get_api_calls_used())


def check_api_budget(required: int = 1) -> bool:
    """Return True if at least `required` calls remain in the budget."""
    return get_api_calls_remaining() >= required
