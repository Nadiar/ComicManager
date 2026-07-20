"""Durable, serial task queue: enqueue helper, action registry, lifecycle
signals, snapshot + broadcast. Execution is Celery; these helpers only manage
the QueuedTask ledger and the cross-device UI feed."""

from __future__ import annotations

from django.utils import timezone
from celery.signals import task_prerun, task_postrun, task_failure


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
    # Pre-generate the Celery task id and persist it on the row BEFORE dispatch.
    # If we dispatched first and saved the id afterwards, a fast task on an idle
    # worker could fire task_prerun (which looks the row up by celery_task_id)
    # before the id was saved, so the "running" snapshot never broadcast and the
    # client never set activeTaskId, leaving the trigger button stuck on
    # "Running...". Creating the row with the id first closes that race.
    import uuid

    task_id = str(uuid.uuid4())
    qt = QueuedTask.objects.create(
        action=action, args=args, label=label or action, celery_task_id=task_id
    )
    _registry()[action].apply_async(args=args, queue=lane, task_id=task_id)
    broadcast_queue()
    return qt


def _update_by_celery_id(celery_task_id, **fields):
    from apps.core.models import QueuedTask

    qt = QueuedTask.objects.filter(celery_task_id=celery_task_id).first()
    if qt is None:
        return None
    for k, v in fields.items():
        setattr(qt, k, v)
    qt.save(update_fields=list(fields.keys()))
    broadcast_queue()
    return qt


def _on_prerun(task_id=None, **kw):
    if not task_id:
        return
    _update_by_celery_id(task_id, state="running", started_at=timezone.now())


def _on_postrun(task_id=None, retval=None, state=None, **kw):
    from apps.core.models import QueuedTask

    if not task_id or state != "SUCCESS":
        return
    qt = QueuedTask.objects.filter(celery_task_id=task_id).first()
    if qt is None or qt.state in (QueuedTask.STATE_FAILED, QueuedTask.STATE_CANCELLED):
        return
    summary = retval if isinstance(retval, dict) else None
    _update_by_celery_id(
        task_id, state="done", finished_at=timezone.now(), result_summary=summary
    )


def _on_failure(task_id=None, exception=None, **kw):
    if not task_id:
        return
    _update_by_celery_id(
        task_id, state="failed", finished_at=timezone.now(), error=str(exception)
    )


task_prerun.connect(_on_prerun, weak=False)
task_postrun.connect(_on_postrun, weak=False)
task_failure.connect(_on_failure, weak=False)


def _serialize(qt):
    return {
        "id": str(qt.id),
        "action": qt.action,
        "label": qt.label,
        "state": qt.state,
        "celery_task_id": qt.celery_task_id,
        "created_at": qt.created_at.isoformat() if qt.created_at else None,
    }


def queue_snapshot():
    """Active (queued + running) rows in FIFO order, serialized for the UI."""
    from apps.core.models import QueuedTask

    rows = QueuedTask.objects.filter(state__in=QueuedTask.ACTIVE_STATES).order_by("created_at")
    return [_serialize(r) for r in rows]


def broadcast_queue():
    """Push the current queue snapshot to every connected client."""
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync

    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            "tasks",
            {"type": "queue.event", "payload": {"type": "queue.snapshot", "tasks": queue_snapshot()}},
        )
    except Exception:
        pass


def _active_celery_ids():
    """Celery task ids the workers currently know about (active + reserved)."""
    from comicmanager.celery import app as celery_app

    insp = celery_app.control.inspect()
    ids = set()
    for group in (insp.active() or {}, insp.reserved() or {}):
        for tasks in group.values():
            for t in tasks:
                tid = t.get("id")
                if tid:
                    ids.add(tid)
    return ids


def reconcile_orphans():
    """Mark `running` rows whose Celery task is no longer active as failed.

    Handles the case where a worker was killed mid-task and left a row stuck in
    `running`. Returns the number of rows reconciled."""
    from apps.core.models import QueuedTask

    running = list(QueuedTask.objects.filter(state=QueuedTask.STATE_RUNNING))
    if not running:
        return 0
    active = _active_celery_ids()
    n = 0
    for qt in running:
        if qt.celery_task_id not in active:
            qt.state = QueuedTask.STATE_FAILED
            qt.error = "Worker stopped before the task finished"
            qt.finished_at = timezone.now()
            qt.save(update_fields=["state", "error", "finished_at"])
            n += 1
    if n:
        broadcast_queue()
    return n
