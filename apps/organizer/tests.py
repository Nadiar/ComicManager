"""Tests for the Library Organizer template engine and move safety."""

import os
import shutil
import tempfile

from django.test import SimpleTestCase, TestCase

from apps.core.models import Comic
from apps.core.sample_data import make_cbz
from apps.organizer.models import OrganizerProfile
from apps.organizer.services import FileOverwriteError, _safe_move
from apps.organizer.template_engine import _pad_number


class PadNumberTests(SimpleTestCase):
    """Issue-number padding must preserve any decimal or suffix part."""

    def test_decimal_preserved(self):
        self.assertEqual(_pad_number("23.1", 3), "023.1")

    def test_plain_integer_padded(self):
        self.assertEqual(_pad_number("7", 3), "007")

    def test_zero_padded(self):
        self.assertEqual(_pad_number("0", 3), "000")

    def test_pure_fraction_glyph_unchanged(self):
        self.assertEqual(_pad_number("½", 3), "½")

    def test_alpha_suffix_preserved(self):
        self.assertEqual(_pad_number("1AU", 3), "001AU")

    def test_dotted_suffix_preserved(self):
        self.assertEqual(_pad_number("1.MU", 3), "001.MU")

    def test_negative_one_unchanged(self):
        self.assertEqual(_pad_number("-1", 3), "-1")

    def test_already_wide_number_not_truncated(self):
        self.assertEqual(_pad_number("1234", 3), "1234")

    def test_whitespace_stripped(self):
        self.assertEqual(_pad_number("  23.1  ", 3), "023.1")

    def test_empty_returns_empty(self):
        self.assertEqual(_pad_number("", 3), "")

    def test_none_returns_empty(self):
        self.assertEqual(_pad_number(None, 3), "")


class SafeMoveTests(SimpleTestCase):
    """A move must never silently overwrite a different existing file."""

    def test_move_to_empty_destination_succeeds(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "src.cbz")
            dst = os.path.join(d, "dst.cbz")
            with open(src, "w") as f:
                f.write("source")
            _safe_move(src, dst, d)
            self.assertFalse(os.path.exists(src))
            with open(dst) as f:
                self.assertEqual(f.read(), "source")

    def test_move_onto_different_existing_file_raises(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "src.cbz")
            dst = os.path.join(d, "dst.cbz")
            with open(src, "w") as f:
                f.write("source")
            with open(dst, "w") as f:
                f.write("victim")
            with self.assertRaises(FileOverwriteError):
                _safe_move(src, dst, d)
            # Both files are left untouched.
            self.assertTrue(os.path.exists(src))
            with open(dst) as f:
                self.assertEqual(f.read(), "victim")

    def test_move_outside_allowed_root_raises(self):
        with tempfile.TemporaryDirectory() as d:
            library = os.path.join(d, "library")
            outside = os.path.join(d, "outside")
            os.makedirs(library)
            os.makedirs(outside)
            src = os.path.join(library, "src.cbz")
            # Simulates a template variable (e.g. series="../../outside") walking
            # the destination out of the profile's base_folder.
            dst = os.path.join(library, "..", "outside", "dst.cbz")
            with open(src, "w") as f:
                f.write("source")
            with self.assertRaises(ValueError):
                _safe_move(src, dst, library)
            self.assertTrue(os.path.exists(src))
            self.assertFalse(os.path.exists(os.path.join(outside, "dst.cbz")))

    def test_move_across_mounts_copies_via_hidden_temp(self):
        import errno
        from unittest.mock import patch
        real_link = os.link
        calls = []

        def link(src, dst):
            calls.append(src)
            if len(calls) == 1:
                raise OSError(errno.EXDEV, "Invalid cross-device link")
            return real_link(src, dst)

        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "src.cbz")
            dst = os.path.join(d, "dst.cbz")
            with open(src, "w") as f:
                f.write("source")
            with patch("apps.organizer.services.os.link", side_effect=link):
                _safe_move(src, dst, d)
            self.assertEqual(os.listdir(d), ["dst.cbz"])
            with open(dst) as f:
                self.assertEqual(f.read(), "source")
            self.assertIn(".cm-move-", calls[1])

    def _no_hard_links(self):
        """Patch os.link to fail like a filesystem without hard links (Gitea #10)."""
        import errno
        from unittest.mock import patch
        return patch("apps.organizer.services.os.link",
                     side_effect=OSError(errno.EPERM, "Operation not permitted"))

    def test_move_without_hard_links_renames_the_temp_file(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "src.cbz")
            dst = os.path.join(d, "sub", "dst.cbz")
            os.makedirs(os.path.dirname(dst))
            with open(src, "w") as f:
                f.write("source")
            with self._no_hard_links():
                _safe_move(src, dst, d)
            self.assertFalse(os.path.exists(src))
            self.assertEqual(os.listdir(os.path.dirname(dst)), ["dst.cbz"])
            with open(dst) as f:
                self.assertEqual(f.read(), "source")

    def test_move_without_hard_links_never_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "src.cbz")
            dst = os.path.join(d, "dst.cbz")
            with open(src, "w") as f:
                f.write("source")
            with open(dst, "w") as f:
                f.write("victim")
            # Hide dst from the first check only, as if another move created it
            # while the temp copy was being made
            from unittest.mock import patch
            real_exists = os.path.exists
            hidden = []

            def exists(path):
                if path == dst and not hidden:
                    hidden.append(path)
                    return False
                return real_exists(path)

            with self._no_hard_links(), patch("apps.organizer.services.os.path.exists", side_effect=exists):
                with self.assertRaises(FileOverwriteError):
                    _safe_move(src, dst, d)
            self.assertTrue(os.path.exists(src))
            with open(dst) as f:
                self.assertEqual(f.read(), "victim")
            self.assertEqual(sorted(os.listdir(d)), ["dst.cbz", "src.cbz"])


