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
