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


class ReleaseDateSourceTests(TestCase):
    """scrape_date_source picks which ComicVine date sets year, month and day."""

    COVER = "2025-01-31"
    STORE = "2024-11-20"

    def _scrape(self, source, cover_date=COVER, store_date=STORE, save_store_date=False, comic=None):
        Setting.objects.update_or_create(
            key="scrape_date_source", defaults={"value": source, "type": "text"}
        )
        Setting.objects.update_or_create(
            key="scrape_save_store_date",
            defaults={"value": "true" if save_store_date else "false", "type": "bool"},
        )
        comic = comic or Comic.objects.create(series="Sample Hero", number="1", state="counted")
        apply_cv_match(comic, _make_match(cover_date=cover_date, store_date=store_date))
        return comic

    def _date(self, comic):
        return (comic.year, comic.month, comic.day)

    def test_cover_date(self):
        self.assertEqual(self._date(self._scrape("cover")), (2025, 1, 31))

    def test_store_date(self):
        self.assertEqual(self._date(self._scrape("store")), (2024, 11, 20))

    def test_earliest(self):
        self.assertEqual(self._date(self._scrape("earliest")), (2024, 11, 20))
        comic = self._scrape("earliest", cover_date="2024-11-01")
        self.assertEqual(self._date(comic), (2024, 11, 1))

    def test_latest(self):
        self.assertEqual(self._date(self._scrape("latest")), (2025, 1, 31))

    def test_missing_date_falls_back_to_the_other(self):
        self.assertEqual(self._date(self._scrape("store", store_date=None)), (2025, 1, 31))
        self.assertEqual(self._date(self._scrape("cover", cover_date=None)), (2024, 11, 20))
        self.assertEqual(self._date(self._scrape("earliest", store_date=None)), (2025, 1, 31))
        self.assertEqual(self._date(self._scrape("latest", cover_date=None)), (2024, 11, 20))

    def test_unset_setting_uses_cover_date(self):
        Setting.objects.filter(key="scrape_date_source").delete()
        comic = Comic.objects.create(series="Sample Hero", number="1", state="counted")
        apply_cv_match(comic, _make_match(cover_date=self.COVER, store_date=self.STORE))
        self.assertEqual(self._date(comic), (2025, 1, 31))

    def test_local_match_reads_store_date_from_db(self):
        from unittest.mock import patch
        with patch("apps.scraper.cv_sources.fetch_store_date", return_value=self.STORE) as fetch:
            comic = self._scrape("store", store_date=None)
        fetch.assert_called_once_with(1)
        self.assertEqual(self._date(comic), (2024, 11, 20))

    def test_cover_source_skips_db_lookup(self):
        from unittest.mock import patch
        with patch("apps.scraper.cv_sources.fetch_store_date") as fetch:
            self._scrape("cover", store_date=None)
        fetch.assert_not_called()

    def test_save_store_date_to_custom_values(self):
        comic = self._scrape("cover", save_store_date=True)
        self.assertEqual(comic.custom_values["StoreDate"], self.STORE)

        comic = self._scrape("cover", store_date=None, save_store_date=True, comic=comic)
        self.assertNotIn("StoreDate", comic.custom_values)

    def test_store_date_not_saved_when_off(self):
        comic = self._scrape("cover")
        self.assertNotIn("StoreDate", comic.custom_values)


class FetchStoreDateTests(TestCase):
    """fetch_store_date reads cv_issue.store_date from comicvine.db."""

    def _fetch(self, d, issue_id, columns="id INTEGER PRIMARY KEY, store_date TEXT", rows=()):
        import os
        import sqlite3
        from unittest.mock import patch
        from apps.scraper import cv_sources

        path = os.path.join(d, "comicvine.db")
        conn = sqlite3.connect(path)
        conn.execute(f"CREATE TABLE cv_issue ({columns})")
        conn.executemany("INSERT INTO cv_issue VALUES (?, ?)", rows)
        conn.commit()
        conn.close()
        with patch.object(cv_sources, "_get_cv_db_path", return_value=path):
            return cv_sources.fetch_store_date(issue_id)

    def test_returns_store_date(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self._fetch(d, 7, rows=[(7, "2024-11-20")]), "2024-11-20")

    def test_missing_issue_or_null(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(self._fetch(d, 8, rows=[(7, "2024-11-20"), (9, None)]))
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(self._fetch(d, 9, rows=[(9, None)]))

    def test_db_without_store_date_column(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(self._fetch(d, 7, columns="id INTEGER PRIMARY KEY, name TEXT", rows=[(7, "x")]))

    def test_no_db(self):
        from unittest.mock import patch
        from apps.scraper import cv_sources
        with patch.object(cv_sources, "_get_cv_db_path", return_value="/nonexistent/comicvine.db"):
            self.assertIsNone(cv_sources.fetch_store_date(7))


class IssueFromApiStoreDateTests(TestCase):
    def test_api_match_carries_store_date(self):
        from unittest.mock import patch
        from apps.scraper.comicvine import ComicVineScraper

        scraper = ComicVineScraper(db_path="/nonexistent/comicvine.db")
        data = {"results": {
            "id": 5, "volume": {"id": 3, "name": "Sample Hero"}, "issue_number": "1",
            "cover_date": "2025-01-31", "store_date": "2024-11-20",
        }}
        with patch.object(scraper, "_api_request", return_value=data) as req, \
             patch.object(scraper, "_get_volume_info", return_value={}):
            match = scraper.get_issue_from_api(5)

        self.assertIn("store_date", req.call_args[0][1]["field_list"].split(","))
        self.assertEqual(match.store_date, "2024-11-20")