class MissingFileTests(TestCase):
    """Path Audit must not offer moves for files that are gone (Gitea #4)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        OrganizerProfile.objects.update_or_create(
            name="Default",
            defaults={"priority": 9999, "is_enabled": True, "base_folder": self.tmp,
                      "folder_template": "{<publisher>}/{<series>}",
                      "file_template": "{<series>}{ #<number3>}", "exclude_rules": {}},
        )

    def _comic(self, path, **kw):
        defaults = dict(series="Sample Hero", number="1", publisher="Pub",
                        state=Comic.STATE_DONE, file_format="cbz")
        defaults.update(kw)
        return Comic.objects.create(file_path=path, **defaults)

    def test_audit_flags_missing_instead_of_reorganize(self):
        from apps.organizer.tasks import audit_paths_task
        gone = self._comic(os.path.join(self.tmp, "old", "gone.cbz"))
        audit_paths_task.apply()
        gone.refresh_from_db()
        self.assertTrue(gone.has_flag("file_missing"))
        self.assertFalse(gone.needs_reorganize)
        page = self.client.get("/organizer/path-audit/")
        self.assertEqual(page.context["total_missing"], 1)
        self.assertEqual(page.context["total_flagged"], 0)

    def test_page_lists_comics_to_move_next_to_missing_ones(self):
        from apps.organizer.tasks import audit_paths_task
        self._comic(make_cbz(os.path.join(self.tmp, "Pub", "Sample Hero", "Sample Hero #001.cbz")))
        misplaced = self._comic(make_cbz(os.path.join(self.tmp, "elsewhere", "x.cbz")), number="2")
        self._comic(os.path.join(self.tmp, "old", "gone.cbz"), number="3")
        audit_paths_task.apply()
        page = self.client.get("/organizer/path-audit/")
        self.assertEqual(page.context["total_flagged"], 1)
        self.assertEqual([c.pk for c in page.context["comics"]], [misplaced.pk])
        self.assertEqual(page.context["total_missing"], 1)
        self.assertEqual(page.context["total_correct"], 1)
        self.assertRegex(page.content.decode(), r"Correct Location</div>\s*<div[^>]*>1</div>")

    def test_relink_finds_file_in_target_folder(self):
        target = make_cbz(os.path.join(self.tmp, "Pub", "Sample Hero", "Sample Hero #001 (2020).cbz"))
        comic = self._comic(os.path.join(self.tmp, "old", "gone.cbz"), flags={"file_missing": True})
        resp = self.client.post(f"/organizer/path-audit/relink/{comic.pk}/")
        self.assertEqual(resp.status_code, 200, resp.content)
        comic.refresh_from_db()
        self.assertEqual(comic.file_path, target)
        self.assertFalse(comic.has_flag("file_missing"))

    def test_relink_ignores_other_series_with_same_prefix(self):
        make_cbz(os.path.join(self.tmp, "Pub", "Sample Hero", "Sample Hero Beyond #001.cbz"))
        comic = self._comic(os.path.join(self.tmp, "old", "gone.cbz"), flags={"file_missing": True})
        resp = self.client.post(f"/organizer/path-audit/relink/{comic.pk}/")
        self.assertEqual(resp.status_code, 404)

    def test_remove_missing_only_when_file_is_gone(self):
        present = self._comic(make_cbz(os.path.join(self.tmp, "here.cbz")))
        gone = self._comic(os.path.join(self.tmp, "gone.cbz"), number="2")
        self.assertEqual(self.client.post(f"/organizer/path-audit/remove-missing/{present.pk}/").status_code, 409)
        self.assertTrue(os.path.exists(present.file_path))
        self.assertEqual(self.client.post(f"/organizer/path-audit/remove-missing/{gone.pk}/").status_code, 200)
        self.assertFalse(Comic.objects.filter(pk=gone.pk).exists())

    def test_sync_relinks_done_comics(self):
        from apps.organizer.services import sync_library_paths
        target = make_cbz(os.path.join(self.tmp, "Pub", "Sample Hero", "Sample Hero #1.cbz"))
        comic = self._comic(os.path.join(self.tmp, "old", "gone.cbz"))
        sync_library_paths()
        comic.refresh_from_db()
        self.assertEqual(comic.file_path, target)

    def test_sync_flags_a_comic_whose_file_belongs_to_another_instead_of_deleting_it(self):
        from apps.organizer.services import sync_library_paths
        target = make_cbz(os.path.join(self.tmp, "Pub", "Sample Hero", "Sample Hero #001.cbz"))
        owner = self._comic(target)
        stale = self._comic(os.path.join(self.tmp, "old", "gone.cbz"), notes="Only copy of these notes")
        result = sync_library_paths()
        stale.refresh_from_db()
        self.assertTrue(stale.has_flag("file_missing"))
        self.assertEqual(stale.notes, "Only copy of these notes")
        self.assertEqual(result["flagged_missing"], 1)
        self.assertEqual(Comic.objects.get(pk=owner.pk).file_path, target)


class DefaultProfileTests(TestCase):

    def test_default_profile_fills_in_fields(self):
        from apps.organizer.services import preview_organization
        comic = Comic.objects.create(file_path="/comics/untagged/x.cbz", series="Sample Hero",
                                     number="1", publisher="Pub", volume=2020, year=2020)
        self.assertEqual(preview_organization(comic)["new_path"],
                         "/comics/library/Pub/Sample Hero (2020)/Sample Hero #1 (2020).cbz")

    def test_recreated_default_profile_fills_in_fields(self):
        from apps.organizer.services import get_default_profile, preview_organization
        OrganizerProfile.objects.filter(name="Default").delete()
        get_default_profile()
        comic = Comic.objects.create(file_path="/comics/untagged/x.cbz", series="Sample Hero",
                                     number="1", publisher="Pub")
        self.assertEqual(preview_organization(comic)["new_path"],
                         "/comics/library/Pub/Sample Hero/Sample Hero #1.cbz")


class ImprintTests(TestCase):
    """Imprint works as a template variable, a profile condition and a rule field."""

    def setUp(self):
        self.profile = OrganizerProfile(
            name="Imprint", base_folder="/comics/library",
            folder_template="{<publisher>}/{<imprint>}/{<series>}{ (V<volume>)}",
            file_template="{<series>}{ #<number3>}", exclude_rules={},
        )

    def test_imprint_becomes_a_folder(self):
        from apps.organizer.template_engine import generate_paths
        comic = Comic(series="Sandman", number="1", volume=1989, publisher="DC Comics", imprint="Vertigo")
        folder, _ = generate_paths(comic, self.profile)
        self.assertEqual(folder.replace("\\", "/"), "DC Comics/Vertigo/Sandman (V1989)")

    def test_empty_imprint_leaves_out_the_folder(self):
        from apps.organizer.template_engine import generate_paths
        comic = Comic(series="Batman", number="1", volume=2016, publisher="DC Comics")
        folder, _ = generate_paths(comic, self.profile)
        self.assertEqual(folder.replace("\\", "/"), "DC Comics/Batman (V2016)")

    def test_profile_condition_on_imprint(self):
        from apps.organizer.engine import matches_profile
        self.profile.exclude_rules = {"operator": "All", "mode": "Only", "rules": [
            {"type": "rule", "field": "Imprint", "operator": "is", "value": "Vertigo"}]}
        self.assertTrue(matches_profile(Comic(imprint="Vertigo"), self.profile))
        self.assertFalse(matches_profile(Comic(imprint="Black Label"), self.profile))

    def test_rule_sets_imprint_field(self):
        from apps.tagging.engine import FIELD_MAP, action_set_value
        comic = Comic(series="Sandman")
        action_set_value(comic, "Imprint", "Vertigo")
        self.assertEqual(comic.imprint, "Vertigo")
        self.assertNotIn("Imprint", comic.custom_values)
        self.assertIn("Imprint", FIELD_MAP)


class MoveErrorLogTests(TestCase):
    """A failed move leaves its reason in the container log and the batch log (Gitea #10)."""

    def setUp(self):
        from django.test import override_settings
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.enterContext(override_settings(LIBRARY_DIR=os.path.join(self.tmp, "library")))
        OrganizerProfile.objects.update_or_create(
            name="Default",
            defaults={"priority": 9999, "is_enabled": True, "base_folder": os.path.join(self.tmp, "library"),
                      "folder_template": "{<publisher>}/{<series>}",
                      "file_template": "{<series>}{ #<number3>}", "exclude_rules": {}},
        )
        self.src = make_cbz(os.path.join(self.tmp, "untagged", "x.cbz"))
        self.audit_path = os.path.join(self.tmp, "logs", "batch_actions.jsonl")

    def _audit_errors(self):
        import json
        with open(self.audit_path) as f:
            entries = [json.loads(line) for line in f]
        return [e["changes"]["error"][1] for e in entries if e["action"] == "organize_error"]

    def _run(self, action, comic, error):
        from unittest.mock import patch
        from django.test import override_settings
        from apps.core import workflow
        with override_settings(AUDIT_LOG_PATH=self.audit_path), \
                patch("apps.organizer.services._safe_move", side_effect=error), \
                self.assertLogs("apps.organizer.services", "ERROR") as logs:
            result = getattr(workflow, action)(comic, force=True)
        self.assertFalse(result.success)
        self.assertIsNotNone(logs.records[0].exc_info)
        self.assertIn(self.src, logs.output[0])
        return result

    def test_failed_move_is_logged_with_the_reason(self):
        comic = Comic.objects.create(file_path=self.src, series="Sample Hero", number="1",
                                     publisher="Pub", state=Comic.STATE_ORGANIZED)
        result = self._run("organize", comic, PermissionError(13, "Permission denied", self.src))
        self.assertIn("Permission denied", result.error)
        self.assertEqual(len(self._audit_errors()), 1)
        self.assertIn("Permission denied", self._audit_errors()[0])
        self.assertTrue(os.path.exists(self.src))

    def test_failed_reorganize_is_logged_with_the_reason(self):
        comic = Comic.objects.create(file_path=self.src, series="Sample Hero", number="1",
                                     publisher="Pub", state=Comic.STATE_DONE)
        self._run("reorganize", comic, OSError(5, "Input/output error"))
        self.assertEqual(len(self._audit_errors()), 1)
        self.assertIn("Input/output error", self._audit_errors()[0])
        self.assertTrue(os.path.exists(self.src))

    def test_missing_file_is_logged(self):
        from django.test import override_settings
        from apps.core import workflow
        gone = os.path.join(self.tmp, "untagged", "gone.cbz")
        comic = Comic.objects.create(file_path=gone, series="Sample Hero", number="1",
                                     publisher="Pub", state=Comic.STATE_ORGANIZED)
        with override_settings(AUDIT_LOG_PATH=self.audit_path):
            result = workflow.organize(comic)
        self.assertFalse(result.success)
        self.assertEqual(self._audit_errors(), [f"File not found: {gone}"])


LOP = """<?xml version="1.0" encoding="utf-8"?>
<LibraryOrganizer>
  <Profile Name="01 - Marvel">
    <Mode>Move</Mode>
    <FolderTemplate>{&lt;publisher&gt;}/{&lt;series&gt;}</FolderTemplate>
    <FileTemplate>{&lt;series&gt;} #{&lt;number3&gt;}</FileTemplate>
    <BaseFolder>B:\\Comics\\ComicRack</BaseFolder>
  </Profile>
  <Profile Name="02 - Manga">
    <Mode>Move</Mode>
    <FolderTemplate>{&lt;series&gt;}</FolderTemplate>
    <FileTemplate>{&lt;series&gt;} #{&lt;number3&gt;}</FileTemplate>
    <BaseFolder>B:\\Comics\\ComicRack\\Manga\\Kids</BaseFolder>
  </Profile>
  <Profile Name="03 - Already here">
    <Mode>Move</Mode>
    <FolderTemplate>{&lt;series&gt;}</FolderTemplate>
    <FileTemplate>{&lt;series&gt;}</FileTemplate>
    <BaseFolder>/comics/library/Other</BaseFolder>
  </Profile>
  <Profile Name="04 - Template">
    <Mode>Simulate</Mode>
    <FolderTemplate>{&lt;series&gt;}</FolderTemplate>
    <FileTemplate>{&lt;series&gt;}</FileTemplate>
    <BaseFolder>D:\\Somewhere</BaseFolder>
  </Profile>
</LibraryOrganizer>
"""

COMICRACK = {"B:\\Comics\\ComicRack": {"prefix": "B:\\Comics\\ComicRack", "target": "/comics/library", "slashes": True},
             "B:\\Comics\\ComicRack\\Manga\\Kids": {"prefix": "B:\\Comics\\ComicRack", "target": "/comics/library",
                                                    "slashes": True}}


class MapBaseFolderTests(SimpleTestCase):
    """Base folders from ComicRack are mapped onto the library folder (P7.23)."""

    def test_whole_path_becomes_the_target(self):
        from apps.organizer.parser import map_base_folder
        self.assertEqual(map_base_folder("B:\\Comics\\ComicRack", "B:\\Comics\\ComicRack", "/comics/library"),
                         "/comics/library")

    def test_rest_of_the_path_is_kept_with_slashes(self):
        from apps.organizer.parser import map_base_folder
        self.assertEqual(map_base_folder("B:\\Comics\\ComicRack\\Manga\\Kids", "B:\\Comics\\ComicRack",
                                         "/comics/library/"), "/comics/library/Manga/Kids")

    def test_backslashes_kept_when_asked(self):
        from apps.organizer.parser import map_base_folder
        self.assertEqual(map_base_folder("B:\\Comics\\Manga\\Kids", "B:\\Comics", "/comics/library", slashes=False),
                         "/comics/library/Manga\\Kids")

    def test_other_os_paths(self):
        from apps.organizer.parser import map_base_folder
        self.assertEqual(map_base_folder("/Users/me/Comics/DC", "/Users/me/Comics", "/comics/library"),
                         "/comics/library/DC")

    def test_prefix_must_be_the_start(self):
        from apps.organizer.parser import map_base_folder
        with self.assertRaises(ValueError):
            map_base_folder("B:\\Comics", "D:\\Comics", "/comics/library")

    def test_inside_library(self):
        from apps.organizer.services import is_inside_library
        self.assertTrue(is_inside_library("/comics/library"))
        self.assertTrue(is_inside_library("/comics/library/Manga"))
        self.assertFalse(is_inside_library("/comics/library/../untagged"))
        self.assertFalse(is_inside_library("/comics/library2"))
        self.assertFalse(is_inside_library("B:\\Comics\\ComicRack"))
        self.assertFalse(is_inside_library(""))


class LopImportBaseFolderTests(TestCase):
    """A .lop import never keeps a base folder outside the library folder (P7.23)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.lop = os.path.join(self.tmp, "profiles.lop")
        with open(self.lop, "w", encoding="utf-8") as f:
            f.write(LOP)
        OrganizerProfile.objects.create(name="Mine", folder_template="{<series>}", file_template="{<series>}")
        self.before = sorted(OrganizerProfile.objects.values_list("name", flat=True))

    def test_windows_base_folder_without_replacement_imports_nothing(self):
        from apps.organizer.parser import BaseFolderError, import_profiles
        with self.assertRaises(BaseFolderError) as ctx:
            import_profiles(self.lop, clear_existing=True)
        self.assertIn("B:\\Comics\\ComicRack", str(ctx.exception))
        self.assertNotIn("D:\\Somewhere", str(ctx.exception))
        self.assertEqual(sorted(OrganizerProfile.objects.values_list("name", flat=True)), self.before)

    def test_replacement_maps_every_base_folder(self):
        from apps.organizer.parser import import_profiles
        result = import_profiles(self.lop, clear_existing=True, base_folder_map=COMICRACK)
        bases = dict(OrganizerProfile.objects.values_list("name", "base_folder"))
        self.assertEqual(bases, {"01 - Marvel": "/comics/library",
                                 "02 - Manga": "/comics/library/Manga/Kids",
                                 "03 - Already here": "/comics/library/Other"})
        self.assertEqual([c["profile"] for c in result["base_folders_changed"]], ["01 - Marvel", "02 - Manga"])

    def test_replacement_outside_the_library_imports_nothing(self):
        from apps.organizer.parser import BaseFolderError, import_profiles
        bad = dict(COMICRACK)
        bad["B:\\Comics\\ComicRack"] = {"prefix": "B:\\Comics\\ComicRack", "target": "/tmp", "slashes": True}
        with self.assertRaises(BaseFolderError):
            import_profiles(self.lop, clear_existing=True, base_folder_map=bad)
        self.assertEqual(sorted(OrganizerProfile.objects.values_list("name", flat=True)), self.before)

    def test_import_page(self):
        import json
        with open(self.lop, "rb") as f:
            resp = self.client.post("/organizer/import/", {"lop_file": f, "clear_existing": "on"}, follow=True)
        self.assertEqual(resp.redirect_chain[-1][0], "/organizer/import/")
        self.assertContains(resp, "Nothing was imported")
        self.assertTrue(OrganizerProfile.objects.filter(name="Mine").exists())

        with open(self.lop, "rb") as f:
            resp = self.client.post("/organizer/import/", {"lop_file": f, "clear_existing": "on",
                                                           "base_folder_map": json.dumps(COMICRACK)}, follow=True)
        self.assertContains(resp, "Base folder B:\\Comics\\ComicRack is now /comics/library (1 profile)")
        self.assertEqual(OrganizerProfile.objects.count(), 3)


class BaseFolderGuardTests(TestCase):
    """Moves are refused when a profile's base folder is outside the library folder (P7.24)."""

    def setUp(self):
        from django.test import override_settings
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.library = os.path.join(self.tmp, "library")
        self.enterContext(override_settings(LIBRARY_DIR=self.library,
                                            AUDIT_LOG_PATH=os.path.join(self.tmp, "logs", "batch_actions.jsonl")))
        self.profile, _ = OrganizerProfile.objects.update_or_create(
            name="Default",
            defaults={"priority": 9999, "is_enabled": True, "base_folder": "B:\\Comics\\ComicRack",
                      "folder_template": "{<publisher>}/{<series>}",
                      "file_template": "{<series>}{ #<number3>}", "exclude_rules": {}},
        )
        self.src = make_cbz(os.path.join(self.tmp, "untagged", "x.cbz"))

    def _comic(self, state=Comic.STATE_ORGANIZED, path=None):
        return Comic.objects.create(file_path=path or self.src, series="Sample Hero", number="1",
                                    publisher="Pub", state=state)

    def _assert_refused(self, result_error):
        self.assertIn("outside the library folder", result_error)
        self.assertTrue(os.path.exists(self.src))
        self.assertFalse(os.path.exists("B:\\Comics\\ComicRack"))

    def test_windows_base_folder_refused(self):
        from apps.core import workflow
        result = workflow.organize(self._comic())
        self.assertFalse(result.success)
        self._assert_refused(result.error)
        with open(os.path.join(self.tmp, "logs", "batch_actions.jsonl")) as f:
            self.assertIn("organize_error", f.read())

    def test_folder_outside_the_library_refused(self):
        from apps.organizer.services import organize_comic
        self.profile.base_folder = os.path.join(self.tmp, "elsewhere")
        self.profile.save()
        result = organize_comic(self._comic())
        self.assertFalse(result["success"])
        self._assert_refused(result["error"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "elsewhere")))

    def test_reorganize_refused(self):
        from apps.organizer.services import reorganize_comic
        result = reorganize_comic(self._comic(state=Comic.STATE_DONE))
        self.assertFalse(result["success"])
        self._assert_refused(result["error"])

    def test_move_buttons_answer_400(self):
        resp = self.client.post(f"/comics/{self._comic().pk}/force-organize/")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("outside the library folder", resp.json()["message"])
        done = self._comic(state=Comic.STATE_DONE, path=make_cbz(os.path.join(self.tmp, "untagged", "y.cbz")))
        resp = self.client.post(f"/organizer/path-audit/reorganize/{done.pk}/")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("outside the library folder", resp.json()["error"])
        self.assertTrue(os.path.exists(self.src))

    def test_folder_inside_the_library_moves(self):
        from apps.organizer.services import organize_comic
        self.profile.base_folder = os.path.join(self.library, "Comics")
        self.profile.save()
        comic = self._comic()
        result = organize_comic(comic)
        self.assertTrue(result["success"], result)
        self.assertEqual(comic.file_path, os.path.join(self.library, "Comics", "Pub", "Sample Hero",
                                                       "Sample Hero #001.cbz"))
        self.assertTrue(os.path.exists(comic.file_path))

    def test_profile_pages_warn(self):
        page = self.client.get("/organizer/profiles/")
        self.assertEqual(list(page.context["outside_library"]), [self.profile])
        self.assertContains(page, "outside the library folder")
        resp = self.client.post(f"/organizer/profiles/{self.profile.pk}/edit/",
                                {"name": "Default", "folder_template": "{<series>}", "file_template": "{<series>}",
                                 "base_folder": "D:\\Comics", "is_enabled": "on"}, follow=True)
        self.assertContains(resp, "Moves with this profile are refused")


