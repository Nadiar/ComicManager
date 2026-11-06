"""
Tests for the redesigned dashboard:
- Bottleneck derivation
- Time-of-day greeting
- UserPreference persistence for new dashboard fields
- 14-day weekly aggregation
"""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, Client, override_settings
from django.utils import timezone

from apps.core.models import Comic, UserPreference
from apps.dashboard.helpers import (
    get_bottleneck,
    get_greeting,
    get_week_history,
)


# ── Greeting tests ────────────────────────────────────────────────────────────

class GreetingTests(TestCase):
    def _greeting_at(self, hour):
        fake_now = timezone.now().replace(hour=hour, minute=0, second=0)
        with patch("apps.dashboard.helpers.timezone") as mock_tz:
            mock_tz.localtime.return_value = fake_now
            return get_greeting()

    def test_late_night_before_5(self):
        self.assertEqual(self._greeting_at(3), "Late night")

    def test_good_morning(self):
        self.assertEqual(self._greeting_at(9), "Good morning")

    def test_good_afternoon(self):
        self.assertEqual(self._greeting_at(14), "Good afternoon")

    def test_good_evening(self):
        self.assertEqual(self._greeting_at(19), "Good evening")

    def test_late_night_after_22(self):
        self.assertEqual(self._greeting_at(23), "Late night")

    def test_boundary_midnight(self):
        self.assertEqual(self._greeting_at(0), "Late night")

    def test_boundary_noon(self):
        self.assertEqual(self._greeting_at(12), "Good afternoon")

    def test_boundary_5am(self):
        self.assertEqual(self._greeting_at(5), "Good morning")


# ── Bottleneck tests ──────────────────────────────────────────────────────────

class BottleneckTests(TestCase):
    def _make_pipeline(self, counts):
        states = ["new", "scrape", "tagging", "formats", "deduplicate", "move", "write", "done"]
        return [{"state": s, "count": counts.get(s, 0), "title": s.capitalize(), "action": "Run"} for s in states]

    def test_first_non_zero_non_done_is_bottleneck(self):
        pipeline = self._make_pipeline({"new": 0, "scrape": 16, "done": 100})
        bn = get_bottleneck(pipeline)
        self.assertIsNotNone(bn)
        self.assertEqual(bn["state"], "scrape")

    def test_new_stage_is_bottleneck_if_first(self):
        pipeline = self._make_pipeline({"new": 50, "scrape": 10, "done": 0})
        bn = get_bottleneck(pipeline)
        self.assertEqual(bn["state"], "new")

    def test_done_stage_never_bottleneck(self):
        pipeline = self._make_pipeline({"new": 0, "scrape": 0, "done": 42914})
        bn = get_bottleneck(pipeline)
        self.assertIsNone(bn)

    def test_all_zero_returns_none(self):
        pipeline = self._make_pipeline({})
        bn = get_bottleneck(pipeline)
        self.assertIsNone(bn)

    def test_skips_zero_stages(self):
        pipeline = self._make_pipeline({"new": 0, "scrape": 0, "tagging": 0, "deduplicate": 5})
        bn = get_bottleneck(pipeline)
        self.assertEqual(bn["state"], "deduplicate")


# ── Preference persistence tests ──────────────────────────────────────────────

