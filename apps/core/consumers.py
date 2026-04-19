import json
from channels.generic.websocket import AsyncJsonWebsocketConsumer

_GROUP = "tasks"


class TaskConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add(_GROUP, self.channel_name)
        await self.accept()
        snapshot = await _get_snapshot()
        await self.send_json({"type": "task.snapshot", "tasks": snapshot})

    async def disconnect(self, code):
        await self.channel_layer.group_discard(_GROUP, self.channel_name)

    async def task_event(self, event):
        await self.send_json(event["payload"])


async def _get_snapshot():
    from asgiref.sync import sync_to_async

    @sync_to_async
    def _query():
        try:
            from django_celery_results.models import TaskResult
            rows = TaskResult.objects.filter(status="PROGRESS").order_by("-date_done")[:5]
            tasks = []
            for r in rows:
                try:
                    meta = json.loads(r.result or "{}")
                except Exception:
                    meta = {}
                tasks.append({
                    "task_id": r.task_id,
                    "state": "PROGRESS",
                    "pct": meta.get("pct", 0),
                    "label": meta.get("label") or r.task_name or "Task",
                    "sublabel": meta.get("sublabel", ""),
                    "current": meta.get("current", 0),
                    "total": meta.get("total", 0),
                })
            return tasks
        except Exception:
            return []

    return await _query()
