from django.test import TestCase

from apps.core.models import QueuedTask


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
