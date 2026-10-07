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


class PageOrderTests(TestCase):
    """Numbers compare by value and case is ignored; everything else keeps the
    plain sorted order that scanners name their pages for."""

    def assertOrder(self, names):
        self.assertEqual(cbz_utils.list_pages(list(reversed(names))), names)

    def test_numbers_compare_by_value(self):
        self.assertOrder(["1.png", "2.png", "10.png", "11.png"])

    def test_case_is_ignored(self):
        self.assertOrder(["sho00801.jpg", "sho00802.jpg", "SHO00803.JPG"])

    def test_suffixes_keep_plain_order(self):
        self.assertOrder(["00fc.jpg", "00ifc.jpg", "00ifc2.jpg", "01.jpg",
                          "13.jpg", "13ad.jpg", "13ad2.jpg", "14.jpg"])

    def test_spreads_stay_in_place(self):
        self.assertOrder(["bt_02_01.jpg", "bt_02_02.jpg", "bt_02_0304.jpg", "bt_02_05.jpg",
                          "bt_02_10.jpg", "bt_02_1112.jpg", "bt_02_13.jpg"])
        self.assertOrder(["gl-71.jpg", "gl-7273.jpg", "gl-72x.jpg", "gl-73x.jpg", "gl-74.jpg"])

    def test_spreads_stay_in_place_when_most_pages_are_spreads(self):
        self.assertOrder(["p02.jpg", "p0304.jpg", "p05.jpg", "p0607.jpg",
                          "p0809.jpg", "p1011.jpg", "p12.jpg"])

    def test_long_numbering_is_not_read_as_spreads(self):
        self.assertOrder([f"{i}.jpg" for i in range(1, 1101)])
        self.assertOrder([f"Book v02 - {i:04d}.jpg" for i in range(1, 151)])


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

    def test_repeated_writes_do_not_grow_the_archive(self):
        p = make_cbz(self.path("a.cbz"), comicinfo="<ComicInfo><Series>Old</Series></ComicInfo>")
        comic = Comic.objects.create(file_path=p, series="Same", number="1", publisher="Pub")
        sizes = []
        for _ in range(5):
            self.assertTrue(write_comicinfo_xml(p, comic))
            sizes.append(os.path.getsize(p))
        self.assertEqual(len(set(sizes[1:])), 1, sizes)
        with zipfile.ZipFile(p) as zf:
            self.assertIsNone(zf.testzip())
            self.assertEqual([n for n in zf.namelist() if n.lower() == "comicinfo.xml"], ["ComicInfo.xml"])
        self.assertEqual(page_colors(p), [0, 1, 2])

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

    def test_interrupted_overwrite_of_old_comicinfo_is_restored(self):
        from unittest.mock import patch
        from apps.core import utils
        p = make_cbz(self.path("a.cbz"))
        comic = Comic.objects.create(file_path=p, series="First", number="1", publisher="Pub")
        self.assertTrue(write_comicinfo_xml(p, comic))   # ComicInfo.xml is now the last entry
        with open(p, "rb") as f:
            original = f.read()

        def dying_patch(zip_path, xml_bytes):
            # Crash halfway through writing over the old ComicInfo.xml entry
            with zipfile.ZipFile(zip_path) as zf:
                offset = utils._patch_offset(zf)
            with open(zip_path, "r+b") as f:
                f.seek(offset)
                f.write(b"PK\x03\x04 partial")
                f.truncate()
            raise SystemExit("killed")

        comic.series = "Second"
        with patch.object(utils, "_patch_comicinfo_entry", dying_patch), \
                patch.object(utils, "restore_index_backup", lambda path: False):
            with self.assertRaises(SystemExit):
                write_comicinfo_xml(p, comic)
        self.assertTrue(restore_index_backup(p))
        with open(p, "rb") as f:
            self.assertEqual(f.read(), original)

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
        self.assertEqual(result["flagged_missing"], 1)
        self.assertFalse(Comic.objects.filter(pk=untouched.pk).exists())
        worked.refresh_from_db()
        self.assertEqual(worked.series, "Sample Hero")
        self.assertTrue(worked.has_flag("file_missing"))

        # File comes back: the flag clears
        make_cbz(worked.file_path)
        result = scan_untagged_folder(path=self.tmp)
        self.assertEqual(result["unflagged_missing"], 1)
        worked.refresh_from_db()
        self.assertFalse(worked.has_flag("file_missing"))

    def test_scan_task_reports_missing_file_counts(self):
        from apps.core.tasks import scan_untagged_task
        make_sample_library(self.tmp)
        scan_untagged_folder(path=self.tmp)
        worked = Comic.objects.get(file_path__endswith="Sample Hero 001 (2020).cbz")
        worked.state = Comic.STATE_FORMATTED
        worked.save()
        os.remove(worked.file_path)
        with self.settings(UNTAGGED_DIR=self.tmp):
            result = scan_untagged_task.apply().get()
        self.assertEqual(result["flagged_missing"], 1)
        self.assertEqual(result["unflagged_missing"], 0)

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


