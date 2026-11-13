"""Library scan: finds comic files in the library folder that have no record.

All archives are generated in a temp folder by apps.core.sample_data.
"""

import os
import shutil
import tempfile
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.core.models import Comic, QueuedTask, Setting
from apps.core.sample_data import make_cbz, make_rar
from apps.core.services import scan_library_folder

TAGGED = (
    "<ComicInfo><Series>Sample Hero</Series><Number>1</Number>"
    "<Volume>2020</Volume><Publisher>Sample Press</Publisher></ComicInfo>"
)


class LibraryScanTests(TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.library = os.path.join(self.tmp, "library")
        self.untagged = os.path.join(self.library, "unsorted")
        os.makedirs(self.untagged)

    def lib(self, *parts):
        return os.path.join(self.library, *parts)

    def scan(self, untagged=None):
        return scan_library_folder(path=self.library, untagged_path=untagged or self.untagged)

    def test_tagged_cbz_is_imported_as_finished(self):
        path = make_cbz(self.lib("Sample Press", "Sample Hero (2020)", "Sample Hero 001.cbz"), comicinfo=TAGGED)
        result = self.scan()
        self.assertEqual(result["imported_tagged"], 1)
        comic = Comic.objects.get(file_path=path)
        self.assertEqual(comic.state, Comic.STATE_WRITTEN)
        self.assertEqual((comic.series, comic.number, comic.publisher), ("Sample Hero", "1", "Sample Press"))
        self.assertEqual(comic.file_format, "cbz")

    def test_untagged_files_are_imported_as_new(self):
        bare = make_cbz(self.lib("Sample Press", "Sample Hero (2020)", "Sample Hero (2020) 002.cbz"))
        rar = make_rar(self.lib("Sample Press", "Sample Hero (2020)", "Sample Hero (2020) 003.cbr"))
        result = self.scan()
        self.assertEqual(result["imported_new"], 2)
        for path in (bare, rar):
            comic = Comic.objects.get(file_path=path)
            self.assertEqual(comic.state, Comic.STATE_NEW)
            self.assertEqual(comic.proposed_series, "Sample Hero")
        self.assertEqual(Comic.objects.get(file_path=rar).file_format, "cbr")

    def test_rescan_adds_nothing(self):
        make_cbz(self.lib("Sample Press", "Sample Hero 001.cbz"), comicinfo=TAGGED)
        make_cbz(self.lib("Sample Press", "Sample Hero 002.cbz"))
        self.scan()
        result = self.scan()
        self.assertEqual((result["imported_tagged"], result["imported_new"]), (0, 0))
        self.assertEqual(result["skipped"], 2)
        self.assertEqual(Comic.objects.count(), 2)

    def test_untagged_folder_inside_library_is_left_to_the_untagged_scan(self):
        # The untagged folder is reached through a symlink, so its records use
        # the symlink path, not the path under the library
        link = os.path.join(self.tmp, "untagged")
        os.symlink(self.untagged, link)
        make_cbz(os.path.join(self.untagged, "Sample Hero 004.cbz"))
        Comic.objects.create(file_path=os.path.join(link, "Sample Hero 004.cbz"), file_format="cbz")
        make_cbz(os.path.join(self.untagged, "Sample Hero 005.cbz"))
        result = self.scan(untagged=link)
        self.assertEqual((result["imported_tagged"], result["imported_new"]), (0, 0))
        self.assertEqual(Comic.objects.count(), 1)

    def test_missing_files_are_left_alone(self):
        gone = Comic.objects.create(file_path=self.lib("Sample Press", "Sample Hero 006.cbz"),
                                    file_format="cbz", state=Comic.STATE_NEW)
        self.scan()
        gone.refresh_from_db()
        self.assertFalse(gone.has_flag("file_missing"))

    def test_hidden_files_and_folders_are_skipped(self):
        make_cbz(self.lib("Sample Press", "._Sample Hero 007.cbz"))
        make_cbz(self.lib(".trash", "Sample Hero 008.cbz"))
        result = self.scan()
        self.assertEqual((result["imported_tagged"], result["imported_new"]), (0, 0))

    def test_task_scans_the_library_folder(self):
        from apps.core.tasks import scan_library_task
        make_cbz(self.lib("Sample Press", "Sample Hero 001.cbz"), comicinfo=TAGGED)
        with self.settings(LIBRARY_DIR=self.library, UNTAGGED_DIR=self.untagged):
            result = scan_library_task.apply().get()
        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["imported_tagged"], 1)


