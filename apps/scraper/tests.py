"""Tests for scraper match-application logic."""

from django.test import TestCase

from apps.core.models import Comic
from apps.core.utils import generate_comicinfo_xml, parse_comicinfo_xml
from apps.scraper.comicvine import CVMatch
from apps.scraper.services import apply_cv_match


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