class ZipRenameTests(TempDirMixin, TestCase):
    """A .zip becomes a .cbz only when it really is a ZIP, and never replaces a file."""

    def _comic(self, path):
        return Comic.objects.create(file_path=path, file_format="zip", flags={"is_zip": True})

    def test_scan_flags_rar_named_zip_for_conversion(self):
        make_rar(self.path("Book 001.zip"))
        make_cbz(self.path("Other 001.zip"))
        scan_untagged_folder(path=self.tmp)
        rar = Comic.objects.get(file_path__endswith="Book 001.zip")
        self.assertEqual(rar.file_format, "cbr")
        self.assertTrue(rar.has_flag("needs_conversion"))
        self.assertFalse(rar.has_flag("is_zip"))
        self.assertTrue(Comic.objects.get(file_path__endswith="Other 001.zip").has_flag("is_zip"))

    def test_rename_real_zip(self):
        comic = self._comic(make_cbz(self.path("Book 001.zip")))
        resp = self.client.post(f"/comics/{comic.pk}/convert-zip/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(os.listdir(self.tmp), ["Book 001.cbz"])
        comic.refresh_from_db()
        self.assertEqual((comic.file_format, comic.flags), ("cbz", {}))

    def test_rar_named_zip_is_flagged_not_renamed(self):
        from apps.core.tasks import _convert_comic_to_cbz
        comic = self._comic(make_rar(self.path("Book 001.zip")))
        resp = self.client.post(f"/comics/{comic.pk}/convert-zip/")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(os.listdir(self.tmp), ["Book 001.zip"])
        comic.refresh_from_db()
        self.assertEqual((comic.file_format, comic.flags), ("cbr", {"needs_conversion": True}))

        # Convert then writes a real CBZ next to it and removes the .zip
        self.assertTrue(_convert_comic_to_cbz(comic)["success"])
        self.assertEqual(os.listdir(self.tmp), ["Book 001.cbz"])
        self.assertEqual(page_colors(self.path("Book 001.cbz")), [0, 1, 2])

    def test_rename_never_replaces_an_existing_file(self):
        from apps.core.archives import rename_no_clobber
        src = make_cbz(self.path("a.zip"))
        dest = make_cbz(self.path("a.cbz"), ["x.jpg"])
        with self.assertRaises(FileExistsError):
            rename_no_clobber(src, dest)
        self.assertEqual(sorted(os.listdir(self.tmp)), ["a.cbz", "a.zip"])
        self.assertEqual(cbz_utils.list_pages(zipfile.ZipFile(dest).namelist()), ["x.jpg"])

    def test_batch_rename_skips_rar_named_zip(self):
        from apps.core.tasks import convert_all_zip_task
        self._comic(make_cbz(self.path("Real 001.zip")))
        rar = self._comic(make_rar(self.path("Rar 001.zip")))
        result = convert_all_zip_task.apply().get()
        self.assertEqual(result["converted"], 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(sorted(os.listdir(self.tmp)), ["Rar 001.zip", "Real 001.cbz"])
        rar.refresh_from_db()
        self.assertEqual(rar.file_format, "cbr")
        self.assertTrue(rar.has_flag("needs_conversion"))


class ImportLibraryTests(TempDirMixin, TestCase):

    def test_import_writes_error_log_next_to_audit_log(self):
        from io import StringIO
        from django.core.management import call_command
        from django.test import override_settings
        logs = self.path("logs")
        make_cbz(self.path("lib", "Pub", "No Info 001.cbz"))
        make_cbz(self.path("lib", "Pub", "Tagged 001.cbz"),
                 comicinfo="<ComicInfo><Series>Tagged</Series><Number>1</Number></ComicInfo>")
        with override_settings(AUDIT_LOG_PATH=os.path.join(logs, "batch_actions.jsonl")):
            call_command("import_library", path=self.path("lib"), stdout=StringIO(), stderr=StringIO())
        self.assertTrue(Comic.objects.filter(series="Tagged", state=Comic.STATE_WRITTEN).exists())
        with open(os.path.join(logs, "import_errors.log")) as f:
            self.assertIn("No ComicInfo.xml in: No Info 001.cbz", f.read())

    def test_import_finds_uppercase_extensions_and_skips_hidden_files(self):
        from io import StringIO
        from django.core.management import call_command
        from django.test import override_settings
        lib = self.path("lib")
        make_cbz(os.path.join(lib, "Pub", "Loud 003.CBZ"),
                 comicinfo="<ComicInfo><Series>Loud</Series><Number>3</Number></ComicInfo>")
        make_cbz(os.path.join(lib, "Pub", "._Loud 003.cbz"))
        with override_settings(AUDIT_LOG_PATH=self.path("logs", "batch_actions.jsonl")):
            call_command("import_library", path=lib, stdout=StringIO(), stderr=StringIO())
        self.assertEqual(list(Comic.objects.values_list("series", flat=True)), ["Loud"])

    def test_import_uses_comicdb_for_files_without_comicinfo(self):
        from io import StringIO
        from django.core.management import call_command
        from django.test import override_settings
        lib = self.path("lib")
        make_cbz(os.path.join(lib, "Pub", "Tagged 001.cbz"),
                 comicinfo="<ComicInfo><Series>Tagged</Series><Number>1</Number></ComicInfo>")
        make_cbz(os.path.join(lib, "Pub", "No Info 002.cbz"))
        make_cbz(os.path.join(lib, "Pub", "Loud 003.CBZ"),
                 comicinfo="<ComicInfo><Series>Loud</Series><Number>3</Number></ComicInfo>")
        make_cbz(os.path.join(lib, "Pub", "._Tagged 001.cbz"))
        comicdb = self.path("ComicDb.xml")
        with open(comicdb, "w") as f:
            f.write(
                '<?xml version="1.0"?><ComicDatabase><Books>'
                '<Book File="B:\\Comics\\ComicRack\\Pub\\No Info 002.cbz">'
                "<Series>From ComicDb</Series><Number>2</Number><Volume>1999</Volume>"
                "<Publisher>Pub</Publisher><Tags>Romance</Tags></Book>"
                '<Book File="B:\\Comics\\ComicRack\\Pub\\Elsewhere.cbz"><Series>Other</Series></Book>'
                "</Books></ComicDatabase>"
            )
        out = StringIO()
        with override_settings(AUDIT_LOG_PATH=self.path("logs", "batch_actions.jsonl")):
            call_command("import_library", path=lib, comicdb=comicdb, stdout=out, stderr=StringIO())
        self.assertEqual(Comic.objects.count(), 3)
        from_db = Comic.objects.get(file_path__endswith="No Info 002.cbz")
        self.assertEqual((from_db.series, from_db.number, from_db.volume, from_db.publisher, from_db.tags),
                         ("From ComicDb", "2", 1999, "Pub", "Romance"))
        self.assertEqual(from_db.state, Comic.STATE_WRITTEN)
        self.assertTrue(Comic.objects.filter(file_path__endswith="Loud 003.CBZ").exists())
        self.assertIn("Imported from ComicDb.xml (no ComicInfo.xml in the file): 1", out.getvalue())

    def test_dry_run_counts_what_it_would_import(self):
        from io import StringIO
        from django.core.management import call_command
        from django.test import override_settings
        lib = self.path("lib")
        make_cbz(os.path.join(lib, "Pub", "Tagged 001.cbz"),
                 comicinfo="<ComicInfo><Series>Tagged</Series><Number>1</Number></ComicInfo>")
        make_cbz(os.path.join(lib, "Pub", "Loud 003.CBZ"),
                 comicinfo="<ComicInfo><Series>Loud</Series><Number>3</Number></ComicInfo>")
        out = StringIO()
        with override_settings(AUDIT_LOG_PATH=self.path("logs", "batch_actions.jsonl")):
            call_command("import_library", path=lib, dry_run=True, stdout=out, stderr=StringIO())
        self.assertEqual(Comic.objects.count(), 0)
        self.assertIn("Would import: 2", out.getvalue())
        self.assertNotIn("Imported: 0", out.getvalue())


class AuditLogTests(TempDirMixin, TestCase):

    def _write_log(self, entries):
        import json as _json
        path = self.path("batch_actions.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(_json.dumps(e) + "\n")
        return path

    def test_history_and_log_page(self):
        from django.test import override_settings
        from apps.core.audit import get_comic_audit_history, recent_log_entries
        a, b = "6f1c1d2e-0000-4000-8000-00000000000a", "6f1c1d2e-0000-4000-8000-00000000000b"
        entries = []
        for i in range(30):
            entries.append({"timestamp": f"2026-01-01T00:00:{i:02d}", "action": "write_all" if i % 3 else "convert_cbr",
                            "uuid": a if i % 2 else b, "name": f"x #{i}",
                            "state_before": "write", "state_after": "done", "changes": {"n": [i, i + 1]}})
        path = self._write_log(entries)
        with override_settings(AUDIT_LOG_PATH=path):
            hist = get_comic_audit_history(a)
            self.assertEqual([e["name"] for e in hist], [f"x #{i}" for i in range(29, 0, -2)])

            shown, total = recent_log_entries(limit=5)
            self.assertEqual(total, 30)
            self.assertEqual([e["name"] for e in shown], ["x #29", "x #28", "x #27", "x #26", "x #25"])

            # The action filter searches the whole log, not only its last lines
            shown, total = recent_log_entries("convert_cbr", limit=3)
            self.assertEqual(total, 10)
            self.assertEqual([e["name"] for e in shown], ["x #27", "x #24", "x #21"])

            page = self.client.get("/settings/log/?action=convert_cbr")
            self.assertContains(page, "10 entries total")
