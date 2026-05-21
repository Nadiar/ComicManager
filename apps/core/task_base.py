from celery import Task
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

_GROUP = "tasks"


# =============================================================================
# Cancel helpers (Redis-backed, cross-process)
# =============================================================================

def _cancel_client():
    import redis as _redis
    from django.conf import settings
    url = getattr(settings, "CELERY_BROKER_URL", "redis://redis:6379/0")
    base = url.rsplit("/", 1)[0]
    return _redis.from_url(f"{base}/1", decode_responses=True)


def request_cancel(task_id):
    """Signal a task to cancel cooperatively."""
    _cancel_client().setex(f"cancel:{task_id}", 7200, "1")


def is_cancelled(task_id):
    """Return True if a cancel has been requested for this task."""
    return bool(_cancel_client().get(f"cancel:{task_id}"))


def clear_cancel(task_id):
    """Remove the cancel flag."""
    _cancel_client().delete(f"cancel:{task_id}")


def _broadcast(task_id, payload):
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            _GROUP,
            {"type": "task.event", "payload": payload},
        )
    except Exception:
        pass


class ProgressTask(Task):
    """
    Base task class that auto-broadcasts every update_state(PROGRESS) call
    via WebSocket, plus SUCCESS/FAILURE on completion.
    """
    abstract = True

    def update_state(self, task_id=None, state=None, meta=None, **kwargs):
        super().update_state(task_id=task_id, state=state, meta=meta, **kwargs)
        if state == "PROGRESS" and isinstance(meta, dict):
            actual_id = task_id or self.request.id
            name = self.name.rsplit(".", 1)[-1]
            payload = {"task_id": actual_id, "state": "PROGRESS", **meta}
            payload.setdefault("name", name)
            payload.setdefault("label", name.replace("_task", "").replace("_all", "").replace("_", " ").title())
            current = meta.get("current", 0)
            total = meta.get("total", 0)
            if total > 0:
                payload["pct"] = int(100 * current / max(total, 1))
            _broadcast(actual_id, payload)

    def update_progress(self, current, total, *, label=None, sublabel=None, **extra):
        pct = int(100 * current / max(total, 1))
        name = self.name.rsplit(".", 1)[-1]
        lbl = label or name.replace("_task", "").replace("_all", "").replace("_", " ").title()
        meta = {
            "task_id": self.request.id,
            "name": name,
            "label": lbl,
            "sublabel": sublabel or f"{current} of {total}",
            "pct": pct,
            "current": current,
            "total": total,
            **extra,
        }
        self.update_state(state="PROGRESS", meta=meta)

    def on_success(self, retval, task_id, args, kwargs):
        payload = {
            "task_id": task_id,
            "state": "SUCCESS",
            "pct": 100,
            "result": retval if isinstance(retval, dict) else {},
        }
        _broadcast(task_id, payload)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        payload = {
            "task_id": task_id,
            "state": "FAILURE",
            "error": str(exc),
        }
        _broadcast(task_id, payload)

    def is_cancelled(self):
        return is_cancelled(self.request.id)

    def clear_cancel(self):
        clear_cancel(self.request.id)

    def is_paused(self):
        from django.core.cache import cache
        return bool(cache.get(f"task:pause:{self.request.id}"))



def batch_workflow_run(
    task,
    comic_ids,
    *,
    process,
    count_label="processed",
    is_fatal=None,
    extra_meta=None,
):
    """Run `process(comic)` over `comic_ids` with the standard cancellation,
    progress-update, and error-accumulation pattern shared by every batch task.

    `task` is the bound Celery `self`. `process` returns an `ActionResult`
    (success path increments the counter; non-skipped failure adds to errors).

    Optional `is_fatal(action_result) -> bool` short-circuits the loop and
    returns `stopped_early=True`. Used by organize_all to bail on permission
    or out-of-space errors.

    `extra_meta` is a dict merged into every progress meta payload — useful
    for static fields like `api_mode` that don't change mid-loop.

    Returns:
        {count_label: <count>, "total": <total>, "errors": [...],
         "cancelled": <bool>, "stopped_early": <bool, only when is_fatal fired>}
    """
    from .models import Comic

    comic_ids = list(comic_ids)
    total = len(comic_ids)
    extra_meta = extra_meta or {}

    if total == 0:
        return {count_label: 0, "total": 0, "errors": [], "cancelled": False}

    count = 0
    errors = []

    task.update_state(
        state="PROGRESS",
        meta={"current": 0, "total": total, count_label: 0, "errors": [], **extra_meta},
    )

    for i, comic_id in enumerate(comic_ids):
        if task.is_cancelled():
            task.clear_cancel()
            return {count_label: count, "total": total, "errors": errors, "cancelled": True}

        try:
            comic = Comic.objects.get(pk=comic_id)
        except Comic.DoesNotExist:
            continue

        result = process(comic)
        if result.success:
            count += 1
        elif not result.skipped:
            errors.append(f"{comic.series or '?'} #{comic.number or '?'}: {result.message}")

        task.update_state(
            state="PROGRESS",
            meta={
                "current": i + 1,
                "total": total,
                count_label: count,
                "errors": errors,
                **extra_meta,
            },
        )

        if is_fatal and not result.success and is_fatal(result):
            return {
                count_label: count, "total": total, "errors": errors,
                "cancelled": False, "stopped_early": True,
            }

    return {count_label: count, "total": total, "errors": errors, "cancelled": False}
