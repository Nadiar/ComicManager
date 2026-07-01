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


class LifecycleSignalTests(TestCase):
    def _row(self):
        qt = QueuedTask.objects.create(action="tag_all", label="Tagging")
        qt.celery_task_id = "cid-1"
        qt.save(update_fields=["celery_task_id"])
        return qt

    def test_prerun_marks_running(self):
        qt = self._row()
        with patch.object(task_queue, "broadcast_queue"):
            task_queue._on_prerun(task_id="cid-1")
        qt.refresh_from_db()
        self.assertEqual(qt.state, QueuedTask.STATE_RUNNING)
        self.assertIsNotNone(qt.started_at)

    def test_postrun_success_marks_done_with_summary(self):
        qt = self._row()
        with patch.object(task_queue, "broadcast_queue"):
            task_queue._on_postrun(task_id="cid-1", retval={"written": 3}, state="SUCCESS")
        qt.refresh_from_db()
        self.assertEqual(qt.state, QueuedTask.STATE_DONE)
        self.assertEqual(qt.result_summary, {"written": 3})

    def test_postrun_non_success_is_ignored(self):
        qt = self._row()
        with patch.object(task_queue, "broadcast_queue"):
            task_queue._on_postrun(task_id="cid-1", retval=None, state="FAILURE")
        qt.refresh_from_db()
        self.assertEqual(qt.state, QueuedTask.STATE_QUEUED)

    def test_failure_marks_failed(self):
        qt = self._row()
        with patch.object(task_queue, "broadcast_queue"):
            task_queue._on_failure(task_id="cid-1", exception=ValueError("boom"))
        qt.refresh_from_db()
        self.assertEqual(qt.state, QueuedTask.STATE_FAILED)
        self.assertIn("boom", qt.error)


class SnapshotTests(TestCase):
    def test_snapshot_returns_active_in_order(self):
        a = QueuedTask.objects.create(action="tag_all", label="A", state=QueuedTask.STATE_RUNNING)
        b = QueuedTask.objects.create(action="write_all", label="B", state=QueuedTask.STATE_QUEUED)
        QueuedTask.objects.create(action="x", label="C", state=QueuedTask.STATE_DONE)
        snap = task_queue.queue_snapshot()
        self.assertEqual([r["label"] for r in snap], ["A", "B"])
        self.assertEqual(snap[0]["state"], "running")
