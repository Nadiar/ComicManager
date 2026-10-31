"""
Stale Metadata: comics written before and changed since, in Write or Done, where writing them is the next step. The
dashboard's count, the comic list's filter, Write Stale's check and its task take the same comics (BUG.83).
"""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.core.models import Comic
from apps.core.tasks import _write_queue_qs


class StaleTests(TestCase):
    def _comic(self, name, state, changed=True):
        comic = Comic.objects.create(series="Saga", number=name, state=state, file_path=f"/comics/library/{name}.cbz")
        written = timezone.now() - timedelta(hours=1)
        Comic.objects.filter(pk=comic.pk).update(last_written=written,
                                                 updated_at=timezone.now() if changed else written)
        return comic

    def _stale_everywhere(self):
        """The stale comics' numbers as the dashboard, the list, Write Stale's check and its task see them."""
        with patch("apps.core.views.enqueue") as enqueue:
            enqueue.return_value.id = "queued"
            button = self.client.post("/comics/write-stale/").json()["total"]
        return {
            "dashboard": self.client.get("/").context["stale_count"],
            "list": sorted(c.number for c in self.client.get("/comics/?stale=1").context["comics"]),
            "button": button,
            "task": sorted(Comic.objects.filter(pk__in=_write_queue_qs("stale")).values_list("number", flat=True)),
        }

    def test_done_comics_changed_since_they_were_written(self):
        self._comic("1", Comic.STATE_DONE)
        self._comic("2", Comic.STATE_DONE, changed=False)
        self._comic("3", Comic.STATE_WRITTEN)
        self.assertEqual(self._stale_everywhere(), {"dashboard": 2, "list": ["1", "3"], "button": 2, "task": ["1", "3"]})

    def test_a_comic_sent_back_to_an_earlier_step_is_not_stale(self):
        """Write Stale would write it and set it to Done, skipping the steps in between."""
        self._comic("1", Comic.STATE_TAGGED)
        self._comic("2", Comic.STATE_ORGANIZED)
        self.assertEqual(self._stale_everywhere(), {"dashboard": 0, "list": [], "button": 0, "task": []})
