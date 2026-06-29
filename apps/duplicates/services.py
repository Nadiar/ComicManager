"""
Duplicate Detection Services.

Core business logic for detecting and resolving duplicates.
"""

import logging
import os
from collections import defaultdict
from typing import Optional

from django.db import transaction
from django.utils import timezone

from apps.core.models import Comic

from .models import (
    DuplicateGroup,
    DuplicateGroupMembership,
    DuplicateResolution,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Detection Functions
# ============================================================================


def detect_duplicates_by_cv_id(comics: list[Comic]) -> list[DuplicateGroup]:
    """
    Detect duplicates by ComicVine issue ID.

    Groups comics with the same comicvine_issue custom value.
    EXCLUDES digital+physical pairs (they are NOT duplicates).

    Returns list of newly created DuplicateGroup instances.
    """
    logger.info(f"CV ID detection: scanning {len(comics)} comics")

    # Group by CV ID
    cv_groups: dict[str, list[Comic]] = defaultdict(list)

    for comic in comics:
        cv_id = comic.custom_values.get("comicvine_issue")
        if cv_id:
            cv_groups[cv_id].append(comic)

    logger.info(f"CV ID detection: found {len(cv_groups)} unique CV IDs")

    created_groups = []

    for cv_id, group_comics in cv_groups.items():
        if len(group_comics) < 2:
            continue

        logger.info(f"CV ID {cv_id}: {len(group_comics)} comics found")

        # Filter out digital+physical pairs - they are NOT duplicates
        digital = [c for c in group_comics if c.medium == Comic.MEDIUM_DIGITAL]
        physical = [c for c in group_comics if c.medium == Comic.MEDIUM_PHYSICAL]

        # If we have exactly one digital and one physical, NOT a duplicate
        if len(digital) == 1 and len(physical) == 1:
            continue

        # Multiple of same medium ARE duplicates
        dup_comics = []
        if len(digital) > 1:
            dup_comics.extend(digital)
        if len(physical) > 1:
            dup_comics.extend(physical)

        if len(dup_comics) >= 2:
            logger.info(f"CV ID {cv_id}: creating group with {len(dup_comics)} duplicates")
            for c in dup_comics:
                logger.info(f"  - {c.series} #{c.number} ({c.medium}): {c.file_path}")
            group = _create_duplicate_group(
                comics=dup_comics,
                detection_method=DuplicateGroup.DETECTION_CV_ID,
                match_key=f"CV:{cv_id}",
            )
            created_groups.append(group)

    logger.info(f"CV ID detection: created {len(created_groups)} groups")
    return created_groups


def detect_duplicates_by_metadata(comics: list[Comic]) -> list[DuplicateGroup]:
    """
    Detect duplicates by series + number + volume match.

    Catches unscraped or mis-tagged duplicates that don't have CV IDs.
    Also excludes digital+physical pairs.
    """
    # Group by (series, number, volume) - normalized
    meta_groups: dict[tuple, list[Comic]] = defaultdict(list)

    for comic in comics:
        if not comic.series:
            continue

        key = (
            (comic.series or "").lower().strip(),
            (comic.number or "").lstrip("0").lower() or "0",
            comic.volume or 0,
        )
        meta_groups[key].append(comic)

    created_groups = []

    for key, group_comics in meta_groups.items():
        if len(group_comics) < 2:
            continue

        # Skip if all comics already have same CV ID (handled by cv_id detection)
        cv_ids = set(c.custom_values.get("comicvine_issue") for c in group_comics)
        cv_ids.discard(None)
        if len(cv_ids) == 1:
            continue

        # Filter out digital+physical pairs
        digital = [c for c in group_comics if c.medium == Comic.MEDIUM_DIGITAL]
        physical = [c for c in group_comics if c.medium == Comic.MEDIUM_PHYSICAL]

        if len(digital) == 1 and len(physical) == 1:
            continue

        dup_comics = []
        if len(digital) > 1:
            dup_comics.extend(digital)
        if len(physical) > 1:
            dup_comics.extend(physical)

        if len(dup_comics) >= 2:
            # Page-count sanity check: a TPB and a single issue often share the
            # same series+number+volume but are not duplicates.  If the largest
            # page count is more than 3× the smallest, skip this group.
            pages = [c.page_count for c in dup_comics if c.page_count]
            if len(pages) >= 2 and min(pages) > 0 and max(pages) / min(pages) > 3:
                continue

            series, number, volume = key
            match_key = f"{series} #{number}" + (f" v{volume}" if volume else "")

            group = _create_duplicate_group(
                comics=dup_comics,
                detection_method=DuplicateGroup.DETECTION_METADATA,
                match_key=match_key,
            )
            created_groups.append(group)

    return created_groups


def detect_duplicates_by_phash(
    comics: list[Comic],
    max_distance: int = 5,
) -> list[DuplicateGroup]:
    """
    Detect duplicates by pHash similarity.

    Uses hamming distance between cover image hashes.
    Only considers digital comics (physical have no hash).
    """
    from apps.core.models import get_setting

    # Get threshold from settings, with fallback
    max_distance = get_setting("duplicate_phash_distance", max_distance)

    # Filter to digital comics with hashes
    hashable = [
        c for c in comics
        if c.medium == Comic.MEDIUM_DIGITAL and c.phash
    ]

    if len(hashable) < 2:
        return []

    # Build groups using union-find approach
    parent: dict[str, str] = {}  # comic.pk -> group representative pk
    distances: dict[tuple, int] = {}  # (pk1, pk2) -> distance

    def find(pk: str) -> str:
        if pk not in parent:
            parent[pk] = pk
        if parent[pk] != pk:
            parent[pk] = find(parent[pk])
        return parent[pk]

    def union(pk1: str, pk2: str):
        p1, p2 = find(pk1), find(pk2)
        if p1 != p2:
            parent[p1] = p2

    # Compare all pairs
    for i, c1 in enumerate(hashable):
        for c2 in hashable[i + 1:]:
            distance = _hamming_distance(c1.phash, c2.phash)
            if distance <= max_distance:
                pk1, pk2 = str(c1.pk), str(c2.pk)
                union(pk1, pk2)
                distances[(pk1, pk2)] = distance
                distances[(pk2, pk1)] = distance

    # Collect groups
    groups: dict[str, list[Comic]] = defaultdict(list)
    comic_by_pk = {str(c.pk): c for c in hashable}

    for pk in parent:
        root = find(pk)
        groups[root].append(comic_by_pk[pk])

    created_groups = []

    for root_pk, group_comics in groups.items():
        if len(group_comics) < 2:
            continue

        # Calculate max distance in group
        max_dist = 0
        for c1 in group_comics:
            for c2 in group_comics:
                if c1.pk != c2.pk:
                    d = distances.get((str(c1.pk), str(c2.pk)), 0)
                    max_dist = max(max_dist, d)

        # Use anchor comic's hash as the match key
        anchor = comic_by_pk[root_pk]

        group = _create_duplicate_group(
            comics=group_comics,
            detection_method=DuplicateGroup.DETECTION_PHASH,
            match_key=f"pHash:{anchor.phash[:16]}...",
            anchor_comic=anchor,
            phash_max_distance=max_dist,
        )
        created_groups.append(group)

    return created_groups


def detect_duplicates_by_filename(comics: list[Comic]) -> list[DuplicateGroup]:
    """
    Detect duplicates by OS-generated duplicate filename patterns.

    Catches files like:
    - Linux:   "Comic #001_1.cbz", "Comic #001_2.cbz"  (underscore + number)
    - Windows: "Comic #001 (1).cbz", "Comic #001 (2).cbz"  (space + parens + number)

    Groups these with the base file "Comic #001.cbz" if it exists in the pool.
    Only considers digital comics with file paths.
    """
    import re

    # Pattern to strip OS duplicate suffixes before the extension
    # Matches: _1, _2, _12  or  (1), (2), (12)  at the end of the filename stem
    DUPE_SUFFIX = re.compile(r'(?:_\d+| \(\d+\))$')

    # Filter to digital comics with file paths
    pathable = [
        c for c in comics
        if c.medium == Comic.MEDIUM_DIGITAL and c.file_path
    ]

    if len(pathable) < 2:
        return []

    # Group by normalized base filename (directory + stem without dupe suffix)
    filename_groups: dict[str, list[Comic]] = defaultdict(list)

    for comic in pathable:
        directory = os.path.dirname(comic.file_path)
        basename = os.path.basename(comic.file_path)
        stem, ext = os.path.splitext(basename)

        # Strip OS duplicate suffix to get the canonical name
        canonical_stem = DUPE_SUFFIX.sub('', stem)
        canonical_key = os.path.join(directory, canonical_stem + ext).lower()

        filename_groups[canonical_key].append(comic)

    created_groups = []

    for canonical_key, group_comics in filename_groups.items():
        if len(group_comics) < 2:
            continue

        # At least one comic in the group must have a dupe suffix
        # (otherwise they're just different comics in the same folder)
        has_suffix = False
        for comic in group_comics:
            stem = os.path.splitext(os.path.basename(comic.file_path))[0]
            if DUPE_SUFFIX.search(stem):
                has_suffix = True
                break

        if not has_suffix:
            continue

        base_name = os.path.basename(canonical_key)
        group = _create_duplicate_group(
            comics=group_comics,
            detection_method=DuplicateGroup.DETECTION_FILENAME,
            match_key=f"File:{base_name}",
        )
        created_groups.append(group)

    return created_groups


def _hamming_distance(hash1: str, hash2: str) -> int:
    """Compute hamming distance between two hex hash strings."""
    try:
        h1 = int(hash1, 16) if isinstance(hash1, str) else int(hash1)
        h2 = int(hash2, 16) if isinstance(hash2, str) else int(hash2)
        return bin(h1 ^ h2).count("1")
    except (ValueError, TypeError):
        return 64  # Max distance if invalid


def _create_duplicate_group(
    comics: list[Comic],
    detection_method: str,
    match_key: str,
    anchor_comic: Optional[Comic] = None,
    phash_max_distance: int = None,
) -> DuplicateGroup:
    """
    Create a DuplicateGroup and add comics as members.
    """
    with transaction.atomic():
        group = DuplicateGroup.objects.create(
            detection_method=detection_method,
            match_key=match_key,
            phash_max_distance=phash_max_distance,
        )

        for comic in comics:
            # Calculate distance from anchor for pHash groups
            member_distance = None
            if anchor_comic and detection_method == DuplicateGroup.DETECTION_PHASH:
                if comic.phash and anchor_comic.phash:
                    member_distance = _hamming_distance(anchor_comic.phash, comic.phash)

            DuplicateGroupMembership.objects.create(
                group=group,
                comic=comic,
                phash_distance=member_distance,
            )

            # Update comic reference
            comic.duplicate_group = group
            comic.save(update_fields=["duplicate_group"])

    return group


def _add_to_existing_group(comic: Comic, group: DuplicateGroup) -> None:
    """Attach a comic to an already-existing duplicate group."""
    with transaction.atomic():
        membership, _ = DuplicateGroupMembership.objects.get_or_create(group=group, comic=comic)

        if group.detection_method == DuplicateGroup.DETECTION_PHASH and comic.phash:
            anchor_mem = group.memberships.exclude(comic=comic).select_related("comic").first()
            if anchor_mem and anchor_mem.comic.phash:
                dist = _hamming_distance(comic.phash, anchor_mem.comic.phash)
                DuplicateGroupMembership.objects.filter(group=group, comic=comic).update(phash_distance=dist)
                if group.phash_max_distance is None or dist > group.phash_max_distance:
                    group.phash_max_distance = dist
                    group.save(update_fields=["phash_max_distance"])

        comic.duplicate_group = group
        comic.save(update_fields=["duplicate_group"])


def _attach_orphans_to_pending_groups(orphans: list[Comic]) -> set:
    """
    After main detection, attach ungrouped candidates to any existing pending
    group whose members they match by CV ID, pHash, or filename.

    This catches comics that were processed in a later batch than their
    duplicate partners, which were already grouped before the later batch ran.

    Returns the set of orphan PKs that were attached to an existing group.
    """
    import re
    from apps.core.models import get_setting

    if not orphans:
        return set()

    DUPE_SUFFIX = re.compile(r'(?:_\d+| \(\d+\))$')

    pending_members = list(
        DuplicateGroupMembership.objects.filter(
            group__status=DuplicateGroup.STATUS_PENDING,
        ).select_related("comic", "group")
    )

    if not pending_members:
        return set()

    # Build lookup structures keyed by match criteria
    cv_to_group: dict[str, DuplicateGroup] = {}
    phash_entries: list[tuple[str, DuplicateGroup]] = []
    canonical_to_group: dict[str, DuplicateGroup] = {}

    for mem in pending_members:
        c = mem.comic
        g = mem.group

        cv_id = str((c.custom_values or {}).get("comicvine_issue", ""))
        if cv_id and cv_id not in cv_to_group:
            cv_to_group[cv_id] = g

        if c.phash and c.medium == Comic.MEDIUM_DIGITAL:
            phash_entries.append((c.phash, g))

        if c.file_path and c.medium == Comic.MEDIUM_DIGITAL:
            directory = os.path.dirname(c.file_path)
            stem, ext = os.path.splitext(os.path.basename(c.file_path))
            canonical_key = os.path.join(directory, DUPE_SUFFIX.sub("", stem) + ext).lower()
            if canonical_key not in canonical_to_group:
                canonical_to_group[canonical_key] = g

    phash_threshold = get_setting("duplicate_phash_distance", 5)
    attached_pks: set = set()

    for comic in orphans:
        if comic.duplicate_group_id is not None:
            continue

        target_group = None

        # CV ID (highest confidence)
        cv_id = str((comic.custom_values or {}).get("comicvine_issue", ""))
        if cv_id and cv_id in cv_to_group:
            target_group = cv_to_group[cv_id]

        # pHash
        if target_group is None and comic.phash and comic.medium == Comic.MEDIUM_DIGITAL:
            for phash, group in phash_entries:
                if _hamming_distance(comic.phash, phash) <= phash_threshold:
                    target_group = group
                    break

        # Filename
        if target_group is None and comic.file_path and comic.medium == Comic.MEDIUM_DIGITAL:
            directory = os.path.dirname(comic.file_path)
            stem, ext = os.path.splitext(os.path.basename(comic.file_path))
            canonical_key = os.path.join(directory, DUPE_SUFFIX.sub("", stem) + ext).lower()
            if canonical_key in canonical_to_group:
                target_group = canonical_to_group[canonical_key]

        if target_group is not None:
            _add_to_existing_group(comic, target_group)
            attached_pks.add(comic.pk)
            logger.info(
                f"_attach_orphans_to_pending_groups: attached {comic.pk} to existing group {target_group.pk}"
            )

    return attached_pks


# Method priority for group survival during consolidation (lower = higher priority)
_METHOD_PRIORITY = {
    DuplicateGroup.DETECTION_CV_ID: 0,
    DuplicateGroup.DETECTION_METADATA: 1,
    DuplicateGroup.DETECTION_PHASH: 2,
    DuplicateGroup.DETECTION_FILENAME: 3,
}


def _consolidate_pending_groups() -> int:
    """
    Merge any pending groups that share members into a single group.

    Comics matched by multiple methods (e.g. CV ID and pHash) end up in
    separate groups within the same detection run because the in-memory pool
    is built before any groups are written. This pass merges them.

    Survival rule: most members wins; ties broken by method priority
    (cv_id > metadata > phash > filename).

    Returns the number of groups deleted (merged away).
    """
    pending_groups = list(DuplicateGroup.objects.filter(status=DuplicateGroup.STATUS_PENDING))
    if len(pending_groups) < 2:
        return 0

    group_pks = [g.pk for g in pending_groups]

    # Load memberships in one query: group_pk → set of comic_pks
    group_comics: dict = defaultdict(set)
    for group_pk, comic_pk in DuplicateGroupMembership.objects.filter(
        group_id__in=group_pks
    ).values_list("group_id", "comic_id"):
        group_comics[group_pk].add(comic_pk)

    # Union-find: union groups that share at least one member
    parent: dict = {g.pk: g.pk for g in pending_groups}

    def find(pk):
        while parent[pk] != pk:
            parent[pk] = parent[parent[pk]]
            pk = parent[pk]
        return pk

    def union(pk1, pk2):
        p1, p2 = find(pk1), find(pk2)
        if p1 != p2:
            parent[p1] = p2

    comic_to_groups: dict = defaultdict(list)
    for g in pending_groups:
        for cpk in group_comics.get(g.pk, set()):
            comic_to_groups[cpk].append(g.pk)

    for gpks in comic_to_groups.values():
        for i in range(1, len(gpks)):
            union(gpks[0], gpks[i])

    # Group by root to find components
    components: dict = defaultdict(list)
    group_by_pk = {g.pk: g for g in pending_groups}
    for g in pending_groups:
        components[find(g.pk)].append(g)

    deleted = 0

    for component_groups in components.values():
        if len(component_groups) < 2:
            continue

        # Canonical = most members, then lowest method priority index
        def sort_key(g):
            return (-len(group_comics.get(g.pk, set())), _METHOD_PRIORITY.get(g.detection_method, 99))

        canonical = min(component_groups, key=sort_key)
        to_merge = [g for g in component_groups if g.pk != canonical.pk]

        all_comic_pks = set()
        for g in component_groups:
            all_comic_pks |= group_comics.get(g.pk, set())

        with transaction.atomic():
            for cpk in all_comic_pks:
                DuplicateGroupMembership.objects.get_or_create(
                    group=canonical,
                    comic_id=cpk,
                )
            Comic.objects.filter(pk__in=all_comic_pks).update(duplicate_group=canonical)
            for g in to_merge:
                g.delete()
            deleted += len(to_merge)

        logger.info(
            f"_consolidate_pending_groups: merged {len(to_merge)} groups into {canonical.pk} "
            f"({canonical.detection_method}, {len(all_comic_pks)} comics)"
        )

    return deleted


# ============================================================================
# Batch Detection
# ============================================================================


def _run_all_detectors(pool: list) -> tuple[list, dict]:
    """Run every duplicate-detection method over `pool`.

    Returns the combined list of groups plus a per-method count breakdown
    so callers that report statistics don't have to repeat the four calls.
    """
    by_cv_id = detect_duplicates_by_cv_id(pool)
    by_metadata = detect_duplicates_by_metadata(pool)
    by_phash = detect_duplicates_by_phash(pool)
    by_filename = detect_duplicates_by_filename(pool)
    all_groups = by_cv_id + by_metadata + by_phash + by_filename
    counts = {
        "by_cv_id": len(by_cv_id),
        "by_metadata": len(by_metadata),
        "by_phash": len(by_phash),
        "by_filename": len(by_filename),
    }
    return all_groups, counts


def run_duplicate_detection_for_comics(comic_pks: list) -> dict:
    """
    Run duplicate detection for a specific set of comics.
    Each comic is checked against the full library; clean comics advance to organized state.
    """
    candidates = list(Comic.objects.filter(
        pk__in=comic_pks,
        state=Comic.STATE_DEDUPLICATED,
        duplicate_group__isnull=True,
    ))

    if not candidates:
        return {"success": True, "message": "No eligible comics to process", "total_comics": 0, "groups_created": 0, "advanced": 0}

    candidate_pks = set(c.pk for c in candidates)

    library_comics = list(Comic.objects.filter(
        duplicate_group__isnull=True,
    ).exclude(
        state=Comic.STATE_DEDUPLICATED,
    ).exclude(pk__in=candidate_pks))

    comparison_pool = candidates + library_comics

    all_groups, _ = _run_all_detectors(comparison_pool)

    candidates_with_groups = set()
    for group in all_groups:
        for membership in group.memberships.all():
            if membership.comic_id in candidate_pks:
                candidates_with_groups.add(membership.comic_id)

    # Attach any remaining ungrouped candidates to existing pending groups, then
    # merge groups that share members. Without this the selected path produced
    # un-consolidated, orphan-laden groups that the full scan would have cleaned
    # up — same comics, different grouping depending on the entry point.
    still_ungrouped = [c for c in candidates if c.pk not in candidates_with_groups]
    orphan_pks = _attach_orphans_to_pending_groups(still_ungrouped)
    candidates_with_groups |= orphan_pks
    merged = _consolidate_pending_groups()

    from apps.core.audit import log_batch_entry

    advanced = 0
    for comic in candidates:
        if comic.pk not in candidates_with_groups:
            state_before = comic.state
            comic.state = Comic.STATE_ORGANIZED
            comic.save(update_fields=["state"])
            advanced += 1
            log_batch_entry(
                "deduplicate_selected", comic, state_before, Comic.STATE_ORGANIZED,
                {"state": [state_before, Comic.STATE_ORGANIZED]},
            )

    return {
        "success": True,
        "message": f"Detection complete: {len(all_groups)} duplicate groups found",
        "total_comics": len(candidates),
        "groups_created": len(all_groups),
        "orphans_attached": len(orphan_pks),
        "groups_merged": merged,
        "advanced": advanced,
    }


def run_duplicate_detection() -> dict:
    """
    Run full duplicate detection on formatted comics.

    Compares formatted candidates against the ENTIRE library (all states)
    to catch duplicates of already-processed comics, not just other
    formatted comics.

    Returns dict with detection statistics.
    """
    # Get candidates: deduplicated comics without existing group
    candidates = list(Comic.objects.filter(
        state=Comic.STATE_DEDUPLICATED,
        duplicate_group__isnull=True,
    ))

    logger.info(f"run_duplicate_detection: found {len(candidates)} deduplicated candidates")

    if not candidates:
        return {
            "success": True,
            "message": "No comics to process",
            "total_comics": 0,
            "groups_created": 0,
            "advanced": 0,
        }

    candidate_pks = set(c.pk for c in candidates)

    # Build comparison pool: candidates + all library comics without a group.
    # This catches duplicates of already-processed comics (e.g. a new import
    # that matches an already-written comic).
    library_comics = list(Comic.objects.filter(
        duplicate_group__isnull=True,
    ).exclude(
        state=Comic.STATE_DEDUPLICATED,
    ))

    comparison_pool = candidates + library_comics
    logger.info(
        f"run_duplicate_detection: comparison pool = {len(candidates)} candidates "
        f"+ {len(library_comics)} library comics = {len(comparison_pool)} total"
    )

    # Run detection methods on the full pool
    all_groups, method_counts = _run_all_detectors(comparison_pool)
    logger.info(f"run_duplicate_detection: created {len(all_groups)} total groups")

    # Collect IDs of candidates that ended up in groups
    candidates_with_groups = set()
    for group in all_groups:
        for membership in group.memberships.all():
            if membership.comic_id in candidate_pks:
                candidates_with_groups.add(membership.comic_id)

    # Attach any remaining ungrouped candidates to existing pending groups.
    # Handles the case where a candidate's duplicate partner was already grouped
    # in a previous detection run and therefore excluded from the pool above.
    still_ungrouped = [c for c in candidates if c.pk not in candidates_with_groups]
    orphan_pks = _attach_orphans_to_pending_groups(still_ungrouped)
    candidates_with_groups |= orphan_pks
    logger.info(f"run_duplicate_detection: attached {len(orphan_pks)} orphans to existing groups")

    # Merge groups that share members (same comics matched by multiple methods)
    merged = _consolidate_pending_groups()
    logger.info(f"run_duplicate_detection: consolidated {merged} redundant groups")

    # Only advance candidates (formatted comics) without duplicates
    from apps.core.audit import log_batch_entry

    advanced = 0
    for comic in candidates:
        if comic.pk not in candidates_with_groups:
            state_before = comic.state
            comic.state = Comic.STATE_ORGANIZED
            comic.save(update_fields=["state"])
            advanced += 1
            log_batch_entry(
                "deduplicate_all", comic, state_before, Comic.STATE_ORGANIZED,
                {"state": [state_before, Comic.STATE_ORGANIZED]},
            )

    logger.info(f"run_duplicate_detection: advanced {advanced} candidates to organized")

    return {
        "success": True,
        "message": f"Detection complete: {len(all_groups)} duplicate groups found",
        "total_comics": len(candidates),
        "groups_created": len(all_groups),
        **method_counts,
        "advanced": advanced,
    }


def scan_all_for_duplicates() -> dict:
    """
    Scan ALL digital comics for duplicates, regardless of state.

    This is useful for catching duplicates that already passed through
    the workflow before duplicate detection was implemented.

    Does NOT change comic states - only creates duplicate groups for review.
    """
    # Get all digital comics without existing group
    comics = list(Comic.objects.filter(
        medium=Comic.MEDIUM_DIGITAL,
        duplicate_group__isnull=True,
    ))

    logger.info(f"scan_all_for_duplicates: scanning {len(comics)} digital comics")

    if not comics:
        return {
            "success": True,
            "message": "No comics to scan",
            "total_comics": 0,
            "groups_created": 0,
        }

    # Run detection methods
    all_groups, method_counts = _run_all_detectors(comics)
    logger.info(f"scan_all_for_duplicates: created {len(all_groups)} total groups")

    # After creating new groups, attach any still-ungrouped comics to existing
    # pending groups (catches orphans whose partners were already grouped before
    # this scan ran).
    newly_grouped_pks = set()
    for group in all_groups:
        for mem in group.memberships.all():
            newly_grouped_pks.add(mem.comic_id)

    still_ungrouped = [c for c in comics if c.pk not in newly_grouped_pks]
    orphan_pks = _attach_orphans_to_pending_groups(still_ungrouped)
    logger.info(f"scan_all_for_duplicates: attached {len(orphan_pks)} orphans to existing groups")

    # Merge groups that share members (same comics matched by multiple methods)
    merged = _consolidate_pending_groups()
    logger.info(f"scan_all_for_duplicates: consolidated {merged} redundant groups")

    return {
        "success": True,
        "message": f"Scan complete: {len(all_groups)} duplicate groups found, {len(orphan_pks)} orphans attached, {merged} redundant groups merged",
        "total_comics": len(comics),
        "groups_created": len(all_groups),
        "orphans_attached": len(orphan_pks),
        "groups_merged": merged,
        **method_counts,
    }


# ============================================================================
# Resolution Functions
# ============================================================================


def resolve_keep(
    group: DuplicateGroup,
    winner_comic_id: str,
    reason: str = "",
) -> dict:
    """
    Keep a comic as the winner in a duplicate group.

    The winner advances to deduplicated state.
    Other comics remain pending until resolved.
    """
    winner = Comic.objects.get(pk=winner_comic_id)
    membership = DuplicateGroupMembership.objects.get(
        group=group,
        comic=winner,
    )

    with transaction.atomic():
        # Mark this comic as kept
        membership.resolution = DuplicateGroupMembership.RESOLUTION_KEPT
        membership.save()

        # Update the comic — only advance if still in deduplicated state
        # (don't downgrade already-processed comics)
        winner.is_duplicate = False
        winner.duplicate_of = None
        winner.format_ok = True
        if winner.state == Comic.STATE_DEDUPLICATED:
            winner.state = Comic.STATE_ORGANIZED
        winner.save()

        # Update group
        group.kept_comic = winner
        group.save()

        # Create audit log
        DuplicateResolution.objects.create(
            group=group,
            detection_method=group.detection_method,
            match_key=group.match_key,
            action=DuplicateResolution.ACTION_KEEP,
            comic_id=winner.pk,
            comic_str=str(winner),
            reason=reason,
        )

        # Check if group is fully resolved
        _check_group_resolved(group)

    return {
        "success": True,
        "message": f"Kept: {winner}",
        "comic": str(winner),
    }


def resolve_keep_and_delete_rest(
    group: DuplicateGroup,
    winner_comic_id: str,
    reason: str = "",
) -> dict:
    """
    Keep one comic as the winner and hard-delete all other pending comics in the group.
    Resolves the group in a single action.
    """
    # Collect IDs of other pending comics before marking the winner as kept
    others_to_delete = list(
        group.memberships
        .filter(resolution=DuplicateGroupMembership.RESOLUTION_PENDING)
        .exclude(comic_id=winner_comic_id)
        .values_list("comic_id", flat=True)
    )

    keep_result = resolve_keep(group, winner_comic_id, reason)

    deleted = []
    for comic_id in others_to_delete:
        try:
            del_result = resolve_delete(group, str(comic_id), reason="Deleted: keep-and-delete-rest action")
            deleted.append(del_result.get("comic", str(comic_id)))
        except Exception as e:
            logger.error("keep_and_delete_rest: failed to delete comic %s: %s", comic_id, e)

    return {
        "success": True,
        "message": f"Kept: {keep_result['comic']}. Deleted {len(deleted)} comic(s).",
        "deleted": deleted,
    }


def resolve_requeue(
    group: DuplicateGroup,
    comic_id: str,
    reason: str = "",
) -> dict:
    """
    Send a comic back to imported state for re-scraping.

    Removes it from the duplicate group.
    """
    comic = Comic.objects.get(pk=comic_id)
    membership = DuplicateGroupMembership.objects.get(
        group=group,
        comic=comic,
    )

    with transaction.atomic():
        # Mark as requeued
        membership.resolution = DuplicateGroupMembership.RESOLUTION_REQUEUED
        membership.save()

        # Reset comic state and clear CV data for re-scraping
        comic.state = Comic.STATE_IMPORTED
        comic.duplicate_group = None
        comic.is_duplicate = False
        comic.duplicate_of = None
        # Clear CV data so it gets re-scraped
        comic.custom_values.pop("comicvine_issue", None)
        comic.custom_values.pop("comicvine_volume", None)
        comic.custom_values.pop("scrape_source", None)
        comic.save()

        # Create audit log
        DuplicateResolution.objects.create(
            group=group,
            detection_method=group.detection_method,
            match_key=group.match_key,
            action=DuplicateResolution.ACTION_REQUEUE,
            comic_id=comic.pk,
            comic_str=str(comic),
            reason=reason,
        )

        # Check if group is fully resolved
        _check_group_resolved(group)

    return {
        "success": True,
        "message": f"Re-queued: {comic} (sent back to imported state)",
        "comic": str(comic),
    }


def resolve_delete(
    group: DuplicateGroup,
    comic_id: str,
    reason: str = "",
) -> dict:
    """
    Hard delete a comic: remove file from disk AND delete DB record.
    """
    comic = Comic.objects.get(pk=comic_id)
    membership = DuplicateGroupMembership.objects.get(
        group=group,
        comic=comic,
    )

    comic_str = str(comic)
    file_path = comic.file_path
    file_deleted = False

    with transaction.atomic():
        # Mark as deleted in membership (before deleting comic)
        membership.resolution = DuplicateGroupMembership.RESOLUTION_DELETED
        membership.save()

        # Create audit log BEFORE deleting
        DuplicateResolution.objects.create(
            group=group,
            detection_method=group.detection_method,
            match_key=group.match_key,
            action=DuplicateResolution.ACTION_DELETE,
            comic_id=comic.pk,
            comic_str=comic_str,
            reason=reason,
        )

        # Delete file from disk
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                file_deleted = True

                # Try to remove empty parent directories
                parent_dir = os.path.dirname(file_path)
                while parent_dir and parent_dir != "/comics":
                    if os.path.isdir(parent_dir) and not os.listdir(parent_dir):
                        os.rmdir(parent_dir)
                        parent_dir = os.path.dirname(parent_dir)
                    else:
                        break
            except OSError:
                pass  # Continue even if file deletion fails

        # Delete the comic record
        comic.delete()

        # Check if group is fully resolved
        _check_group_resolved(group)

    return {
        "success": True,
        "message": f"Deleted: {comic_str}" + (" (file removed)" if file_deleted else ""),
        "comic": comic_str,
        "file_deleted": file_deleted,
    }


def resolve_keep_all(
    group: DuplicateGroup,
    reason: str = "",
) -> dict:
    """
    Mark all comics in group as intentional (not duplicates).

    All advance to deduplicated state.
    """
    memberships = group.memberships.select_related("comic").all()
    count = 0

    with transaction.atomic():
        for membership in memberships:
            if membership.resolution == DuplicateGroupMembership.RESOLUTION_PENDING:
                comic = membership.comic
                membership.resolution = DuplicateGroupMembership.RESOLUTION_KEPT
                membership.save()

                comic.is_duplicate = False
                comic.duplicate_of = None
                # Only advance if still in deduplicated state
                # (don't downgrade already-processed comics)
                if comic.state == Comic.STATE_DEDUPLICATED:
                    comic.state = Comic.STATE_ORGANIZED
                comic.save()
                count += 1

        group.status = DuplicateGroup.STATUS_INTENTIONAL
        group.resolved_at = timezone.now()
        group.save()

        DuplicateResolution.objects.create(
            group=group,
            detection_method=group.detection_method,
            match_key=group.match_key,
            action=DuplicateResolution.ACTION_KEEP_ALL,
            reason=reason,
        )

    return {
        "success": True,
        "message": f"Kept all {count} comics as intentional (not duplicates)",
        "count": count,
    }


def _check_group_resolved(group: DuplicateGroup):
    """
    Check if group should be auto-resolved.

    Auto-resolves when:
    - All memberships are resolved (0 pending), OR
    - Only 1 comic remains pending (no longer a duplicate situation)
    """
    pending_memberships = group.memberships.filter(
        resolution=DuplicateGroupMembership.RESOLUTION_PENDING
    )
    pending_count = pending_memberships.count()

    if pending_count == 0:
        # All resolved — only update status fields, not kept_comic.
        # The kept_comic FK may have been CASCADE-nullified if that comic was
        # deleted in the same transaction (e.g. keep_and_delete_rest), and
        # saving the stale Python object would cause an IntegrityError.
        group.status = DuplicateGroup.STATUS_RESOLVED
        group.resolved_at = timezone.now()
        group.save(update_fields=["status", "resolved_at"])
    elif pending_count == 1:
        # Only 1 comic left - auto-keep it since it's no longer a duplicate
        membership = pending_memberships.first()
        comic = membership.comic

        membership.resolution = DuplicateGroupMembership.RESOLUTION_KEPT
        membership.save()

        comic.is_duplicate = False
        comic.duplicate_of = None
        # Only advance if still in deduplicated state
        # (don't downgrade already-processed comics)
        if comic.state == Comic.STATE_DEDUPLICATED:
            comic.state = Comic.STATE_ORGANIZED
        comic.save()

        group.kept_comic = comic
        group.status = DuplicateGroup.STATUS_RESOLVED
        group.resolved_at = timezone.now()
        group.save()

        # Log the auto-resolution
        DuplicateResolution.objects.create(
            group=group,
            detection_method=group.detection_method,
            match_key=group.match_key,
            action=DuplicateResolution.ACTION_KEEP,
            comic_id=comic.pk,
            comic_str=str(comic),
            reason="Auto-kept: last remaining comic in group",
        )


# ============================================================================
# Query Functions
# ============================================================================


def get_pending_groups() -> list[dict]:
    """
    Get all pending duplicate groups with their comics for review.
    """
    groups = DuplicateGroup.objects.filter(
        status=DuplicateGroup.STATUS_PENDING
    ).prefetch_related(
        "memberships__comic"
    ).order_by("detection_method", "-created_at")

    result = []
    for group in groups:
        comics_data = []
        for membership in group.memberships.filter(
            resolution=DuplicateGroupMembership.RESOLUTION_PENDING
        ).select_related("comic"):
            comic = membership.comic
            comics_data.append({
                "id": str(comic.pk),
                "series": comic.series,
                "number": comic.number,
                "volume": comic.volume,
                "title": comic.title,
                "publisher": comic.publisher,
                "format": comic.format,
                "file_path": comic.file_path,
                "file_size": comic.file_size,
                "page_count": comic.page_count,
                "phash": comic.phash,
                "medium": comic.medium,
                "scrape_source": comic.custom_values.get("scrape_source"),
                "cv_issue": comic.custom_values.get("comicvine_issue"),
                "phash_distance": membership.phash_distance,
            })

        if len(comics_data) >= 2:  # Only include groups with 2+ pending comics
            result.append({
                "id": str(group.pk),
                "detection_method": group.detection_method,
                "detection_method_display": group.get_detection_method_display(),
                "match_key": group.match_key,
                "comic_count": len(comics_data),
                "comics": comics_data,
                "created_at": group.created_at.isoformat(),
            })
        elif len(comics_data) == 1:
            # Auto-resolve single-comic groups
            _check_group_resolved(group)

    return result


def get_duplicate_stats() -> dict:
    """
    Get statistics about duplicate detection state.
    """
    pending = DuplicateGroup.objects.filter(status=DuplicateGroup.STATUS_PENDING)
    resolved = DuplicateGroup.objects.filter(status=DuplicateGroup.STATUS_RESOLVED)
    intentional = DuplicateGroup.objects.filter(status=DuplicateGroup.STATUS_INTENTIONAL)

    deduplicated_count = Comic.objects.filter(state=Comic.STATE_DEDUPLICATED).count()
    organized_count = Comic.objects.filter(state=Comic.STATE_ORGANIZED).count()
    marked_duplicate = Comic.objects.filter(is_duplicate=True).count()

    return {
        "pending_groups": pending.count(),
        "resolved_groups": resolved.count(),
        "intentional_groups": intentional.count(),
        "pending_by_method": {
            "cv_id": pending.filter(detection_method=DuplicateGroup.DETECTION_CV_ID).count(),
            "metadata": pending.filter(detection_method=DuplicateGroup.DETECTION_METADATA).count(),
            "phash": pending.filter(detection_method=DuplicateGroup.DETECTION_PHASH).count(),
            "filename": pending.filter(detection_method=DuplicateGroup.DETECTION_FILENAME).count(),
        },
        "deduplicated_comics": deduplicated_count,
        "organized_comics": organized_count,
        "marked_duplicate": marked_duplicate,
    }


def get_resolution_history(limit: int = 100) -> list[DuplicateResolution]:
    """
    Get recent resolution audit log entries.
    """
    return list(DuplicateResolution.objects.all()[:limit])
