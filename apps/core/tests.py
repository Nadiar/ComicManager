from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import reverse

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
        with patch.object(task_queue, "_registry", return_value={"tag_all": fake_task}), \
             patch.object(task_queue, "broadcast_queue") as bq:
            qt = task_queue.enqueue("tag_all", args=[], label="Tagging 5")
        self.assertEqual(qt.state, QueuedTask.STATE_QUEUED)
        self.assertTrue(qt.celery_task_id)
        self.assertEqual(qt.label, "Tagging 5")
        # The task is dispatched with the row's own id so the worker's
        # task_prerun lookup (by celery_task_id) always finds the row.
        _, kwargs = fake_task.apply_async.call_args
        self.assertEqual(kwargs["task_id"], qt.celery_task_id)
        self.assertEqual(kwargs["queue"], "serial")
        bq.assert_called_once()

    def test_row_persisted_with_celery_id_before_dispatch(self):
        """Regression: the QueuedTask row must be saved with its celery_task_id
        BEFORE the task is dispatched. Otherwise a fast task on an idle worker
        can fire task_prerun (which looks the row up by celery_task_id) before
        the id is saved, so the 'running' snapshot never broadcasts, the client
        never sets activeTaskId, and the trigger button stays stuck on
        'Running...'."""
        seen = {}
        fake_task = MagicMock()

        def _capture(*args, **kwargs):
            # Simulate the worker's task_prerun lookup racing in at dispatch time.
            seen["task_id_passed"] = kwargs.get("task_id")
            seen["row_has_id"] = QueuedTask.objects.exclude(celery_task_id="").exists()
            return MagicMock(id=kwargs.get("task_id"))

        fake_task.apply_async.side_effect = _capture
        with patch.object(task_queue, "_registry", return_value={"tag_all": fake_task}), \
             patch.object(task_queue, "broadcast_queue"):
            task_queue.enqueue("tag_all", args=[], label="Tagging")
        self.assertTrue(seen["task_id_passed"], "a task_id must be passed to apply_async")
        self.assertTrue(seen["row_has_id"], "row must be persisted with celery_task_id before dispatch")


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


class CancelQueuedTests(TestCase):
    def test_cancel_queued_marks_cancelled(self):
        qt = QueuedTask.objects.create(action="tag_all", label="A",
                                       celery_task_id="cid-9", state=QueuedTask.STATE_QUEUED)
        with patch("apps.core.views._revoke_celery") as rev, \
             patch("apps.core.task_queue.broadcast_queue"):
            resp = self.client.post(reverse("core:cancel_queued", args=[qt.id]))
        self.assertEqual(resp.status_code, 200)
        qt.refresh_from_db()
        self.assertEqual(qt.state, QueuedTask.STATE_CANCELLED)
        rev.assert_called_once_with("cid-9")


class DispatchEnqueueTests(TestCase):
    def test_tag_all_enqueues(self):
        qt = MagicMock()
        qt.id = "qt-1"
        qt.label = "Tagging comics"
        with patch("apps.core.views.enqueue", return_value=qt) as enq:
            resp = self.client.post(reverse("core:tag_all"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])
        enq.assert_called_once()
        self.assertEqual(enq.call_args.args[0], "tag_all")


class ModalIfNowTests(TestCase):
    def _comic(self):
        from apps.core.models import Comic
        return Comic.objects.create(series="S", number="1", state="tagging")

    def test_runs_sync_when_queue_empty(self):
        c = self._comic()
        with patch("apps.core.views._run_action_sync", return_value={"success": True}) as run, \
             patch("apps.core.views.enqueue") as enq:
            resp = self.client.post(reverse("core:comic_action"), {
                "pks": [str(c.pk)], "action": "tag", "show_result": "true"})
        run.assert_called_once()
        enq.assert_not_called()
        self.assertEqual(resp.json()["modal_type"], "tag")

    def test_enqueues_when_busy(self):
        c = self._comic()
        QueuedTask.objects.create(action="tag_all", label="busy", state=QueuedTask.STATE_RUNNING)
        with patch("apps.core.views._run_action_sync") as run, \
             patch("apps.core.views.enqueue", return_value=MagicMock(id="qt-2", label="Tagging")) as enq:
            resp = self.client.post(reverse("core:comic_action"), {
                "pks": [str(c.pk)], "action": "tag", "show_result": "true"})
        run.assert_not_called()
        enq.assert_called_once()
        self.assertTrue(resp.json()["queued"])


class ReconcileTests(TestCase):
    def test_orphaned_running_marked_failed(self):
        qt = QueuedTask.objects.create(action="tag_all", label="A",
                                       celery_task_id="dead", state=QueuedTask.STATE_RUNNING)
        with patch("apps.core.task_queue._active_celery_ids", return_value=set()), \
             patch("apps.core.task_queue.broadcast_queue"):
            n = task_queue.reconcile_orphans()
        qt.refresh_from_db()
        self.assertEqual(n, 1)
        self.assertEqual(qt.state, QueuedTask.STATE_FAILED)


