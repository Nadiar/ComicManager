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