class ReorganizeFlagTests(TestCase):
    """Done comics are flagged for re-organizing like the other library states (RE.8)."""

    def _comic(self, state):
        return Comic.objects.create(series="Sandman", number="1", publisher="DC Comics", state=state,
                                    medium=Comic.MEDIUM_DIGITAL, file_path=f"/comics/library/{state}.cbz")

    def test_metadata_change_flags_done_comics(self):
        flagged = [self._comic(state) for state in (Comic.STATE_ORGANIZED, Comic.STATE_WRITTEN, Comic.STATE_DONE)]
        not_in_library = self._comic("tagging")
        for comic in flagged + [not_in_library]:
            comic.publisher = "Vertigo"
            comic.save()
        flags = dict(Comic.objects.values_list("state", "needs_reorganize"))
        self.assertEqual(flags, {Comic.STATE_ORGANIZED: True, Comic.STATE_WRITTEN: True,
                                 Comic.STATE_DONE: True, "tagging": False})

    def test_profile_template_change_flags_done_comics(self):
        profile = OrganizerProfile.objects.create(name="Mine", folder_template="{<series>}", file_template="{<series>}")
        done = self._comic(Comic.STATE_DONE)
        profile.folder_template = "{<publisher>}/{<series>}"
        profile.save()
        done.refresh_from_db()
        self.assertTrue(done.needs_reorganize)


