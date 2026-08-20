"""Duplicate detection: who is compared with whom, and how groups are formed."""

from django.test import TestCase

from apps.core.models import Comic
from apps.duplicates.models import DuplicateGroup
from apps.duplicates.services import resolve_keep_all, run_duplicate_detection_for_comics


class DetectionPoolTests(TestCase):

    def _comic(self, n, state=Comic.STATE_DONE, **kw):
        defaults = dict(series="Sample Hero", number=str(n), file_path=f"/comics/library/{n}-{kw.get('phash', '')}.cbz",
                        state=state, file_format="cbz")
        defaults.update(kw)
        return Comic.objects.create(**defaults)

    def test_new_comic_matching_a_previously_kept_comic_is_found(self):
        kept = self._comic(1, custom_values={"comicvine_issue": "100"})
        other = self._comic(1, custom_values={"comicvine_issue": "100"}, file_path="/comics/library/b.cbz")
        # First pair resolved as intentional: both keep their group link
        group = DuplicateGroup.objects.create(detection_method=DuplicateGroup.DETECTION_CV_ID, match_key="CV:100")
        for c in (kept, other):
            group.memberships.create(comic=c)
            c.duplicate_group = group
            c.save()
        resolve_keep_all(group)

        new = self._comic(1, state=Comic.STATE_DEDUPLICATED, custom_values={"comicvine_issue": "100"},
                          file_path="/comics/untagged/new.cbz")
        result = run_duplicate_detection_for_comics([new.pk])
        new.refresh_from_db()
        self.assertEqual(result["advanced"], 0)
        self.assertIsNotNone(new.duplicate_group)
        self.assertEqual(new.duplicate_group.status, DuplicateGroup.STATUS_PENDING)
