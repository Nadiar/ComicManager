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


class FakeComicVine:
    """Stands in for ComicVineScraper's API methods and counts the calls."""

    def __init__(self, volumes=(), issues=None, search=()):
        self.volumes = list(volumes)
        self.issues = issues or {}  # (volume_id, number) -> CVMatch
        self.search = list(search)
        self.calls = []

    def search_volumes_api(self, query, limit=10):
        self.calls.append(("volumes", query))
        return self.volumes

    def get_issue_by_volume_and_number(self, volume_id, issue_number):
        self.calls.append(("issues", volume_id))
        return self.issues.get((volume_id, issue_number))

    def search_api(self, query, limit=10, fetch_volume_info=False):
        self.calls.append(("search", query))
        return self.search

    def get_issue_from_api(self, issue_id):
        self.calls.append(("issue", issue_id))
        return _make_match(issue_id=issue_id, series="Details")


def _volume(volume_id, series, start_year, issue_count=50, publisher="DC Comics"):
    return _make_match(issue_id=0, volume_id=volume_id, series=series, issue_number="",
                       start_year=start_year, issue_count=issue_count, publisher=publisher)


def _issue(issue_id, volume_id, number, series="", start_year=None):
    return _make_match(issue_id=issue_id, volume_id=volume_id, series=series, issue_number=number,
                       start_year=start_year, cover_url=f"https://example.com/{issue_id}.jpg")