class PathFieldTests(TestCase):
    """A metadata change marks a library comic Needs Re-organize only when a profile's templates or match rules
    use that field, from any profile (RE.9)."""

    def _comic(self, name="a", **fields):
        return Comic.objects.create(series="Sandman", number="1", publisher="DC Comics", state=Comic.STATE_DONE,
                                    medium=Comic.MEDIUM_DIGITAL, file_path=f"/comics/library/{name}.cbz", **fields)

    def _marked_after(self, comic, **changes):
        for field, value in changes.items():
            setattr(comic, field, value)
        comic.save()
        comic.refresh_from_db()
        return comic.needs_reorganize

    def test_fields_from_templates_and_rules(self):
        from apps.organizer.services import path_fields
        OrganizerProfile.objects.create(
            name="Arcs", folder_template="{<publisher>}/{<storyarc>}",
            file_template="{<series>}{ #<number3>}{ - <writer[1][l]>}{ <Custom(Era)>}{ <altNumber2>}{ <Printing>}",
            exclude_rules={"operator": "All", "mode": "Only", "rules": [
                {"type": "rule", "field": "Format", "operator": "is", "value": "TPB"},
                {"type": "group", "operator": "Any", "rules": [
                    {"type": "rule", "field": "Custom(Line)", "operator": "is", "value": "Black Label"}]},
            ]})
        fields, custom = path_fields()
        self.assertLessEqual({"publisher", "story_arc", "series", "number", "writer", "format"}, fields)
        self.assertEqual(custom, {"Era", "AlternateNumber", "Printing", "Line"})
        # the Default profile's templates count too
        self.assertLessEqual({"volume", "year"}, fields)
        self.assertNotIn("imprint", fields)

    def test_disabled_profiles_dont_count(self):
        from apps.organizer.services import path_fields
        OrganizerProfile.objects.create(name="Off", is_enabled=False, folder_template="{<imprint>}",
                                        file_template="{<series>}")
        self.assertNotIn("imprint", path_fields()[0])

    def test_a_field_no_profile_uses_does_not_mark(self):
        self.assertFalse(self._marked_after(self._comic(), story_arc="Preludes and Nocturnes", imprint="Vertigo"))

    def test_a_field_a_profile_uses_marks(self):
        # number is in the Default profile's file name
        self.assertTrue(self._marked_after(self._comic("a"), number="2"))
        OrganizerProfile.objects.create(name="Arcs", folder_template="{<storyarc>}", file_template="{<series>}")
        self.assertTrue(self._marked_after(self._comic("b"), story_arc="Preludes and Nocturnes"))

    def test_a_custom_value_a_template_uses_marks(self):
        OrganizerProfile.objects.create(name="Era", folder_template="{<series>}", file_template="{<Custom(Era)>}")
        comic = self._comic(custom_values={"comicvine_issue": "1"})
        self.assertFalse(self._marked_after(comic, custom_values={"comicvine_issue": "2"}))
        self.assertTrue(self._marked_after(comic, custom_values={"comicvine_issue": "2", "Era": "Golden Age"}))

    def test_saves_that_cant_change_the_path_dont_read_the_profiles(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        done = self._comic("a")
        tagging = self._comic("b")
        Comic.objects.filter(pk=tagging.pk).update(state="tagging")
        tagging.refresh_from_db()
        with CaptureQueriesContext(connection) as ctx:
            done.flags = {"is_pdf": True}
            done.save(update_fields=["flags"])
            tagging.publisher = "Vertigo"
            tagging.save()
        self.assertFalse([q for q in ctx.captured_queries if "organizer_organizerprofile" in q["sql"]])
