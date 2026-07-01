from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.core.models import QueuedTask
from apps.core import task_queue


class QueuedTaskModelTests(TestCase):
    def test_defaults_and_ordering(self):
        a = QueuedTask.objects.create(action="tag_all", label="Tagging")
        b = QueuedTask.objects.create(action="write_all", label="Writing")
        self.assertEqual(a.state, QueuedTask.STATE_QUEUED)
        self.assertEqual(a.args, {})
        self.assertEqual(a.celery_task_id, "")
        # created_at ordering is FIFO
        self.assertEqual(list(QueuedTask.objects.all()), [a, b])
        self.assertEqual(
            QueuedTask.ACTIVE_STATES,
            (QueuedTask.STATE_QUEUED, QueuedTask.STATE_RUNNING),
        )


class EnqueueTests(TestCase):
    def test_enqueue_creates_row_and_dispatches(self):
        fake_task = MagicMock()
        fake_task.apply_async.return_value = MagicMock(id="celery-123")
        with patch.object(task_queue, "_registry", return_value={"tag_all": fake_task}), \
             patch.object(task_queue, "broadcast_queue") as bq:
            qt = task_queue.enqueue("tag_all", args=[], label="Tagging 5")
        self.assertEqual(qt.state, QueuedTask.STATE_QUEUED)
        self.assertEqual(qt.celery_task_id, "celery-123")
        self.assertEqual(qt.label, "Tagging 5")
        fake_task.apply_async.assert_called_once_with(args=[], queue="serial")
        bq.assert_called_once()
