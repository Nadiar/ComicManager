"""Tests for the Library Organizer template engine and move safety."""

import os
import tempfile

from django.test import SimpleTestCase
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

