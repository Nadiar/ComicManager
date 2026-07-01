"""Durable, serial task queue: enqueue helper, action registry, lifecycle
signals, snapshot + broadcast. Execution is Celery; these helpers only manage
the QueuedTask ledger and the cross-device UI feed."""

from __future__ import annotations


_REGISTRY = None


def _registry():
    """action key -> Celery task object. Built lazily on first use so importing
    this module does not pull in every task module (avoids import cycles)."""
    global _REGISTRY
    if _REGISTRY is None:
        from apps.core import tasks as c
        from apps.dashboard import tasks as d
        from apps.organizer import tasks as o
        _REGISTRY = {
            # core batch tasks
            "scrape_all": c.scrape_all_task,
            "tag_all": c.tag_all_task,
            "retag_flagged": c.retag_flagged_task,
            "format_all": c.format_all_task,
            "organize_all": c.organize_all_task,
            "deduplicate_all": c.deduplicate_all_task,
            "populate_counts": c.populate_counts_task,
            "detect_format_upgrades": c.detect_format_upgrades_task,
            "scan_untagged": c.scan_untagged_task,
            "audit_metadata": c.audit_metadata_task,
            "convert_cbr": c.convert_cbr_task,
            "convert_all_cbr": c.convert_all_cbr_task,
            "convert_all_zip": c.convert_all_zip_task,
            "write_all": c.write_all_comics_task,
            "write_stale": c.write_stale_comics_task,
            "write_missing": c.write_missing_comics_task,
            "rewrite_updated": c.rewrite_updated_comics_task,
            "bulk_action": c.bulk_action_task,
            "search_alt_covers": c.search_alt_covers_task,
            # dashboard
            "smartlist_action": d.run_smartlist_action_task,
            "run_pipeline": d.run_full_pipeline_task,
            # organizer
            "audit_paths": o.audit_paths_task,
            "scan_au": o.scan_au_paths_task,
            "reorganize_au": o.reorganize_au_flagged_task,
            "reorganize_all": o.reorganize_all_flagged_task,
        }
    return _REGISTRY


def enqueue(action: str, args=None, label: str = "", lane: str = "serial"):
    """Create a queued ledger row, dispatch the task to `lane`, return the row.

    `args` is a list of positional Celery args. `lane` is the Celery queue;
    it stays "serial" today, and exists as a parameter so a future parallel
    lane is a routing change rather than a refactor.
    """
    from apps.core.models import QueuedTask

    args = list(args or [])
    qt = QueuedTask.objects.create(action=action, args=args, label=label or action)
    result = _registry()[action].apply_async(args=args, queue=lane)
    qt.celery_task_id = result.id
    qt.save(update_fields=["celery_task_id"])
    broadcast_queue()
    return qt


def broadcast_queue():
    """Placeholder replaced in the snapshot task (T5). Defined here so enqueue
    and the signal handlers can call it now."""
    return None
