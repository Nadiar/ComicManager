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
from apps.core.sample_data import make_cbz, make_sample_library, page_colors
from apps.core.services import scan_untagged_folder
from apps.core.utils import read_comicinfo_xml, write_comicinfo_xml


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
