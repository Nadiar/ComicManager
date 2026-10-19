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


class HashCacheTests(TestCase):
    """Cover hashes in comicvine.db may be stored as signed 64-bit integers (#8)."""

    HASH = 0xA4580F3A9C21B7E0  # top bit set: stored by SQLite as a negative number

    def _make_db(self, d, phash, ahash):
        import os
        import sqlite3

        path = os.path.join(d, "comicvine.db")
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE cv_publisher (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE cv_volume (id INTEGER PRIMARY KEY, name TEXT, start_year TEXT,
                                    count_of_issues INTEGER, publisher_id INTEGER);
            CREATE TABLE cv_issue (id INTEGER PRIMARY KEY, volume_id INTEGER, name TEXT,
                                   issue_number TEXT, cover_date TEXT, description TEXT,
                                   image_url TEXT);
            CREATE TABLE comic_covers (id INTEGER PRIMARY KEY, cvid INTEGER, cv_url TEXT,
                                       ct_phash INTEGER, ct_ahash INTEGER);
            INSERT INTO cv_publisher VALUES (1, 'Image');
            INSERT INTO cv_volume VALUES (139839, 'Gunslinger', '2021', 58, 1);
            INSERT INTO cv_issue VALUES (1188248, 139839, NULL, '57', '2026-08-19', NULL, NULL);
        """)
        conn.execute("INSERT INTO comic_covers VALUES (1, 1188248, 'https://example.com/57.jpg', ?, ?)",
                     (phash, ahash))
        conn.commit()
        conn.close()
        return path

    def test_negative_hash_matches_as_unsigned(self):
        import tempfile
        from apps.scraper.comicvine import ComicVineScraper

        signed = self.HASH - (1 << 64)
        self.assertLess(signed, 0)
        with tempfile.TemporaryDirectory() as d:
            scraper = ComicVineScraper(self._make_db(d, signed, signed))
            matches = scraper.match_by_hash_fast(self.HASH, self.HASH, max_distance=0)
            self.assertEqual([(m.issue_id, m.match_score) for m in matches], [(1188248, 0)])

    def test_unreadable_hash_gives_no_matches(self):
        import tempfile
        from apps.scraper.comicvine import ComicVineScraper

        with tempfile.TemporaryDirectory() as d:
            scraper = ComicVineScraper(self._make_db(d, "not a hash", "not a hash"))
            with self.assertLogs("apps.scraper.comicvine", level="ERROR"):
                self.assertEqual(scraper.match_by_hash_fast(self.HASH, self.HASH), [])


class ScrapePreviewErrorTests(TestCase):
    """A failing local lookup reaches the scrape modal as JSON, not an HTML error page (#8)."""

    def test_error_is_json_with_the_reason_and_the_comic(self):
        import sqlite3
        from unittest.mock import patch
        comic = Comic.objects.create(series="Black Cat", number="14", year=2026)
        with patch("apps.scraper.cv_sources.is_cv_db_available", return_value=True), \
                patch("apps.core.views.ComicVineScraper") as scraper, \
                self.assertLogs("apps.core.views", "ERROR") as logs:
            scraper.return_value.match_by_metadata.side_effect = sqlite3.OperationalError("no such table: cv_issue")
            resp = self.client.get(f"/comics/{comic.pk}/scrape/preview/?force=1")
        self.assertEqual(resp.status_code, 500)
        data = resp.json()
        self.assertFalse(data["success"])
        self.assertIn("no such table: cv_issue", data["error"])
        self.assertEqual(data["comic"]["series"], "Black Cat")
        self.assertEqual(data["comic"]["number"], "14")
        self.assertIsNotNone(logs.records[0].exc_info)
