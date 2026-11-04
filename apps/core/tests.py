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

    def _toast_cancel(self, celery_task_id):
        with patch("apps.core.views._revoke_celery") as rev, \
             patch("apps.core.tasks.request_cancel") as flag, \
             patch("apps.core.task_queue.broadcast_queue"):
            resp = self.client.post(reverse("core:cancel_task", args=[celery_task_id]))
        self.assertEqual(resp.status_code, 200)
        return rev, flag

    def test_toast_cancel_cancels_a_task_that_has_not_started(self):
        qt = QueuedTask.objects.create(action="convert_all_cbr", label="A",
                                       celery_task_id="cid-1", state=QueuedTask.STATE_QUEUED)
        rev, flag = self._toast_cancel("cid-1")
        qt.refresh_from_db()
        self.assertEqual(qt.state, QueuedTask.STATE_CANCELLED)
        rev.assert_called_once_with("cid-1")
        flag.assert_not_called()

    def test_toast_cancel_stops_a_running_task_cooperatively(self):
        qt = QueuedTask.objects.create(action="convert_all_cbr", label="A",
                                       celery_task_id="cid-2", state=QueuedTask.STATE_RUNNING)
        rev, flag = self._toast_cancel("cid-2")
        qt.refresh_from_db()
        self.assertEqual(qt.state, QueuedTask.STATE_CANCELLED)
        flag.assert_called_once_with("cid-2")

    def test_toast_cancel_without_a_queue_entry_only_sets_the_flag(self):
        rev, flag = self._toast_cancel("cid-3")
        flag.assert_called_once_with("cid-3")
        rev.assert_not_called()

    def test_single_convert_stops_when_cancelled(self):
        from apps.core.models import Comic
        from apps.core.tasks import convert_cbr_task
        comic = Comic.objects.create(proposed_series="Sample", proposed_number="1", file_path="/x/a.cbr")
        with patch("apps.core.task_base.is_cancelled", return_value=True), \
             patch("apps.core.task_base.clear_cancel"), \
             patch("apps.core.tasks._convert_comic_to_cbz") as convert:
            result = convert_cbr_task.apply(args=[str(comic.pk)]).result
        convert.assert_not_called()
        self.assertTrue(result["cancelled"])


class CancelledAfterRestartTests(TestCase):
    """A task cancelled while queued stays cancelled when Redis delivers it again after a restart (#6)."""

    def _flagged(self, path):
        from apps.core.models import Comic
        return Comic.objects.create(proposed_series="Sample", proposed_number="1", file_path=path,
                                    flags={"needs_conversion": True})

    def _run(self, celery_task_id):
        from apps.core.tasks import convert_all_cbr_task
        with patch("apps.core.tasks._convert_comic_to_cbz",
                   return_value={"success": True, "skipped": False, "error": None, "fatal": False}) as convert, \
             patch("apps.core.task_queue.broadcast_queue"):
            result = convert_all_cbr_task.apply(task_id=celery_task_id).result
        return result, convert

    def test_cancelled_task_is_skipped_and_stays_cancelled(self):
        self._flagged("/x/a.cbr")
        qt = QueuedTask.objects.create(action="convert_all_cbr", label="A",
                                       celery_task_id="cid-c", state=QueuedTask.STATE_CANCELLED)
        result, convert = self._run("cid-c")
        convert.assert_not_called()
        self.assertEqual(result, {"cancelled": True, "skipped": True})
        qt.refresh_from_db()
        self.assertEqual(qt.state, QueuedTask.STATE_CANCELLED)

    def test_queued_task_still_runs(self):
        self._flagged("/x/a.cbr")
        qt = QueuedTask.objects.create(action="convert_all_cbr", label="A",
                                       celery_task_id="cid-q", state=QueuedTask.STATE_QUEUED)
        result, convert = self._run("cid-q")
        convert.assert_called_once()
        self.assertEqual(result["converted"], 1)
        qt.refresh_from_db()
        self.assertEqual(qt.state, QueuedTask.STATE_DONE)

    def test_worker_start_fails_rows_left_running_and_removes_half_converted_files(self):
        import os
        import shutil
        import tempfile
        from apps.core.task_queue import _on_worker_ready
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        temp_dir = os.path.join(tmp, "temp")
        os.makedirs(os.path.join(temp_dir, "cm-convert-abc", "out"))
        os.makedirs(os.path.join(temp_dir, "unrelated"))
        self._flagged(os.path.join(tmp, "Sample 001.cbr"))
        leftover = os.path.join(tmp, ".cm-convert-Sample 001.tmp")
        other = os.path.join(tmp, ".cm-convert-Other 002.tmp")
        for path in (leftover, other):
            open(path, "w").close()
        running = QueuedTask.objects.create(action="convert_all_cbr", label="A",
                                            celery_task_id="cid-r", state=QueuedTask.STATE_RUNNING)
        queued = QueuedTask.objects.create(action="tag_all", label="B",
                                           celery_task_id="cid-w", state=QueuedTask.STATE_QUEUED)
        with patch("apps.core.task_queue.broadcast_queue"), \
             patch("tempfile.gettempdir", return_value=temp_dir):
            _on_worker_ready()
        running.refresh_from_db()
        queued.refresh_from_db()
        self.assertEqual(running.state, QueuedTask.STATE_FAILED)
        self.assertEqual(queued.state, QueuedTask.STATE_QUEUED)
        self.assertFalse(os.path.exists(leftover))
        self.assertTrue(os.path.exists(other))
        self.assertEqual(os.listdir(temp_dir), ["unrelated"])


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