class ApiMatchTests(TestCase):
    """try_api_metadata_match tries more volumes, then the issue search, and says why it gave up."""

    def setUp(self):
        from unittest import mock
        Setting.objects.update_or_create(key="cv_api_key", defaults={"value": "key", "type": "text"})
        services._publisher_filter_cache["expires"] = 0.0
        self.budget = mock.patch("apps.scraper.cv_sources.check_api_budget", return_value=True)
        self.budget.start()
        self.addCleanup(self.budget.stop)
        # Covers in self.bad_covers do not match the comic's cover
        self.bad_covers = set()

        def verify(comic, match):
            if match.issue_id in self.bad_covers:
                comic.flags["scrape_error_detail"] = "cover hash mismatch (phash dist 30, ahash dist 28)"
                return False
            return True

        cover = mock.patch.object(services, "_verify_cover_hash", side_effect=verify)
        cover.start()
        self.addCleanup(cover.stop)

    def tearDown(self):
        services._publisher_filter_cache["expires"] = 0.0

    def _comic(self, series="Batman", number="100", year=2020):
        return Comic.objects.create(series=series, number=number, year=year, state=Comic.STATE_IMPORTED)

    def test_volumes_are_ranked_by_who_can_hold_the_issue(self):
        comic = self._comic()
        volumes = [
            _volume(1, "Batman", "1940", 713),
            _volume(2, "Batman", "2025", 10),
            _volume(3, "Batman Beyond", "1999"),
            _volume(4, "Batman", "2011", 52),
            _volume(5, "Batman", "2016", 160),
            _volume(6, "Superman", "2016"),
        ]
        ranked = services.rank_api_volumes(comic, volumes)
        # 2016 and 1940 have at least 100 issues; 2011 and Beyond have fewer;
        # 2025 started after the comic
        self.assertEqual([v.volume_id for v in ranked], [5, 1, 4, 3, 2])

    def test_reprints_with_few_issues_go_after_the_real_run(self):
        comic = self._comic(series="Saga", number="40", year=2016)
        volumes = [
            _volume(1, "Saga", "2013", 12, publisher="Cross Cult"),
            _volume(2, "Saga", "2012", 72, publisher="Image"),
            _volume(3, "Saga", "2013", 10, publisher="Urban Comics"),
        ]
        self.assertEqual([v.volume_id for v in services.rank_api_volumes(comic, volumes)], [2, 1, 3])

    def test_issue_in_the_second_volume_is_found(self):
        comic = self._comic(series="Star Wars", number="45", year=2018)
        cv = FakeComicVine(
            volumes=[_volume(1, "Star Wars", "1977", 107), _volume(2, "Star Wars", "2015", 75)],
            issues={(1, "45"): _issue(145, 1, "45")},
        )
        match = services.try_api_metadata_match(comic, cv)
        self.assertEqual(match.issue_id, 145)
        self.assertEqual(match.match_type, "api+volume+detail")
        self.assertEqual(cv.calls, [("volumes", "Star Wars"), ("issues", 2), ("issues", 1), ("issue", 145)])

    def test_cover_mismatch_moves_on_to_the_next_volume(self):
        comic = self._comic(number="1", year=2016)
        cv = FakeComicVine(
            volumes=[_volume(5, "Batman", "2016"), _volume(1, "Batman", "1940")],
            issues={(5, "1"): _issue(51, 5, "1"), (1, "1"): _issue(11, 1, "1")},
        )
        self.bad_covers.add(51)
        match = services.try_api_metadata_match(comic, cv)
        self.assertEqual(match.issue_id, 11)
        self.assertNotIn(("issue", 51), cv.calls)

    def test_at_most_three_volumes_are_looked_up(self):
        comic = self._comic(number="5", year=None)
        cv = FakeComicVine(volumes=[_volume(i, "Batman", str(1940 + i)) for i in range(1, 6)])
        services.try_api_metadata_match(comic, cv)
        self.assertEqual(len([c for c in cv.calls if c[0] == "issues"]), 3)

    def test_issue_search_finds_what_the_volumes_missed(self):
        comic = self._comic(series="Star Wars", number="45", year=2018)
        cv = FakeComicVine(
            volumes=[_volume(1, "Star Wars", "1977"), _volume(2, "Star Wars", "2015", publisher="Marvel")],
            search=[
                _issue(901, 2, "44", series="Star Wars", start_year="2018"),
                _issue(902, 3, "45", series="Star Wars Adventures", start_year="2018"),
                _issue(903, 2, "45", series="Star Wars", start_year="2018"),
            ],
        )
        match = services.try_api_metadata_match(comic, cv)
        self.assertEqual(match.issue_id, 903)
        self.assertEqual(match.match_type, "api+search+detail")
        self.assertIn(("search", "Star Wars 45"), cv.calls)

    def test_rejected_search_results_are_named_in_the_reason(self):
        comic = self._comic(series="Star Wars", number="45", year=2018)
        cv = FakeComicVine(
            volumes=[_volume(2, "Star Wars", "2015", publisher="Marvel")],
            search=[_issue(903, 2, "45", series="Star Wars", start_year="2018")],
        )
        self.bad_covers.add(903)
        self.assertIsNone(services.try_api_metadata_match(comic, cv))
        detail = comic.flags["scrape_error_detail"]
        self.assertIn("the cover does not match Star Wars #45 (cover hash mismatch", detail)
        self.assertNotIn("issue search", detail)

    def test_issue_search_respects_the_publisher_lists(self):
        Setting.objects.update_or_create(
            key="scrape_publisher_block", defaults={"value": "Panini", "type": "text"}
        )
        services._publisher_filter_cache["expires"] = 0.0
        comic = self._comic(series="Star Wars", number="45", year=2018)
        cv = FakeComicVine(
            volumes=[_volume(1, "Star Wars", "2015", publisher="Marvel"),
                     _volume(7, "Star Wars", "2015", publisher="Panini Comics")],
            search=[_issue(904, 7, "45", series="Star Wars", start_year="2018")],
        )
        self.assertIsNone(services.try_api_metadata_match(comic, cv))
        self.assertNotIn(("issue", 904), cv.calls)

    def test_gives_up_with_the_reason(self):
        comic = self._comic(number="5", year=2016)
        cv = FakeComicVine(
            volumes=[_volume(5, "Batman", "2016"), _volume(1, "Batman", "1940")],
            issues={(1, "5"): _issue(15, 1, "5")},
            search=[_issue(15, 1, "5", series="Batman")],
        )
        self.bad_covers.add(15)
        self.assertIsNone(services.try_api_metadata_match(comic, cv))
        detail = comic.flags["scrape_error_detail"]
        self.assertTrue(detail.startswith("ComicVine API: #5 is not in Batman (2016)"), detail)
        self.assertIn("the cover does not match Batman (1940) #5 (cover hash mismatch (phash dist 30", detail)
        self.assertIn('the issue search for "Batman 5" found no other issue', detail)
        self.assertEqual(len([c for c in cv.calls if c[0] == "issue"]), 0)

    def test_reason_without_api_key_or_budget(self):
        from unittest import mock
        comic = self._comic()
        Setting.objects.filter(key="cv_api_key").update(value="")
        self.assertIsNone(services.try_api_metadata_match(comic, FakeComicVine()))
        self.assertEqual(comic.flags["scrape_error_detail"], "ComicVine API: no API key is set in Settings")

        Setting.objects.filter(key="cv_api_key").update(value="key")
        with mock.patch("apps.scraper.cv_sources.check_api_budget", return_value=False):
            cv = FakeComicVine()
            self.assertIsNone(services.try_api_metadata_match(comic, cv))
        self.assertIn("200 calls per hour is used up", comic.flags["scrape_error_detail"])
        self.assertEqual(cv.calls, [])

    def test_no_volume_with_an_allowed_publisher(self):
        Setting.objects.update_or_create(
            key="scrape_publisher_allow", defaults={"value": "Marvel", "type": "text"}
        )
        services._publisher_filter_cache["expires"] = 0.0
        comic = self._comic()
        cv = FakeComicVine(volumes=[_volume(1, "Batman", "1940"), _volume(5, "Batman", "2016")])
        self.assertIsNone(services.try_api_metadata_match(comic, cv))
        self.assertIn("none of the 2 volumes found", comic.flags["scrape_error_detail"])

    def test_db_mode_says_when_api_fallback_is_off(self):
        from unittest import mock
        comic = self._comic()
        with mock.patch("apps.scraper.cv_sources.is_cv_db_available", return_value=True), \
                mock.patch.object(services, "try_hash_match", return_value=None), \
                mock.patch.object(services, "try_metadata_match", return_value=None):
            self.assertIsNone(services.find_best_match(comic, FakeComicVine(), max_distance=8))
        self.assertIn("API fallback is off", comic.flags["scrape_error_detail"])

    def test_scrape_message_and_audit_log_give_the_reason(self):
        from unittest import mock
        from apps.core import workflow
        comic = self._comic(number="5")
        with mock.patch("apps.scraper.cv_sources.is_cv_db_available", return_value=False), \
                mock.patch("apps.core.audit.log_batch_entry") as log:
            result = workflow.scrape(comic, scraper=FakeComicVine())
        self.assertFalse(result.success)
        self.assertEqual(result.message, 'No match found: ComicVine API: no volume found for "Batman"')
        self.assertEqual(log.call_args[0][4]["reason"][1], 'ComicVine API: no volume found for "Batman"')
        comic.refresh_from_db()
        self.assertTrue(comic.has_flag("scrape_no_match"))


