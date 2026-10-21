"""Tests for scraper match-application logic."""

from django.test import TestCase

from apps.core.models import Comic, Setting
from apps.core.utils import generate_comicinfo_xml, parse_comicinfo_xml
from apps.scraper.comicvine import CVMatch
from apps.scraper.services import (
    apply_cv_match,
    metadata_alignment_score,
    publisher_allowed,
)
from apps.scraper import services


def _make_match(**overrides) -> CVMatch:
    fields = dict(
        issue_id=1,
        volume_id=None,
        series="Fantastic Four",
        issue_number="1",
        title=None,
        cover_date=None,
        publisher=None,
        start_year=None,
        issue_count=None,
        description=None,
        image_url=None,
        cover_url=None,
    )
    fields.update(overrides)
    return CVMatch(**fields)


class PublisherFilterTests(TestCase):
    """Auto-match must respect the publisher allow/block lists."""

    def _set_lists(self, allow="", block=""):
        Setting.objects.update_or_create(
            key="scrape_publisher_allow", defaults={"value": allow, "type": "text"}
        )
        Setting.objects.update_or_create(
            key="scrape_publisher_block", defaults={"value": block, "type": "text"}
        )
        services._publisher_filter_cache["expires"] = 0.0

    def tearDown(self):
        services._publisher_filter_cache["expires"] = 0.0

    def test_empty_lists_allow_everything(self):
        self._set_lists()
        self.assertTrue(publisher_allowed("Panini Comics"))
        self.assertTrue(publisher_allowed(None))

    def test_block_list_matches_substring(self):
        self._set_lists(block="panini")
        self.assertFalse(publisher_allowed("Panini Comics"))
        self.assertFalse(publisher_allowed("Editorial Panini"))
        self.assertTrue(publisher_allowed("DC Comics"))

    def test_allow_list_rejects_everything_else(self):
        self._set_lists(allow="DC, Marvel")
        self.assertTrue(publisher_allowed("DC Comics"))
        self.assertTrue(publisher_allowed("Marvel"))
        self.assertFalse(publisher_allowed("Panini Comics"))

    def test_unknown_publisher_passes_both_lists(self):
        self._set_lists(allow="DC", block="panini")
        self.assertTrue(publisher_allowed(None))
        self.assertTrue(publisher_allowed(""))
        self.assertTrue(publisher_allowed("  "))

    def test_blocked_publisher_disqualifies_a_perfect_match(self):
        self._set_lists(block="panini")
        comic = Comic.objects.create(series="Batman", number="1", year=2011, state="counted")
        good = _make_match(series="Batman", issue_number="1", start_year=2011, publisher="DC Comics")
        bad = _make_match(series="Batman", issue_number="1", start_year=2011, publisher="Panini Comics")

        self.assertEqual(metadata_alignment_score(comic, good), 4)
        self.assertEqual(metadata_alignment_score(comic, bad), 0)


class ApplyCvMatchStoryArcTests(TestCase):
    """A ComicVine match's story arc data must persist onto the comic (BUG.61)."""

    def test_story_arcs_copied_onto_comic(self):
        comic = Comic.objects.create(series="S", number="1", state="counted")
        match = _make_match(story_arcs="Fantastic Four Battle of the Century")

        apply_cv_match(comic, match)

        self.assertEqual(comic.story_arc, "Fantastic Four Battle of the Century")

    def test_no_story_arcs_leaves_field_unset(self):
        comic = Comic.objects.create(series="S", number="1", state="counted")
        match = _make_match(story_arcs=None)

        apply_cv_match(comic, match)

        self.assertIsNone(comic.story_arc)

    def test_story_arc_round_trips_through_comicinfo_xml(self):
        comic = Comic.objects.create(
            series="S", number="1", state="counted", story_arc="Arc One, Arc Two"
        )

        xml = generate_comicinfo_xml(comic)

        self.assertIn("<StoryArc>Arc One, Arc Two</StoryArc>", xml)
        self.assertEqual(parse_comicinfo_xml(xml.encode())["story_arc"], "Arc One, Arc Two")


class SharedCacheTests(TestCase):
    """The API budget must be shared by the web and worker processes (Redis)."""

    def test_cache_backend_is_redis(self):
        from django.core.cache import caches
        from django.core.cache.backends.redis import RedisCache
        self.assertIsInstance(caches["default"], RedisCache)

    def test_budget_counter_is_visible_to_another_connection(self):
        from django.core.cache.backends.redis import RedisCache
        from django.conf import settings
        from apps.scraper import cv_sources
        from django.core.cache import cache

        cache.delete(cv_sources.CV_API_BUDGET_KEY)
        self.addCleanup(cache.delete, cv_sources.CV_API_BUDGET_KEY)
        cv_sources.increment_api_call_count(3)
        other = RedisCache(settings.CACHES["default"]["LOCATION"], {})
        self.assertEqual(other.get(cv_sources.CV_API_BUDGET_KEY), 3)


class MclIndexTests(TestCase):

    def test_index_reloads_when_file_changes(self):
        import os
        import tempfile
        from unittest.mock import patch
        from apps.scraper import cv_sources

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "latest.mcl")
            with open(path, "w") as f:
                f.write("7205;51379,75503;24,1\n")
            with patch.object(cv_sources, "_get_mcl_path", return_value=path):
                first = cv_sources.load_mcl_index()
                self.assertIs(cv_sources.load_mcl_index(), first)
                self.assertEqual(first["7205"][1], {"issue_id": "75503", "number": "1"})
                with open(path, "w") as f:
                    f.write("7205;51379,75503,75504;24,1,2\n9;1;1\n")
                os.utime(path, ns=(1, 1))
                second = cv_sources.load_mcl_index()
                self.assertEqual(len(second["7205"]), 3)
                self.assertIn("9", second)


