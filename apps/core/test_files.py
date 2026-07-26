"""File-level tests: CBZ page edits, ComicInfo writes and the untagged scan.

All archives are generated in a temp folder by apps.core.sample_data.
"""

import os
import shutil
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

    def test_delete_all_pages_refused(self):
        p = make_cbz(self.path("a.cbz"), ["001.jpg", "002.jpg"])
        self.assertFalse(cbz_utils.delete_pages(p, [0, 1]))
        self.assertEqual(page_colors(p), [0, 1])


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
