"""File-level tests: CBZ page edits, ComicInfo writes and the untagged scan.

All archives are generated in a temp folder by apps.core.sample_data.
"""

import json
import os
import shutil
import stat
import tempfile
import zipfile

from django.test import TestCase

from apps.core import cbz_utils
from apps.core.models import Comic
from apps.core.sample_data import make_cbz, make_rar, make_sample_library, page_colors
from apps.core.services import check_missing_files, scan_untagged_folder
from apps.core.utils import read_comicinfo_xml, restore_index_backup, write_comicinfo_xml


class TempDirMixin:
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)


class PageEditTests(TempDirMixin, TestCase):

    def test_delete_page_removes_the_chosen_page(self):
        p = make_cbz(self.path("a.cbz"), ["001.jpg", "002.jpg", "003.jpg"])
        self.assertTrue(cbz_utils.delete_pages(p, [1]))
        self.assertEqual(page_colors(p), [0, 2])

    def test_reorder_pages(self):
        p = make_cbz(self.path("a.cbz"), ["001.jpg", "002.jpg", "003.jpg"])
        self.assertTrue(cbz_utils.reorder_pages(p, [2, 0, 1]))
        self.assertEqual(page_colors(p), [2, 0, 1])

    def test_page_edit_keeps_comicinfo(self):
        p = make_cbz(self.path("a.cbz"), comicinfo="<ComicInfo><Series>Keep</Series></ComicInfo>")
        self.assertTrue(cbz_utils.delete_pages(p, [0]))
        self.assertEqual(read_comicinfo_xml(p).get("series"), "Keep")

    def test_dotfiles_are_not_pages(self):
        # macOS "._" resource forks must not shift page indexes
        p = make_cbz(self.path("a.cbz"), ["001.jpg", "002.jpg", "003.jpg"],
                     extra={"._001.jpg": b"junk", "sub/._002.jpg": b"junk"})
        self.assertEqual(cbz_utils.list_pages(zipfile.ZipFile(p).namelist()),
                         ["001.jpg", "002.jpg", "003.jpg"])
        self.assertTrue(cbz_utils.delete_pages(p, [1]))
        self.assertEqual(page_colors(p), [0, 2])
        self.assertIn("._001.jpg", zipfile.ZipFile(p).namelist())

    def test_pages_use_natural_order(self):
        names = [f"page{i}.jpg" for i in range(1, 12)]
        p = make_cbz(self.path("a.cbz"), names)
        self.assertEqual(cbz_utils.list_pages(zipfile.ZipFile(p).namelist()), names)
        self.assertTrue(cbz_utils.delete_pages(p, [10]))
        self.assertEqual(page_colors(p), list(range(10)))

    def test_edit_keeps_file_mode_and_leaves_no_temp_files(self):
        p = make_cbz(self.path("a.cbz"), mode=0o664)
        self.assertTrue(cbz_utils.reorder_pages(p, [1, 0, 2]))
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o664)
        self.assertEqual(os.listdir(self.tmp), ["a.cbz"])

    def test_failed_edit_leaves_original_untouched(self):
        p = make_cbz(self.path("a.cbz"))
        with open(p, "rb") as f:
            before = f.read()
        self.assertFalse(cbz_utils.reorder_pages(p, [0, 0, 1]))
        self.assertFalse(cbz_utils.save_page_layout(p, [{"type": "new", "key": "missing"}], {}))
        with open(p, "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(os.listdir(self.tmp), ["a.cbz"])

    def test_add_and_layout(self):
        from apps.core.sample_data import page_image, PAGE_COLORS
        p = make_cbz(self.path("a.cbz"))
        self.assertTrue(cbz_utils.add_page_from_upload(p, page_image(PAGE_COLORS[5]), 1))
        self.assertEqual(page_colors(p), [0, 5, 1, 2])
        layout = [{"type": "existing", "index": 3}, {"type": "new", "key": "f.jpg"}]
        self.assertTrue(cbz_utils.save_page_layout(p, layout, {"f.jpg": page_image(PAGE_COLORS[7])}))
        self.assertEqual(page_colors(p), [2, 7])

    def test_delete_all_pages_refused(self):
        p = make_cbz(self.path("a.cbz"), ["001.jpg", "002.jpg"])
        self.assertFalse(cbz_utils.delete_pages(p, [0, 1]))
        self.assertEqual(page_colors(p), [0, 1])


class PageManagerViewTests(TempDirMixin, TestCase):

    def test_delete_first_page_refreshes_count_and_cover_hash(self):
        from apps.scraper.hasher import extract_cover_hashes
        p = make_cbz(self.path("a.cbz"), ["001.jpg", "002.jpg", "003.jpg"], extra={"._001.jpg": b"junk"})
        hashes = extract_cover_hashes(p)
        comic = Comic.objects.create(file_path=p, file_format="cbz", page_count=3,
                                     phash=hashes.phash_hex, ahash=hashes.ahash_hex)
        listing = self.client.get(f"/comics/{comic.pk}/pages/").json()
        self.assertEqual(listing["page_count"], 3)
        resp = self.client.post(f"/comics/{comic.pk}/pages/delete/", json.dumps({"indices": [0]}),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["page_count"], 2)
        self.assertEqual(page_colors(p), [1, 2])
        comic.refresh_from_db()
        self.assertEqual(comic.page_count, 2)
        self.assertEqual(comic.phash, extract_cover_hashes(p).phash_hex)
        self.assertNotEqual(comic.phash, hashes.phash_hex)


class ComicInfoWriteTests(TempDirMixin, TestCase):

    def test_write_then_read_back(self):
        p = make_cbz(self.path("a.cbz"))
        comic = Comic.objects.create(file_path=p, series="Sample Hero", number="1", publisher="Pub")
        self.assertTrue(write_comicinfo_xml(p, comic))
        self.assertEqual(read_comicinfo_xml(p).get("series"), "Sample Hero")

    def test_rewrite_leaves_a_single_comicinfo_entry(self):
        p = make_cbz(self.path("a.cbz"), comicinfo="<ComicInfo><Series>Old</Series></ComicInfo>")
        comic = Comic.objects.create(file_path=p, series="New", number="1", publisher="Pub")
        self.assertTrue(write_comicinfo_xml(p, comic))
        self.assertTrue(write_comicinfo_xml(p, comic))
        with zipfile.ZipFile(p) as zf:
            names = [n for n in zf.namelist() if n.lower() == "comicinfo.xml"]
            self.assertIsNone(zf.testzip())
        self.assertEqual(len(names), 1)
        self.assertEqual(page_colors(p), [0, 1, 2])


class CopyOnWriteWriteTests(TempDirMixin, TestCase):
    """The btrfs/XFS path: patch a reflink clone and swap it in atomically.

    Test machines run ext4, where reflinks fail, so the clone is simulated
    with a plain copy.
    """

    def setUp(self):
        super().setUp()
        from unittest.mock import patch
        from apps.core import utils

        def fake_reflink(src, dst):
            shutil.copyfile(src, dst)
            shutil.copystat(src, dst)
            return True

        p = patch.object(utils, "_try_reflink", fake_reflink)
        p.start()
        self.addCleanup(p.stop)

    def test_clone_is_synced_then_swapped_in(self):
        from unittest.mock import patch
        from apps.core import utils

        p = make_cbz(self.path("a.cbz"), mode=0o664)
        inode = os.stat(p).st_ino
        comic = Comic.objects.create(file_path=p, series="Cow", number="1", publisher="Pub")
        events = []
        real_fsync, real_replace = utils._fsync_file, os.replace

        def fsync(path):
            events.append(("fsync", os.path.basename(path) if path != self.tmp else "<folder>"))
            real_fsync(path)

        def replace(src, dst):
            events.append(("replace", os.path.basename(dst)))
            real_replace(src, dst)

        with patch.object(utils, "_fsync_file", fsync), \
                patch.object(utils.os, "replace", replace), \
                patch.object(utils, "_save_index_backup", side_effect=AssertionError("in-place path used")):
            self.assertTrue(write_comicinfo_xml(p, comic))

        self.assertEqual([e[0] for e in events], ["fsync", "replace", "fsync"])
        self.assertTrue(events[0][1].startswith(".cm-"))
        self.assertEqual(events[2][1], "<folder>")
        self.assertNotEqual(os.stat(p).st_ino, inode)
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o664)
        self.assertEqual(read_comicinfo_xml(p).get("series"), "Cow")
        self.assertEqual(os.listdir(self.tmp), ["a.cbz"])

    def test_failed_patch_leaves_original_untouched(self):
        from unittest.mock import patch
        from apps.core import utils

        p = make_cbz(self.path("a.cbz"))
        with open(p, "rb") as f:
            before = f.read()
        comic = Comic.objects.create(file_path=p, series="Cow", number="1", publisher="Pub")
        with patch.object(utils, "_patch_comicinfo_entry", side_effect=OSError("disk full")):
            self.assertFalse(write_comicinfo_xml(p, comic))
        with open(p, "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(os.listdir(self.tmp), ["a.cbz"])


class InterruptedWriteTests(TempDirMixin, TestCase):
    """An in-place ComicInfo write that dies halfway must be recoverable."""

    def _interrupt(self, p, comic):
        from unittest.mock import patch
        from apps.core import utils

        def dying_patch(zip_path, xml_bytes):
            # Simulate a crash after the new entry overwrote the old index but
            # before the new index was written
            with zipfile.ZipFile(zip_path) as zf:
                start = zf.start_dir
            with open(zip_path, "r+b") as f:
                f.seek(start)
                f.write(b"PK\x03\x04 partial entry")
                f.truncate()
            raise SystemExit("killed")

        with patch.object(utils, "_patch_comicinfo_entry", dying_patch), \
                patch.object(utils, "restore_index_backup", lambda path: False):
            with self.assertRaises(SystemExit):
                write_comicinfo_xml(p, comic)

    def test_backup_restores_original_archive(self):
        p = make_cbz(self.path("a.cbz"), comicinfo="<ComicInfo><Series>Old</Series></ComicInfo>")
        with open(p, "rb") as f:
            original = f.read()
        comic = Comic.objects.create(file_path=p, series="New", number="1", publisher="Pub")
        self._interrupt(p, comic)
        with self.assertRaises(zipfile.BadZipFile):
            zipfile.ZipFile(p)
        self.assertTrue(restore_index_backup(p))
        with open(p, "rb") as f:
            self.assertEqual(f.read(), original)
        self.assertEqual(os.listdir(self.tmp), ["a.cbz"])

    def test_rezip_and_next_write_recover(self):
        from pathlib import Path
        from apps.core.services import try_rezip_cbz
        p = make_cbz(self.path("a.cbz"))
        comic = Comic.objects.create(file_path=p, series="New", number="1", publisher="Pub")
        self._interrupt(p, comic)
        self.assertTrue(try_rezip_cbz(Path(p))["success"])
        self.assertEqual(page_colors(p), [0, 1, 2])

        self._interrupt(p, comic)
        self.assertTrue(write_comicinfo_xml(p, comic))
        self.assertEqual(read_comicinfo_xml(p).get("series"), "New")
        self.assertEqual(os.listdir(self.tmp), ["a.cbz"])

    def test_successful_write_leaves_no_backup(self):
        p = make_cbz(self.path("a.cbz"))
        comic = Comic.objects.create(file_path=p, series="New", number="1", publisher="Pub")
        self.assertTrue(write_comicinfo_xml(p, comic))
        self.assertEqual(os.listdir(self.tmp), ["a.cbz"])


class UntaggedScanTests(TempDirMixin, TestCase):

    def test_scan_imports_sample_library(self):
        created = make_sample_library(self.tmp)
        result = scan_untagged_folder(path=self.tmp)
        self.assertTrue(result["success"])
        self.assertEqual(result["imported"], len(created))
        comic = Comic.objects.get(file_path__endswith="Sample Hero 002 (2020).cbz")
        self.assertEqual(comic.state, Comic.STATE_NEW)
        self.assertEqual(comic.page_count, 3)

    def test_rescan_skips_known_files(self):
        created = make_sample_library(self.tmp)
        scan_untagged_folder(path=self.tmp)
        result = scan_untagged_folder(path=self.tmp)
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["skipped"], len(created))

    def test_missing_files_are_flagged_not_deleted(self):
        make_sample_library(self.tmp)
        scan_untagged_folder(path=self.tmp)
        worked = Comic.objects.get(file_path__endswith="Sample Hero 001 (2020).cbz")
        worked.state = Comic.STATE_FORMATTED
        worked.series = "Sample Hero"
        worked.save()
        untouched = Comic.objects.get(file_path__endswith="Another Book 001 (1999).cbz")
        os.remove(worked.file_path)
        os.remove(untouched.file_path)

        result = scan_untagged_folder(path=self.tmp)
        self.assertEqual(result["cleaned"], 1)
        self.assertFalse(Comic.objects.filter(pk=untouched.pk).exists())
        worked.refresh_from_db()
        self.assertEqual(worked.series, "Sample Hero")
        self.assertTrue(worked.has_flag("file_missing"))

        # File comes back: the flag clears
        make_cbz(worked.file_path)
        scan_untagged_folder(path=self.tmp)
        worked.refresh_from_db()
        self.assertFalse(worked.has_flag("file_missing"))

    def test_unmounted_folder_changes_nothing(self):
        make_sample_library(self.tmp)
        scan_untagged_folder(path=self.tmp)
        count = Comic.objects.count()
        for entry in os.listdir(self.tmp):
            shutil.rmtree(self.path(entry))
        result = check_missing_files(self.tmp)
        self.assertTrue(result["skipped"])
        self.assertEqual(Comic.objects.count(), count)
        self.assertFalse(Comic.objects.filter(flags__file_missing=True).exists())


    def test_scan_finds_uppercase_extensions_and_skips_hidden_files(self):
        make_cbz(self.path("Loud", "LOUD 001.CBZ"))
        make_cbz(self.path("Loud", "._LOUD 001.cbz"))
        result = scan_untagged_folder(path=self.tmp)
        self.assertEqual(result["imported"], 1)
        self.assertTrue(Comic.objects.filter(file_path__endswith="LOUD 001.CBZ").exists())