class TaskHealthQueueTests(TestCase):
    """Task Health lists tasks still in the queue, which have no result row yet (#6)."""

    def setUp(self):
        self.waiting = QueuedTask.objects.create(action="convert_all_cbr", label="Converting files",
                                                 celery_task_id="cid-1", state=QueuedTask.STATE_QUEUED)
        QueuedTask.objects.create(action="tag_all", label="Finished tagging",
                                  celery_task_id="cid-2", state=QueuedTask.STATE_DONE)

    def test_check_lists_unfinished_queue_entries(self):
        html = self.client.get(reverse("settings:task_health_check")).content.decode()
        self.assertIn("Converting files", html)
        self.assertNotIn("Finished tagging", html)
        self.assertIn("Force stop all", html)

    def test_check_with_an_empty_queue(self):
        self.waiting.delete()
        html = self.client.get(reverse("settings:task_health_check")).content.decode()
        self.assertIn("Queue is empty", html)
        self.assertNotIn("Force stop all", html)

    def test_force_stop_cancels_queue_entries(self):
        with patch("apps.core.views._revoke_celery") as rev, \
             patch("apps.core.tasks.request_cancel"), \
             patch("apps.core.task_queue.broadcast_queue"):
            html = self.client.post(reverse("settings:task_health_clear")).content.decode()
        self.waiting.refresh_from_db()
        self.assertEqual(self.waiting.state, QueuedTask.STATE_CANCELLED)
        rev.assert_called_once_with("cid-1")
        self.assertIn("Cleared 1 task", html)


class DefaultQueueTests(TestCase):
    """Tasks sent without a queue go to one the worker consumes (BUG.71)."""

    def test_tasks_without_a_queue_go_to_serial(self):
        from comicmanager.celery import app
        self.assertEqual(app.conf.task_default_queue, "serial")
        route = app.amqp.router.route({}, "celery.backend_cleanup")
        self.assertEqual(route["queue"].name, "serial")


class SearchTests(TestCase):
    """The free-text search on the comic list covers the Imprint (UI.36)."""

    def test_search_finds_imprint(self):
        from django.http import QueryDict
        from apps.core.models import Comic
        from apps.core.views import _build_comic_list_queryset
        Comic.objects.create(series="Sandman", number="1", publisher="DC Comics", imprint="Vertigo", state="tagging")
        Comic.objects.create(series="Batman", number="1", publisher="DC Comics", state="tagging")
        found = _build_comic_list_queryset(QueryDict("q=vertigo")).values_list("series", flat=True)
        self.assertEqual(list(found), ["Sandman"])


class ComicListRailQueryTests(TestCase):
    """The comic list's filter rail counts every flag in one query, and HTMX requests skip it (#18)."""

    def setUp(self):
        from apps.core.models import Comic
        Comic.objects.create(series="A", state="tagging", flags={"is_pdf": True, "needs_conversion": True})
        Comic.objects.create(series="B", state="tagging", flags={"is_pdf": True})

    def _get(self, **headers):
        from django.db import connection
        from django.test import Client
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            response = Client().get("/comics/", **headers)
        flag_queries = [q["sql"] for q in ctx.captured_queries if '"flags" ->' in q["sql"]]
        return response, flag_queries

    def test_full_page_counts_flags_in_one_query(self):
        response, flag_queries = self._get()
        counts = {f["key"]: f["count"] for f in response.context["flag_counts"]}
        self.assertEqual(counts, {"is_pdf": 2, "needs_conversion": 1})
        self.assertEqual(response.context["needs_conversion_count"], 1)
        self.assertEqual(response.context["is_zip_count"], 0)
        # was a count and an exists() for each of the 17 flags
        self.assertEqual(len(flag_queries), 1, flag_queries)

    def test_htmx_request_skips_the_rail(self):
        response, flag_queries = self._get(HTTP_HX_REQUEST="true")
        self.assertNotIn("flag_counts", response.context)
        self.assertEqual(flag_queries, [])


class NumberParamTests(TestCase):
    """Text in a number parameter is ignored instead of giving a server error (AC.12)."""

    def test_int_param(self):
        from apps.core.utils import int_param
        self.assertEqual(int_param({"n": "12"}, "n", 5), 12)
        self.assertEqual(int_param({"n": "abc"}, "n", 5), 5)
        self.assertEqual(int_param({}, "n", 5), 5)

    def test_pages_ignore_text_in_number_params(self):
        from django.test import Client
        from apps.dashboard.models import SmartList
        smartlist = SmartList.objects.create(name="All")
        client = Client()
        for url in ("/comics/?per_page=abc", f"/smartlists/{smartlist.pk}/?per_page=abc",
                    "/scraper/dry-run/?limit=abc&max_distance=x"):
            self.assertEqual(client.get(url).status_code, 200, url)


class InlineProposedYearTests(TestCase):
    """Proposed Year is editable in place in the New list, like the other proposed values, and saved as a number."""

    def setUp(self):
        from apps.core.models import Comic
        self.comic = Comic.objects.create(proposed_series="Saga", proposed_number="40", state="new")
        self.url = f"/comics/{self.comic.pk}/inline-field/"

    def _post(self, value):
        from django.test import Client
        Client().post(self.url, {"field": "proposed_year", "value": value})
        self.comic.refresh_from_db()
        return self.comic.proposed_year

    def test_year_saves_as_a_number(self):
        self.assertEqual(self._post("2016"), 2016)
        self.assertIsNone(self._post(""))
        self.assertIsNone(self._post("20x6"))

    def test_the_new_list_and_the_input_offer_it(self):
        from django.test import Client
        client = Client()
        self.assertIn("field=proposed_year", client.get("/comics/?state=new").content.decode())
        form = client.get(self.url + "?field=proposed_year").content.decode()
        self.assertIn('type="number"', form)
