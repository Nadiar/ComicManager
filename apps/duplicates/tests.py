"""Duplicate detection: who is compared with whom, and how groups are formed."""

from django.test import TestCase

from apps.core.models import Comic
from apps.duplicates.models import DuplicateGroup
from apps.duplicates.services import (
    detect_duplicates_by_phash,
    resolve_keep_all,
    run_duplicate_detection_for_comics,
)


def _hash(bits_set):
    """64-bit hex hash with the given bit positions set."""
    value = 0
    for b in bits_set:
        value |= 1 << b
    return f"{value:016x}"


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

    def test_batch_run_does_not_group_old_library_comics(self):
        # Two old library comics that look alike, never grouped before
        self._comic(5, custom_values={"comicvine_issue": "500"}, file_path="/comics/library/x.cbz")
        self._comic(5, custom_values={"comicvine_issue": "500"}, file_path="/comics/library/y.cbz")
        new = self._comic(9, state=Comic.STATE_DEDUPLICATED, series="Unrelated",
                          file_path="/comics/untagged/z.cbz")
        result = run_duplicate_detection_for_comics([new.pk])
        self.assertEqual(result["groups_created"], 0)
        self.assertEqual(result["advanced"], 1)
        self.assertFalse(DuplicateGroup.objects.exists())


class PhashGroupingTests(TestCase):

    def _comic(self, name, phash):
        return Comic.objects.create(series=name, number="1", phash=phash,
                                    file_path=f"/comics/library/{name}.cbz", file_format="cbz")

    def test_near_matches_do_not_chain(self):
        # b is 4 bits from a, c is 4 bits from b but 8 from a
        a = self._comic("a", _hash([]))
        b = self._comic("b", _hash([0, 1, 2, 3]))
        c = self._comic("c", _hash([0, 1, 2, 3, 4, 5, 6, 7]))
        groups = detect_duplicates_by_phash([a, b, c], max_distance=5)
        self.assertEqual(len(groups), 1)
        members = {m.comic_id for m in groups[0].memberships.all()}
        self.assertEqual(members, {a.pk, b.pk})

    def test_must_include_only_compares_candidates(self):
        a = self._comic("a", _hash([]))
        b = self._comic("b", _hash([1]))           # a and b look alike (old library)
        c = self._comic("c", _hash(range(30, 50)))  # candidate, unlike both
        groups = detect_duplicates_by_phash([a, b, c], max_distance=5, must_include={c.pk})
        self.assertEqual(groups, [])

    def test_candidates_sharing_a_match_end_up_in_one_group(self):
        lib = self._comic("lib", _hash([]))
        c1 = self._comic("c1", _hash([1]))
        c2 = self._comic("c2", _hash([2, 3]))
        groups = detect_duplicates_by_phash([lib, c1, c2], max_distance=5, must_include={c1.pk, c2.pk})
        self.assertEqual(len(groups), 1)
        self.assertEqual({m.comic_id for m in groups[0].memberships.all()}, {lib.pk, c1.pk, c2.pk})