class ConvertTests(TempDirMixin, TestCase):

    def _make_cb7(self, name):
        import subprocess
        src = self.path("src")
        os.makedirs(src, exist_ok=True)
        from apps.core.sample_data import page_image, PAGE_COLORS
        for i in range(3):
            with open(os.path.join(src, f"{i:03d}.jpg"), "wb") as f:
                f.write(page_image(PAGE_COLORS[i]))
        out = self.path(name)
        subprocess.run(["7z", "a", "-bd", "-y", out, os.path.join(src, "*")],
                       check=True, capture_output=True)
        shutil.rmtree(src)
        os.chmod(out, 0o664)
        return out

    def test_convert_cb7(self):
        from apps.core.tasks import _convert_comic_to_cbz
        p = self._make_cb7("Book 001.cb7")
        comic = Comic.objects.create(file_path=p, file_format="cb7")
        result = _convert_comic_to_cbz(comic)
        self.assertTrue(result["success"], result)
        comic.refresh_from_db()
        self.assertEqual(comic.file_path, self.path("Book 001.cbz"))
        self.assertEqual(page_colors(comic.file_path), [0, 1, 2])
        self.assertEqual(stat.S_IMODE(os.stat(comic.file_path).st_mode), 0o664)
        self.assertEqual(os.listdir(self.tmp), ["Book 001.cbz"])

    def test_existing_cbz_with_same_name_is_left_alone(self):
        from apps.core.tasks import _convert_comic_to_cbz
        p = self._make_cb7("Book 001.cb7")
        other = make_cbz(self.path("Book 001.cbz"), ["a.jpg"])
        comic = Comic.objects.create(file_path=p, file_format="cb7")
        result = _convert_comic_to_cbz(comic)
        self.assertFalse(result["success"])
        self.assertTrue(os.path.exists(p))
        self.assertEqual(page_colors(other), [0])
        comic.refresh_from_db()
        self.assertEqual(comic.file_path, p)


