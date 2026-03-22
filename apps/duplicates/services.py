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


# ============================================================================
# Batch Detection
# ============================================================================


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
    cv_groups = detect_duplicates_by_cv_id(comparison_pool)
    meta_groups = detect_duplicates_by_metadata(comparison_pool)
    phash_groups = detect_duplicates_by_phash(comparison_pool)
    filename_groups = detect_duplicates_by_filename(comparison_pool)

    all_groups = cv_groups + meta_groups + phash_groups + filename_groups
    logger.info(f"run_duplicate_detection: created {len(all_groups)} total groups")

    # Collect IDs of candidates that ended up in groups
    candidates_with_groups = set()
    for group in all_groups:
        for membership in group.memberships.all():
            if membership.comic_id in candidate_pks:
                candidates_with_groups.add(membership.comic_id)

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
        "by_cv_id": len(cv_groups),
        "by_metadata": len(meta_groups),
        "by_phash": len(phash_groups),
        "by_filename": len(filename_groups),
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
    cv_groups = detect_duplicates_by_cv_id(comics)
    meta_groups = detect_duplicates_by_metadata(comics)
    phash_groups = detect_duplicates_by_phash(comics)
    filename_groups = detect_duplicates_by_filename(comics)

    all_groups = cv_groups + meta_groups + phash_groups + filename_groups
    logger.info(f"scan_all_for_duplicates: created {len(all_groups)} total groups")

    return {
        "success": True,
        "message": f"Scan complete: {len(all_groups)} duplicate groups found",
        "total_comics": len(comics),
        "groups_created": len(all_groups),
        "by_cv_id": len(cv_groups),
        "by_metadata": len(meta_groups),
        "by_phash": len(phash_groups),
        "by_filename": len(filename_groups),
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
