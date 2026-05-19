"""
Audit log utilities for batch pipeline actions.

Writes JSON Lines entries to AUDIT_LOG_PATH for every scrape/tag/format
batch operation so users can review what changed and roll back if needed.
"""

import json
import os
from datetime import datetime, timezone

from django.conf import settings


def _log_path():
    return getattr(settings, "AUDIT_LOG_PATH", "/app/logs/batch_actions.jsonl")


# Canonical audit action names. The keys map workflow concepts to the strings
# used in the on-disk JSONL log. Keep these stable: existing log entries are
# read by apps/core/settings_views.py:settings_log and a rename would orphan
# old entries.
AUDIT_ACTION_ACCEPT = "accept"
AUDIT_ACTION_SCRAPE = "scrape_all"
AUDIT_ACTION_TAG = "tag_all"
AUDIT_ACTION_FORMAT = "format_all"
AUDIT_ACTION_ORGANIZE = "organize_all"
AUDIT_ACTION_WRITE = "write_all"

# Per-action error variants (used for permission/IO failures inside batch tasks).
AUDIT_ACTION_ORGANIZE_ERROR = "organize_error"
AUDIT_ACTION_WRITE_ERROR = "write_error"

# Non-workflow actions (file conversions, dedupe, page-delete, audits).
AUDIT_ACTION_CONVERT_CBR = "convert_cbr"
AUDIT_ACTION_CONVERT_ZIP = "convert_zip"
AUDIT_ACTION_DELETE_PAGES = "delete_pages"
AUDIT_ACTION_DEDUPLICATE = "deduplicate_all"
AUDIT_ACTION_AUDIT_METADATA = "audit_metadata"

# Display order for the settings log filter dropdown.
AUDIT_ACTIONS = [
    AUDIT_ACTION_ACCEPT,
    AUDIT_ACTION_SCRAPE,
    AUDIT_ACTION_TAG,
    AUDIT_ACTION_FORMAT,
    AUDIT_ACTION_DEDUPLICATE,
    AUDIT_ACTION_ORGANIZE,
    AUDIT_ACTION_ORGANIZE_ERROR,
    AUDIT_ACTION_WRITE,
    AUDIT_ACTION_WRITE_ERROR,
    AUDIT_ACTION_CONVERT_CBR,
    AUDIT_ACTION_CONVERT_ZIP,
    AUDIT_ACTION_DELETE_PAGES,
    AUDIT_ACTION_AUDIT_METADATA,
]


def log_batch_entry(action: str, comic, state_before: str, state_after: str, changes: dict):
    """Append one JSON line to the batch audit log.

    Args:
        action: Identifies the batch operation (e.g. "scrape_all", "tag_all", "format_all").
        comic: The Comic model instance that was processed.
        state_before: Comic state before the operation.
        state_after: Comic state after the operation.
        changes: Dict mapping field name to [before_value, after_value].
                 Only include fields where before != after.
    """
    if not changes:
        return

    series_display = comic.series or comic.proposed_series or "?"
    number_display = comic.number or comic.proposed_number or "?"

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "uuid": str(comic.pk),
        "name": f"{series_display} #{number_display}",
        "state_before": state_before,
        "state_after": state_after,
        "changes": changes,
    }

    path = _log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")



def snapshot_fields(comic, fields: list) -> dict:
    """Capture current values of the named comic attributes for later diffing."""
    return {f: getattr(comic, f) for f in fields}


def diff_fields(comic, snapshot: dict) -> dict:
    """Return a {field: [old, new]} dict for attributes whose value changed since `snapshot` was taken."""
    return {
        f: [old, getattr(comic, f)]
        for f, old in snapshot.items()
        if getattr(comic, f) != old
    }