@mock.patch("apps.core.task_queue.enqueue")
class ScheduledLibraryScanTests(TestCase):

    def set_interval(self, hours):
        Setting.objects.update_or_create(
            key="library_scan_interval_hours",
            defaults={"value": str(hours), "label": "Library scan interval (hours)",
                      "type": Setting.TYPE_INT, "group": Setting.GROUP_LIBRARY},
        )

    def tick(self):
        from apps.core.tasks import scheduled_library_scan_task
        return scheduled_library_scan_task.apply().get()

    def test_off_by_default(self, enqueue):
        Setting.objects.filter(key="library_scan_interval_hours").delete()
        self.tick()
        enqueue.assert_not_called()

    def test_zero_means_off(self, enqueue):
        self.set_interval(0)
        self.tick()
        enqueue.assert_not_called()

    def test_first_run_enqueues_a_scan(self, enqueue):
        self.set_interval(6)
        self.tick()
        enqueue.assert_called_once()
        self.assertEqual(enqueue.call_args.args[0], "scan_library")

    def test_waits_for_the_interval(self, enqueue):
        self.set_interval(6)
        recent = QueuedTask.objects.create(action="scan_library", state=QueuedTask.STATE_DONE)
        QueuedTask.objects.filter(pk=recent.pk).update(created_at=timezone.now() - timedelta(hours=2))
        self.tick()
        enqueue.assert_not_called()

        QueuedTask.objects.filter(pk=recent.pk).update(created_at=timezone.now() - timedelta(hours=7))
        self.tick()
        enqueue.assert_called_once()

    def test_skips_while_a_scan_is_queued_or_running(self, enqueue):
        self.set_interval(1)
        old = QueuedTask.objects.create(action="scan_library", state=QueuedTask.STATE_RUNNING)
        QueuedTask.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(hours=5))
        self.tick()
        enqueue.assert_not_called()


class ImportFileTests(TestCase):
    """POST /comics/import-file/: another application (a downloader) adds
    one file it saved in the library, without a full library scan."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.library = os.path.join(self.tmp, "library")
        self.untagged = os.path.join(self.tmp, "untagged")
        os.makedirs(self.untagged)
        self.enterContext(self.settings(LIBRARY_DIR=self.library, UNTAGGED_DIR=self.untagged))

    def post(self, path):
        return self.client.post("/comics/import-file/", {"path": path})

    def test_imports_a_library_file_as_new_even_when_tagged(self):
        path = make_cbz(os.path.join(self.library, "Sample Press", "Sample Hero 001.cbz"), comicinfo=TAGGED)
        response = self.post(path)
        self.assertEqual(response.status_code, 200)
        comic = Comic.objects.get(file_path=path)
        self.assertEqual(response.json(), {"success": True, "comic_id": str(comic.pk), "created": True})
        self.assertEqual(comic.state, Comic.STATE_NEW)
        self.assertEqual(comic.proposed_series, "Sample Hero")

    def test_imports_a_file_in_the_untagged_folder(self):
        path = make_cbz(os.path.join(self.untagged, "Sample Hero 002.cbz"))
        self.assertEqual(self.post(path).status_code, 200)
        self.assertTrue(Comic.objects.filter(file_path=path).exists())

    def test_a_known_file_returns_its_comic(self):
        path = make_cbz(os.path.join(self.library, "Sample Hero 003.cbz"))
        known = Comic.objects.create(file_path=path, file_format="cbz", state=Comic.STATE_DONE)
        response = self.post(path)
        self.assertEqual(response.json(), {"success": True, "comic_id": str(known.pk), "created": False})
        self.assertEqual(Comic.objects.count(), 1)

    def test_refuses_paths_outside_the_comic_folders(self):
        outside = make_cbz(os.path.join(self.tmp, "elsewhere", "Sample Hero 004.cbz"))
        sneaky = os.path.join(self.library, "..", "elsewhere", "Sample Hero 004.cbz")
        for path in (outside, sneaky):
            self.assertEqual(self.post(path).status_code, 400, path)
        self.assertFalse(Comic.objects.exists())

    def test_refuses_missing_files_and_other_types(self):
        os.makedirs(self.library)
        notes = os.path.join(self.library, "notes.txt")
        with open(notes, "w") as f:
            f.write("x")
        for path in (os.path.join(self.library, "Sample Hero 005.cbz"), notes, ""):
            self.assertEqual(self.post(path).status_code, 400, path)
        self.assertFalse(Comic.objects.exists())