class SharedPacingTests(TestCase):
    """ComicVine requests from any process are spaced by the shared Redis slot."""

    def setUp(self):
        from apps.scraper import cv_sources
        cv_sources._redis().delete(cv_sources.CV_API_SLOT_KEY)

    def test_second_request_waits_for_the_slot(self):
        import time
        from unittest.mock import patch
        from apps.scraper import cv_sources
        with patch.object(cv_sources, "CV_API_MIN_INTERVAL_MS", 300):
            start = time.monotonic()
            self.assertTrue(cv_sources.wait_for_api_slot())
            first = time.monotonic() - start
            self.assertTrue(cv_sources.wait_for_api_slot())
            second = time.monotonic() - start
        self.assertLess(first, 0.1)
        self.assertGreaterEqual(second, 0.28)

    def test_slot_is_shared_with_another_connection(self):
        import redis
        from django.conf import settings
        from apps.scraper import cv_sources
        other = redis.from_url(settings.CACHES["default"]["LOCATION"])
        self.assertTrue(cv_sources.wait_for_api_slot())
        self.assertFalse(other.set(cv_sources.CV_API_SLOT_KEY, "1", nx=True, px=1100))

    def test_falls_back_when_redis_is_down(self):
        from unittest.mock import patch
        from apps.scraper import cv_sources
        with patch.object(cv_sources, "_redis", side_effect=ConnectionError("down")):
            self.assertFalse(cv_sources.wait_for_api_slot())


def _set_setting(key, value, type_="bool"):
    Setting.objects.update_or_create(key=key, defaults={"value": value, "type": type_})


def _make_inducks_match(**overrides):
    from apps.scraper.inducks import InducksMatch
    fields = dict(
        issuecode="xx/SA 1", publicationcode="xx/SA", series="Sample Anthology",
        issue_number="1", title=None, cover_date=None, publisher=None, start_year=None,
    )
    fields.update(overrides)
    return InducksMatch(**fields)


class KeepPublisherNameTests(TestCase):
    """scrape_keep_publisher: keep the comic's own publisher name on scrape."""

    def test_default_replaces_publisher_with_comicvine_name(self):
        comic = Comic.objects.create(series="S", number="1", state="counted", publisher="Sample")
        apply_cv_match(comic, _make_match(publisher="Sample Comics"))
        self.assertEqual(comic.publisher, "Sample Comics")

    def test_setting_on_keeps_existing_publisher(self):
        _set_setting("scrape_keep_publisher", "true")
        comic = Comic.objects.create(series="S", number="1", state="counted", publisher="Sample")
        apply_cv_match(comic, _make_match(publisher="Sample Comics"))
        self.assertEqual(comic.publisher, "Sample")

    def test_setting_on_still_fills_an_empty_publisher(self):
        _set_setting("scrape_keep_publisher", "true")
        comic = Comic.objects.create(series="S", number="1", state="counted")
        apply_cv_match(comic, _make_match(publisher="Sample Comics"))
        self.assertEqual(comic.publisher, "Sample Comics")

    def test_inducks_match_respects_the_setting(self):
        from apps.scraper.services import apply_inducks_match
        _set_setting("scrape_keep_publisher", "true")
        comic = Comic.objects.create(series="S", number="1", state="counted", publisher="Sample")
        apply_inducks_match(comic, _make_inducks_match(publisher="Sample Publishing"))
        self.assertEqual(comic.publisher, "Sample")

    def test_setting_is_seeded_off(self):
        from apps.core.models import get_setting
        self.assertIs(get_setting("scrape_keep_publisher"), False)


class UnknownPublisherFlagSettingTests(TestCase):
    """flag_unknown_publisher: the unknown_publisher flag is optional (on by default)."""

    def _scrape(self, known):
        from unittest.mock import patch
        comic = Comic.objects.create(series="S", number="1", state="counted")
        with patch("apps.tagging.engine.is_publisher_known", return_value=known):
            apply_cv_match(comic, _make_match(publisher="Small Sample Press"))
        return comic

    def test_default_flags_unknown_publisher(self):
        self.assertIn("unknown_publisher", self._scrape(known=False).flags)

    def test_known_publisher_is_not_flagged(self):
        self.assertNotIn("unknown_publisher", self._scrape(known=True).flags)

    def test_setting_off_never_flags(self):
        _set_setting("flag_unknown_publisher", "false")
        self.assertNotIn("unknown_publisher", self._scrape(known=False).flags)

    def test_setting_off_clears_an_existing_flag(self):
        from unittest.mock import patch
        _set_setting("flag_unknown_publisher", "false")
        comic = Comic.objects.create(series="S", number="1", state="counted")
        comic.add_flag("unknown_publisher")
        with patch("apps.tagging.engine.is_publisher_known", return_value=False):
            apply_cv_match(comic, _make_match(publisher="Small Sample Press"))
        self.assertNotIn("unknown_publisher", comic.flags)

    def test_setting_is_seeded_on(self):
        from apps.core.models import get_setting
        self.assertIs(get_setting("flag_unknown_publisher"), True)
