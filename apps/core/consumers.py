from channels.generic.websocket import AsyncJsonWebsocketConsumer

_GROUP = "tasks"


class TaskConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add(_GROUP, self.channel_name)
        await self.accept()
        snapshot = await _get_snapshot()
        await self.send_json({"type": "queue.snapshot", "tasks": snapshot})

    async def disconnect(self, code):
        await self.channel_layer.group_discard(_GROUP, self.channel_name)

    async def task_event(self, event):
        # Per-task PROGRESS / SUCCESS / FAILURE updates (progress bars).
        await self.send_json(event["payload"])

    async def queue_event(self, event):
        # Queue snapshot updates (running + queued list).
        await self.send_json(event["payload"])


async def _get_snapshot():
    from asgiref.sync import sync_to_async
    from apps.core.task_queue import queue_snapshot

    return await sync_to_async(queue_snapshot)()
