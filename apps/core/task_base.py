from celery import Task
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

_GROUP = "tasks"


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

    def is_paused(self):
        from django.core.cache import cache
        return bool(cache.get(f"task:pause:{self.request.id}"))