class AdjacentIssuesTests(TestCase):
    """Previous/next issue for the comic page: same series + volume, nearest owned issue."""

    def _comic(self, number, series="Sample Hero", volume=1, **extra):
        from apps.core.models import Comic
        return Comic.objects.create(series=series, number=number, volume=volume, **extra)

    def _adjacent(self, comic):
        from apps.core.services import adjacent_issues
        return adjacent_issues(comic)

    def test_orders_numerically_including_decimals(self):
        one, one_half, two, ten = (self._comic(n) for n in ("1", "1.5", "2", "10"))
        self.assertEqual(self._adjacent(one_half), (one, two))
        self.assertEqual(self._adjacent(two), (one_half, ten))

    def test_skips_missing_issues_to_the_nearest_owned(self):
        three, seven = self._comic("3"), self._comic("7")
        self.assertEqual(self._adjacent(three), (None, seven))
        self.assertEqual(self._adjacent(seven), (three, None))

    def test_ignores_other_series_and_volumes(self):
        current = self._comic("5")
        self._comic("4", series="Another Hero")
        self._comic("6", volume=2)
        self.assertEqual(self._adjacent(current), (None, None))

    def test_series_match_is_case_insensitive(self):
        current = self._comic("2")
        prev = self._comic("1", series="SAMPLE HERO")
        self.assertEqual(self._adjacent(current)[0], prev)

    def test_other_copies_of_the_same_number_are_not_neighbours(self):
        current = self._comic("5")
        self._comic("5", file_path="/copy/sample-hero-5.cbz")
        nxt = self._comic("6")
        self.assertEqual(self._adjacent(current), (None, nxt))

    def test_non_numeric_numbers_sort_last(self):
        one, annual = self._comic("1"), self._comic("Annual")
        self.assertEqual(self._adjacent(one), (None, annual))
        self.assertEqual(self._adjacent(annual), (one, None))

    def test_comic_without_series_has_no_neighbours(self):
        from apps.core.models import Comic
        lone = Comic.objects.create(number="1")
        self.assertEqual(self._adjacent(lone), (None, None))


class ComicDetailNavigationTests(TestCase):
    """Comic page context: previous/next issue and breadcrumb links."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user("nav", password="pw")
        self.client.force_login(user)

    def _comic(self, number, **extra):
        from apps.core.models import Comic
        fields = {"series": "Sample & Co", "volume": 1, "publisher": "Sample Press", **extra}
        return Comic.objects.create(number=number, **fields)

    def _context(self, comic):
        resp = self.client.get(reverse("core:detail", args=[comic.pk]))
        self.assertEqual(resp.status_code, 200)
        return resp

    def test_context_has_previous_and_next_issue(self):
        first, current, last = self._comic("1"), self._comic("2"), self._comic("3")
        resp = self._context(current)
        self.assertEqual(resp.context["prev_issue"], first)
        self.assertEqual(resp.context["next_issue"], last)

    def test_breadcrumb_urls_are_encoded_list_filters(self):
        resp = self._context(self._comic("1"))
        self.assertEqual(resp.context["publisher_url"], "/comics/?publisher=Sample+Press")
        self.assertEqual(
            resp.context["series_url"],
            "/comics/?q=Sample+%26+Co+V1&publisher=Sample+Press",
        )

    def test_series_url_without_volume_or_publisher(self):
        resp = self._context(self._comic("1", volume=None, publisher=None))
        self.assertEqual(resp.context["publisher_url"], "")
        self.assertEqual(resp.context["series_url"], "/comics/?q=Sample+%26+Co")

    def test_no_series_means_no_series_url(self):
        resp = self._context(self._comic("1", series=None))
        self.assertEqual(resp.context["series_url"], "")

    def test_page_links_previous_and_next_issue(self):
        first, current, last = self._comic("1"), self._comic("2"), self._comic("3")
        html = self._context(current).content.decode()
        self.assertIn(f'href="{reverse("core:detail", args=[first.pk])}"', html)
        self.assertIn(f'href="{reverse("core:detail", args=[last.pk])}"', html)
        self.assertIn("Previous issue (#1)", html)
        self.assertIn("Next issue (#3)", html)

    def test_first_issue_has_previous_disabled(self):
        first, second = self._comic("1"), self._comic("2")
        html = self._context(first).content.decode()
        self.assertIn('aria-disabled="true" style="opacity:.4;">&lsaquo; Previous issue</span>', html)
        self.assertIn(f'href="{reverse("core:detail", args=[second.pk])}"', html)

    def test_no_buttons_without_other_issues(self):
        html = self._context(self._comic("1")).content.decode()
        self.assertNotIn("Previous issue", html)
        self.assertNotIn("Next issue", html)

    def test_breadcrumbs_are_ghost_button_links(self):
        html = self._context(self._comic("1")).content.decode()
        self.assertIn('href="/comics/?publisher=Sample+Press" class="cm-btn sm ghost"', html)
        self.assertIn('href="/comics/?q=Sample+%26+Co+V1&amp;publisher=Sample+Press" class="cm-btn sm ghost"', html)
