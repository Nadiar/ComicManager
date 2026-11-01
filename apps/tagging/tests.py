"""Tests for the tagging rule engine."""

from django.test import SimpleTestCase, TestCase

from apps.core.models import Comic
from apps.tagging import engine


class DotNetRegexTests(TestCase):
    """ComicRack rules use .NET regex: named groups convert, lookbehinds stay (P4.17)."""

    def _comic(self, notes):
        return Comic.objects.create(series="Star Wars", number="1", notes=notes)

    def test_named_group_with_a_lookbehind(self):
        comic = self._comic("Batman #12 (2020)")
        engine.action_regex_var_replace(comic, "Notes", r"(?<=#)(?<num>\d+)")
        self.assertEqual(comic.notes, "12")

    def test_negative_lookbehind_and_append(self):
        comic = self._comic("Era: Old Republic")
        engine.action_regex_var_append(comic, "Notes", r"(?<!New )(?<era>Republic)")
        self.assertEqual(comic.notes, "Era: Old Republic, Republic")


class DotNetRegexConditionTests(SimpleTestCase):

    def test_conditions_accept_named_groups_and_lookbehinds(self):
        self.assertTrue(engine.match_regex("Star Wars: Legacy", r"(?<sw>Star Wars)"))
        self.assertTrue(engine.match_regex("Vol. 2", r"(?<=Vol\. )\d"))
        self.assertFalse(engine.match_not_regex("Vol. 2", r"(?<!x)Vol"))

    def test_conversion_only_touches_named_groups(self):
        self.assertEqual(engine._python_regex(r"(?<a>x)(?<=y)(?<!z)(?P<b>w)"), r"(?P<a>x)(?<=y)(?<!z)(?P<b>w)")