class EscapingTests(TestCase):

    def test_rollback_escapes_invalid_state(self):
        comic = Comic.objects.create(series="S", number="1")
        resp = self.client.post(f"/comics/{comic.pk}/rollback/", {"to_state": "<img src=x onerror=alert(1)>"})
        self.assertNotIn(b"<img", resp.content)
        self.assertIn(b"&lt;img", resp.content)

    def test_smartlist_filters_cannot_break_out_of_script(self):
        from apps.dashboard.models import SmartList
        sl = SmartList.objects.create(name="x", filters=[
            {"field": "series", "lookup": "icontains", "value": "</script><b>boom</b>"},
            {"field": "series", "lookup": "isnull", "value": True},
        ])
        resp = self.client.get(f"/smartlists/{sl.pk}/edit/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b"</script><b>boom", resp.content)
        self.assertIn(b'id="existing-filters"', resp.content)


class MisnamedArchiveTests(TempDirMixin, TestCase):
    """RAR (and 7-Zip) archives named .cbz are converted, not reported as corrupted."""

    def test_sniff(self):
        from apps.core.archives import misnamed_format, sniff_archive
        rar = make_rar(self.path("a.cbz"))
        zip_ = make_cbz(self.path("b.cbz"))
        self.assertEqual(sniff_archive(rar), "rar")
        self.assertEqual(misnamed_format(rar), "cbr")
        self.assertEqual(sniff_archive(zip_), "zip")
        self.assertIsNone(misnamed_format(zip_))
        self.assertIsNone(misnamed_format(make_rar(self.path("c.cbr"))))

    def test_scan_flags_rar_named_cbz_for_conversion(self):
        make_rar(self.path("Book", "Book 001.cbz"))
        scan_untagged_folder(path=self.tmp)
        comic = Comic.objects.get()
        self.assertEqual(comic.file_format, "cbr")
        self.assertTrue(comic.has_flag("needs_conversion"))
        self.assertFalse(comic.has_flag("corrupted_archive"))

    def test_convert_rar_named_cbz_in_place(self):
        from apps.core.tasks import _convert_comic_to_cbz
        p = make_rar(self.path("Book 001.cbz"), mode=0o664)
        comic = Comic.objects.create(file_path=p, file_format="cbr",
                                     flags={"needs_conversion": True, "corrupted_archive": True})
        result = _convert_comic_to_cbz(comic)
        self.assertTrue(result["success"], result)
        comic.refresh_from_db()
        self.assertEqual(comic.file_path, p)
        self.assertEqual(comic.file_format, "cbz")
        self.assertEqual(comic.flags, {})
        self.assertEqual(comic.page_count, 3)
        self.assertIsNotNone(comic.phash)
        self.assertEqual(page_colors(p), [0, 1, 2])
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o664)
        self.assertEqual(os.listdir(self.tmp), ["Book 001.cbz"])

    def test_convert_real_cbr(self):
        from apps.core.tasks import _convert_comic_to_cbz
        p = make_rar(self.path("Book 001.cbr"))
        comic = Comic.objects.create(file_path=p, file_format="cbr")
        self.assertTrue(_convert_comic_to_cbz(comic)["success"])
        self.assertEqual(os.listdir(self.tmp), ["Book 001.cbz"])
        self.assertEqual(page_colors(self.path("Book 001.cbz")), [0, 1, 2])

    def test_broken_rar_is_left_untouched(self):
        from apps.core.tasks import _convert_comic_to_cbz
        p = make_rar(self.path("Book 001.cbz"))
        with open(p, "r+b") as f:
            f.truncate(os.path.getsize(p) - 2000)
        with open(p, "rb") as f:
            before = f.read()
        comic = Comic.objects.create(file_path=p, file_format="cbr")
        result = _convert_comic_to_cbz(comic)
        self.assertFalse(result["success"])
        with open(p, "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(os.listdir(self.tmp), ["Book 001.cbz"])
        comic.refresh_from_db()
        self.assertEqual(comic.file_format, "cbr")

    def test_rezip_converts_rar_named_cbz(self):
        p = make_rar(self.path("Book 001.cbz"))
        comic = Comic.objects.create(file_path=p, file_format="cbz", flags={"corrupted_archive": True})
        resp = self.client.post(f"/comics/{comic.pk}/rezip/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn("converted", resp.json()["message"])
        comic.refresh_from_db()
        self.assertEqual(comic.page_count, 3)
        self.assertFalse(comic.has_flag("corrupted_archive"))
        self.assertEqual(page_colors(p), [0, 1, 2])

    def test_command_converts_library_files_and_import_hints(self):
        from io import StringIO
        from django.core.management import call_command
        rar = make_rar(self.path("Pub", "Book 001.cbz"))
        good = make_cbz(self.path("Pub", "Book 002.cbz"))

        out = StringIO()
        call_command("import_library", path=self.tmp, stdout=out, stderr=StringIO())
        self.assertIn("convert_misnamed_archives", out.getvalue())

        out = StringIO()
        call_command("convert_misnamed_archives", path=self.tmp, dry_run=True, stdout=out)
        self.assertIn("Would convert (RAR)", out.getvalue())
        with open(rar, "rb") as f:
            self.assertTrue(f.read(4) == b"Rar!")

        out = StringIO()
        call_command("convert_misnamed_archives", path=self.tmp, stdout=out)
        self.assertIn("Converted: 1", out.getvalue())
        self.assertIn("import_library", out.getvalue())
        self.assertEqual(page_colors(rar), [0, 1, 2])
        self.assertEqual(page_colors(good), [0, 1, 2])