@override_settings(ALLOWED_HOSTS=["*"])
class PreferencePersistenceTests(TestCase):
    def setUp(self):
        self.client = Client(SERVER_NAME="localhost")
        UserPreference.objects.filter(pk=1).delete()
        self.prefs = UserPreference.get()

    def test_default_hero_style_is_editorial(self):
        self.assertEqual(self.prefs.dashboard_hero_style, "editorial")

    def test_default_attention_style_is_list(self):
        self.assertEqual(self.prefs.dashboard_attention_style, "list")

    def test_default_toggles_are_true(self):
        self.assertTrue(self.prefs.dashboard_show_weekly_card)
        self.assertTrue(self.prefs.dashboard_show_priority_banner)

    def test_settings_dashboard_post_saves_hero_style(self):
        resp = self.client.post(
            "/settings/dashboard/",
            {"dashboard_hero_style": "bold",
             "dashboard_attention_style": "triage",
             "dashboard_show_weekly_card": "on",
             "dashboard_show_priority_banner": "on"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp.status_code, 200)
        updated = UserPreference.get()
        self.assertEqual(updated.dashboard_hero_style, "bold")

    def test_settings_dashboard_post_toggles_off(self):
        resp = self.client.post(
            "/settings/dashboard/",
            {"dashboard_hero_style": "subtle",
             "dashboard_attention_style": "triage"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp.status_code, 200)
        updated = UserPreference.get()
        self.assertFalse(updated.dashboard_show_weekly_card)
        self.assertFalse(updated.dashboard_show_priority_banner)
        self.assertEqual(updated.dashboard_attention_style, "triage")

    def test_dashboard_renders_all_hero_variants(self):
        for hero in ("editorial", "subtle", "bold"):
            self.prefs.dashboard_hero_style = hero
            self.prefs.save()
            resp = self.client.get("/")
            self.assertEqual(resp.status_code, 200, f"Hero variant '{hero}' failed")

    def test_dashboard_renders_all_attention_variants(self):
        for att in ("list", "triage", "grid"):
            self.prefs.dashboard_attention_style = att
            self.prefs.save()
            resp = self.client.get("/")
            self.assertEqual(resp.status_code, 200, f"Attention variant '{att}' failed")

    def test_dashboard_renders_with_all_toggles_off(self):
        self.prefs.dashboard_show_weekly_card = False
        self.prefs.dashboard_show_priority_banner = False
        self.prefs.save()
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)


# ── Weekly aggregation tests ──────────────────────────────────────────────────

class WeeklyAggregationTests(TestCase):
    def _create_done_comic(self, days_ago):
        written_at = timezone.now() - timedelta(days=days_ago)
        Comic.objects.create(
            state=Comic.STATE_DONE,
            last_written=written_at,
        )

    def test_week_history_has_14_entries(self):
        history = get_week_history()
        self.assertEqual(len(history), 14)

    def test_week_history_empty_when_no_comics(self):
        Comic.objects.all().delete()
        history = get_week_history()
        self.assertEqual(sum(history), 0)

    def test_recent_comic_appears_in_last_7_bars(self):
        Comic.objects.all().delete()
        self._create_done_comic(days_ago=0)  # today
        history = get_week_history()
        self.assertEqual(history[13], 1)  # last bar = today

    def test_8_days_ago_appears_in_first_7_bars(self):
        Comic.objects.all().delete()
        self._create_done_comic(days_ago=8)
        history = get_week_history()
        self.assertEqual(history[5], 1)  # 13 - 8 = index 5

    def test_too_old_comic_not_counted(self):
        Comic.objects.all().delete()
        Comic.objects.create(
            state=Comic.STATE_DONE,
            last_written=timezone.now() - timedelta(days=15),
        )
        history = get_week_history()
        self.assertEqual(sum(history), 0)

    def test_this_week_vs_last_week_totals(self):
        Comic.objects.all().delete()
        for d in [0, 1, 3]:
            self._create_done_comic(days_ago=d)
        self._create_done_comic(days_ago=9)
        history = get_week_history()
        this_week = sum(history[7:])
        last_week = sum(history[:7])
        self.assertEqual(this_week, 3)
        self.assertEqual(last_week, 1)


class NestedSmartListGroupTests(TestCase):
    """Gitea #3: groups inside groups, e.g. (A and B) or (C and D)."""

    FILTERS = [{"mode": "or", "filters": [
        {"mode": "and", "filters": [
            {"field": "series", "lookup": "exact", "value": "Hulk"},
            {"field": "publisher", "lookup": "exact", "value": "Marvel"},
        ]},
        {"mode": "and", "filters": [
            {"field": "series", "lookup": "exact", "value": "Thor"},
            {"field": "publisher", "lookup": "exact", "value": "DC Comics"},
        ]},
    ]}]

    def test_query_matches_either_and_group(self):
        from apps.dashboard.models import SmartList
        from apps.dashboard.services import build_queryset
        hulk = Comic.objects.create(series="Hulk", publisher="Marvel", number="1")
        Comic.objects.create(series="Hulk", publisher="DC Comics", number="1")
        thor = Comic.objects.create(series="Thor", publisher="DC Comics", number="1")
        Comic.objects.create(series="Thor", publisher="Marvel", number="1")
        sl = SmartList.objects.create(name="nested", filters=self.FILTERS)
        self.assertEqual(set(build_queryset(sl).values_list("pk", flat=True)), {hulk.pk, thor.pk})

    def test_form_saves_nested_groups_unchanged(self):
        import json
        from apps.dashboard.models import SmartList
        resp = self.client.post("/smartlists/create/", {"name": "nested", "filters_json": json.dumps(self.FILTERS)})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(SmartList.objects.get(name="nested").filters, self.FILTERS)
        edit = self.client.get(f"/smartlists/{SmartList.objects.get(name='nested').pk}/edit/")
        self.assertContains(edit, "MAX_GROUP_DEPTH")
        self.assertContains(edit, 'id="existing-filters"')


class CblReadingListImportTests(TestCase):
    """CBL reading lists name their issues in <Books> instead of <Matchers>."""

    READING_LIST = b"""<?xml version="1.0" encoding="utf-8"?>
<ReadingList>
  <Name>Sample Event</Name>
  <Books>
    <Book Series="Sample Hero" Number="1" Volume="2001" Year="2001">
      <Database Name="cv" Series="9001" Issue="90011" />
    </Book>
    <Book Series="Sample Sidekick" Number="2" Volume="2002" Year="2002">
      <Database Name="cv" Series="9002" Issue="90022" />
    </Book>
    <Book Series="Sample Villain" Number="3" Volume="2003" Year="2003" />
  </Books>
</ReadingList>"""

    def test_parse_cbl_with_books_matches_each_book(self):
        from apps.dashboard.views import _parse_cbl
        name, filters, warnings = _parse_cbl(self.READING_LIST)
        self.assertEqual(name, "Sample Event")
        self.assertEqual(filters, [{"mode": "or", "filters": [
            {"field": "custom_values__comicvine_issue", "lookup": "in", "value": "90011,90022"},
            {"mode": "and", "filters": [
                {"field": "series", "lookup": "exact", "value": "Sample Villain"},
                {"field": "number", "lookup": "exact", "value": "3"},
                {"field": "volume", "lookup": "exact", "value": "2003"},
            ]},
        ]}])
        self.assertEqual(warnings, [])

    def test_parse_cbl_ignores_other_databases(self):
        from apps.dashboard.views import _parse_cbl
        xml = b"""<ReadingList><Name>Other DB</Name><Books>
            <Book Series="Sample Hero" Number="4"><Database Name="other" Issue="123" /></Book>
        </Books></ReadingList>"""
        _, filters, _ = _parse_cbl(xml)
        self.assertEqual(filters, [{"mode": "or", "filters": [
            {"mode": "and", "filters": [
                {"field": "series", "lookup": "exact", "value": "Sample Hero"},
                {"field": "number", "lookup": "exact", "value": "4"},
            ]},
        ]}])

    def test_parse_cbl_prefers_matchers_over_books(self):
        from apps.dashboard.views import _parse_cbl
        xml = b"""<ReadingList xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><Name>Both</Name>
          <Books><Book Series="Sample Hero" Number="1" /></Books>
          <Matchers>
            <ComicBookMatcher xsi:type="ComicBookSeriesMatcher"><MatchValue>Sample Hero</MatchValue></ComicBookMatcher>
          </Matchers>
        </ReadingList>"""
        _, filters, warnings = _parse_cbl(xml)
        self.assertEqual(filters, [{"field": "series", "lookup": "exact", "value": "Sample Hero"}])
        self.assertTrue(any("1 book" in w for w in warnings), warnings)

    def test_parse_cbl_without_rules_or_books_raises(self):
        from apps.dashboard.views import _parse_cbl
        with self.assertRaises(ValueError):
            _parse_cbl(b"<ReadingList><Name>Empty</Name><Books /></ReadingList>")

    def test_import_without_rules_or_books_creates_no_list(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.dashboard.models import SmartList
        upload = SimpleUploadedFile("empty.cbl", b"<ReadingList><Name>Empty</Name></ReadingList>")
        resp = self.client.post("/smartlists/import-cbl/", {"cbl_file": upload})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(SmartList.objects.exists())

    def test_import_reading_list_creates_list_with_book_rules(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.dashboard.models import SmartList
        upload = SimpleUploadedFile("event.cbl", self.READING_LIST)
        resp = self.client.post("/smartlists/import-cbl/", {"cbl_file": upload})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(SmartList.objects.get(name="Sample Event").filters[0]["filters"]), 2)

    def test_book_rules_select_the_listed_comics(self):
        from apps.dashboard.services import _build_filter_q
        from apps.dashboard.views import _parse_cbl
        by_id = Comic.objects.create(series="Sample Hero", number="1", custom_values={"comicvine_issue": "90011"})
        by_name = Comic.objects.create(series="Sample Villain", number="3", volume=2003)
        Comic.objects.create(series="Sample Villain", number="3", volume=2004)
        _, filters, _ = _parse_cbl(self.READING_LIST)
        matched = Comic.objects.filter(_build_filter_q(filters)).values_list("pk", flat=True)
        self.assertEqual(set(matched), {by_id.pk, by_name.pk})

    def test_parse_cbl_warns_about_books_it_cannot_match(self):
        from apps.dashboard.views import _parse_cbl
        xml = b"""<ReadingList><Name>Partial</Name><Books>
            <Book Series="Sample Hero" Number="1" /><Book Number="2" />
        </Books></ReadingList>"""
        _, filters, warnings = _parse_cbl(xml)
        self.assertEqual(len(filters[0]["filters"]), 1)
        self.assertTrue(any("1 book" in w for w in warnings), warnings)

    def test_in_lookup_accepts_spaces_after_commas(self):
        from apps.dashboard.services import _build_filter_q
        listed = Comic.objects.create(series="Sample Hero", number="1", custom_values={"comicvine_issue": "90022"})
        Comic.objects.create(series="Sample Hero", number="2", custom_values={"comicvine_issue": "90033"})
        rule = [{"field": "custom_values__comicvine_issue", "lookup": "in", "value": "90011, 90022"}]
        self.assertEqual(list(Comic.objects.filter(_build_filter_q(rule)).values_list("pk", flat=True)), [listed.pk])


class ReadingListMissingIssuesTests(TestCase):
    """Smart lists with a "CV Issue ID is one of" rule list their missing issues in rule order."""

    FILTERS = [{"mode": "or", "filters": [
        {"field": "custom_values__comicvine_issue", "lookup": "in", "value": "90033, 90011,90022"},
        {"mode": "and", "filters": [{"field": "series", "lookup": "exact", "value": "Sample Villain"}]},
    ]}]

    def setUp(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cv_db = str(Path(tmp.name) / "comicvine.db")
        conn = sqlite3.connect(self.cv_db)
        conn.executescript("""
            CREATE TABLE cv_publisher (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE cv_volume (id INTEGER PRIMARY KEY, name TEXT, start_year INTEGER, publisher_id INTEGER);
            CREATE TABLE cv_issue (id INTEGER PRIMARY KEY, volume_id INTEGER, issue_number TEXT, name TEXT,
                                   cover_date TEXT, image_url TEXT, site_detail_url TEXT);
            INSERT INTO cv_volume VALUES (9001, 'Sample Hero', 2001, NULL);
            INSERT INTO cv_issue VALUES (90011, 9001, '1', 'First Steps', '2001-01-01', NULL, 'https://cv.example/90011');
            INSERT INTO cv_issue VALUES (90022, 9001, '2', 'Second Wind', '2001-02-01', NULL, 'https://cv.example/90022');
        """)
        conn.commit()
        conn.close()

    def _list(self):
        from apps.dashboard.models import SmartList
        return SmartList.objects.create(name="Sample Event", filters=self.FILTERS)

    def test_reading_list_issue_ids_come_from_the_in_rule_in_order(self):
        sl = self._list()
        self.assertEqual(sl.reading_list_issue_ids, ["90033", "90011", "90022"])
        self.assertTrue(sl.has_missing_issues)

    def test_list_without_in_rule_has_no_missing_issues(self):
        from apps.dashboard.models import SmartList
        sl = SmartList.objects.create(name="plain", filters=[{"field": "series", "lookup": "exact", "value": "x"}])
        self.assertEqual(sl.reading_list_issue_ids, [])
        self.assertFalse(sl.has_missing_issues)

    def test_completion_keeps_list_order_and_marks_owned(self):
        from apps.dashboard.services import get_missing_issues
        owned = Comic.objects.create(series="Sample Hero", number="2", custom_values={"comicvine_issue": "90022"})
        with override_settings(CV_DB_PATH=self.cv_db):
            data = get_missing_issues(self._list())
        self.assertEqual([i["issue_id"] for i in data["all_issues"]], [90033, 90011, 90022])
        self.assertEqual((data["owned_count"], data["missing_count"], data["total_count"]), (1, 2, 3))
        self.assertEqual(data["completion"], 33.3)
        known = data["all_issues"][1]
        self.assertEqual((known["series"], known["issue_number"], known["title"]), ("Sample Hero (2001)", "1", "First Steps"))
        self.assertEqual(data["all_issues"][2]["comic_pk"], owned.pk)
        unknown = data["all_issues"][0]
        self.assertIsNone(unknown["issue_number"])
        self.assertEqual(unknown["site_detail_url"], "https://comicvine.gamespot.com/issue/4000-90033/")

    def test_completion_without_cv_db_still_lists_ids(self):
        from apps.dashboard.services import get_missing_issues
        with override_settings(CV_DB_PATH=self.cv_db + ".absent"):
            data = get_missing_issues(self._list())
        self.assertEqual(data["total_count"], 3)
        self.assertEqual(data["missing_count"], 3)

    def test_missing_page_and_index_offer_it(self):
        sl = self._list()
        with override_settings(CV_DB_PATH=self.cv_db):
            page = self.client.get(f"/smartlists/{sl.pk}/missing/")
            index = self.client.get("/smartlists/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Second Wind")
        self.assertContains(page, "4000-90033")
        self.assertContains(index, f"/smartlists/{sl.pk}/missing/")
