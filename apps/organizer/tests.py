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