class LocalMetadataMatchTests(TestCase):
    """Layer 2: closest year first, a matching cover wins, a far year needs a matching cover."""

    FAR = 0xFFFFFFFF00000000  # 32 bits away from a comic hashed as 0

    def setUp(self):
        import os
        import sqlite3
        import tempfile
        from apps.scraper.comicvine import ComicVineScraper

        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d)
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
            INSERT INTO cv_publisher VALUES (1, 'DC Comics');
            INSERT INTO cv_volume VALUES (1, 'Batman', '1940', 713, 1);
            INSERT INTO cv_volume VALUES (2, 'Batman', '2016', 160, 1);
            INSERT INTO cv_volume VALUES (3, 'Batman', '2011', 52, 1);
            INSERT INTO cv_volume VALUES (4, 'Batman and Robin', '2009', 26, 1);
            INSERT INTO cv_issue VALUES (1100, 1, NULL, '100', '1956-06-01', NULL, NULL);
            INSERT INTO cv_issue VALUES (2100, 2, NULL, '100', '2020-09-01', NULL, NULL);
            INSERT INTO cv_issue VALUES (1005, 1, NULL, '5', '1941-03-01', NULL, NULL);
            INSERT INTO cv_issue VALUES (2005, 2, NULL, '5', '2016-11-01', NULL, NULL);
            INSERT INTO cv_issue VALUES (3005, 3, NULL, '5', '2012-03-01', NULL, NULL);
            INSERT INTO cv_issue VALUES (1700, 1, NULL, '700', '2010-08-01', NULL, NULL);
            INSERT INTO cv_issue VALUES (4021, 4, NULL, '21', '2011-05-01', NULL, NULL);
        """)
        for n, cvid in enumerate((1100, 2100, 1005, 2005, 3005, 1700, 4021), start=1):
            conn.execute("INSERT INTO comic_covers VALUES (?, ?, '', ?, ?)",
                         (n, cvid, self.FAR - (1 << 64), self.FAR - (1 << 64)))
        conn.commit()
        conn.close()
        self.db = path
        self.scraper = ComicVineScraper(path)

    def _cover(self, cvid, phash, ahash):
        import sqlite3
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE comic_covers SET ct_phash=?, ct_ahash=? WHERE cvid=?", (phash, ahash, cvid))
        conn.commit()
        conn.close()
        import os, time
        os.utime(self.db, (time.time() + 5, time.time() + 5))  # the hash cache reloads on a new mtime

    def _comic(self, number, year=None, hashed=True, series="Batman"):
        return Comic.objects.create(series=series, number=number, year=year, state=Comic.STATE_IMPORTED,
                                    phash="0" * 16 if hashed else "", ahash="0" * 16 if hashed else "")

    def test_closest_year_first(self):
        ids = lambda year: [m.issue_id for m in self.scraper.match_by_metadata("batman", "100", year)]
        self.assertEqual(ids(2020), [2100, 1100])
        self.assertEqual(ids(2016), [2100, 1100])  # a filename year can be the volume's start year
        self.assertEqual(ids(None), [1100, 2100])  # no year: the volume with the most issues

    def test_close_year_is_taken_when_no_cover_matches(self):
        match = services.try_metadata_match(self._comic("100", 2020), self.scraper)
        self.assertEqual(match.issue_id, 2100)

    def test_matching_cover_wins_over_the_year(self):
        self._cover(3005, 3, 2)
        match = services.try_metadata_match(self._comic("5", 2016), self.scraper)
        self.assertEqual(match.issue_id, 3005)

    def test_far_year_without_a_matching_cover_is_refused(self):
        comic = self._comic("700", 2020)
        self.assertIsNone(services.try_metadata_match(comic, self.scraper))
        self.assertEqual(
            comic.flags["scrape_error_detail"],
            "local comicvine.db: the closest #700 is in Batman (1940) from 2010, the comic is from 2020, "
            "and none of their covers is close to the comic's",
        )

    def test_far_year_with_a_matching_cover_is_taken(self):
        self._cover(1700, 0, 0)
        self.assertEqual(services.try_metadata_match(self._comic("700", 2020), self.scraper).issue_id, 1700)

    def test_no_year_needs_a_single_volume(self):
        comic = self._comic("5", hashed=False)
        self.assertIsNone(services.try_metadata_match(comic, self.scraper))
        self.assertEqual(
            comic.flags["scrape_error_detail"],
            "local comicvine.db: 3 volumes have #5 and the comic has no year, and the comic has no cover to compare",
        )
        robin = self._comic("21", hashed=False, series="Batman and Robin")
        self.assertEqual(services.try_metadata_match(robin, self.scraper).issue_id, 4021)

    def test_no_volume_with_the_number(self):
        comic = self._comic("9999", 2020)
        self.assertIsNone(services.try_metadata_match(comic, self.scraper))
        self.assertEqual(comic.flags["scrape_error_detail"], 'local comicvine.db: no volume named "Batman" has #9999')

    def test_fallback_off_message_keeps_the_layer_2_reason(self):
        from unittest import mock
        comic = self._comic("700", 2020)
        with mock.patch("apps.scraper.cv_sources.is_cv_db_available", return_value=True), \
                mock.patch.object(services, "try_hash_match", return_value=None):
            self.assertIsNone(services.find_best_match(comic, self.scraper, max_distance=8))
        detail = comic.flags["scrape_error_detail"]
        self.assertTrue(detail.startswith("local comicvine.db: the closest #700"), detail)
        self.assertTrue(detail.endswith("; API fallback is off (Settings > Scraping)"), detail)

    def test_cover_hashes_come_from_the_cache(self):
        self._cover(2100, 5, 7)
        self.assertEqual(self.scraper.cover_hashes(2100), [(5, 7)])
        self.assertEqual(self.scraper.cover_hashes(424242), [])


class CoverRuleTests(TestCase):

    def test_sum_of_both_distances(self):
        self.assertTrue(services.covers_agree(16, 5))   # Guardians of the Galaxy #14 via the API
        self.assertTrue(services.covers_agree(14, 14))
        self.assertFalse(services.covers_agree(16, 13))
        self.assertFalse(services.covers_agree(24, 47))
