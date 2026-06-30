"""
Library Organizer Service - Organizes comics into library folder structure.
"""

import os
import shutil
from pathlib import Path

from django.db import transaction

from apps.core.models import Comic

from .engine import find_matching_profile, preview_profile_matches
from .models import OrganizerProfile
from .template_engine import generate_paths


# Base library path (inside container)
LIBRARY_BASE = "/comics/library"


class FileOverwriteError(Exception):
    """Raised when a move would overwrite an existing, different file.

    A move must never silently clobber another comic's file. Callers surface
    this as a failure so the conflict is reported instead of causing data loss.
    """


def _safe_move(old_path: str, new_path: str) -> None:
    """Move old_path to new_path, refusing to overwrite a different existing file.

    If new_path already exists and is not the same file as old_path, raise
    FileOverwriteError rather than letting shutil.move clobber it.
    """
    if os.path.exists(new_path) and os.path.abspath(old_path) != os.path.abspath(new_path):
        raise FileOverwriteError(
            f"Refusing to overwrite existing file: {new_path} "
            f"(would clobber it with {old_path})"
        )
    shutil.move(old_path, new_path)


DEFAULT_PROFILE_NAME = "Default"


def get_default_profile() -> OrganizerProfile:
    """The catch-all profile used when a comic matches no user profile.

    Seeded by a data migration, but recreated here if it was deleted so that
    organizing never falls back to a second, divergent path builder — there is
    exactly one path pipeline (generate_paths/sanitize_filename) for every comic.
    """
    profile, _ = OrganizerProfile.objects.get_or_create(
        name=DEFAULT_PROFILE_NAME,
        defaults={
            "priority": 9999,  # evaluated last; only catches what nothing else does
            "is_enabled": True,
            "folder_template": "<publisher>/<series>{ (<volume>)}",
            "file_template": "<series>{ #<number>}{ (<year>)}",
            "base_folder": LIBRARY_BASE,
            "exclude_rules": {},
        },
    )
    return profile


def organize_comic(comic: Comic, dry_run: bool = False, force: bool = False) -> dict:
    """
    Organize a single comic - move file to library location and update state.

    Args:
        comic: The Comic model instance
        dry_run: If True, don't actually move files or update state
        force: If True, bypass the state and is_duplicate gates (used by force_organize
               and the pipeline). File-existence checks remain enforced.

    Returns:
        Dict with organization results
    """
    if comic.medium == Comic.MEDIUM_PHYSICAL:
        eligible_states = (Comic.STATE_FORMATTED, Comic.STATE_DEDUPLICATED, Comic.STATE_ORGANIZED)
        if not dry_run and (force or comic.state in eligible_states):
            comic.state = Comic.STATE_WRITTEN
            comic.save(update_fields=["state"])
        return {
            "success": True,
            "message": "Physical comic - no file to organize",
            "profile": None,
            "old_path": None,
            "new_path": None,
            "moved": False,
            "dry_run": dry_run,
        }

    if not force and comic.state != Comic.STATE_ORGANIZED:
        return {
            "success": False,
            "message": f"Comic must be in 'move' state, but is '{comic.state}'",
            "profile": None,
            "old_path": comic.file_path,
            "new_path": None,
            "moved": False,
            "dry_run": dry_run,
        }

    if not force and comic.is_duplicate:
        return {
            "success": False,
            "message": "Comic is marked as duplicate - resolve duplicate group first",
            "profile": None,
            "old_path": comic.file_path,
            "new_path": None,
            "moved": False,
            "dry_run": dry_run,
        }

    # Verify file exists
    if not comic.file_path or not os.path.exists(comic.file_path):
        return {
            "success": False,
            "message": f"File not found: {comic.file_path}",
            "profile": None,
            "old_path": comic.file_path,
            "new_path": None,
            "moved": False,
            "dry_run": dry_run,
        }

    # Find matching profile, falling back to the catch-all default profile so
    # every comic runs through the same generate_paths pipeline.
    profile = find_matching_profile(comic) or get_default_profile()
    folder_path, filename = generate_paths(comic, profile)
    profile_name = profile.name
    base = profile.base_folder or LIBRARY_BASE

    # Build full destination path
    old_path = comic.file_path
    file_ext = os.path.splitext(old_path)[1]  # .cbz, .cbr, etc.
    new_folder = os.path.join(base, folder_path)
    new_path = os.path.join(new_folder, filename + file_ext)

    # Perform the move (or simulate)
    moved = False
    error = None

    if not dry_run:
        try:
            # Create destination directory
            os.makedirs(new_folder, exist_ok=True)

            # Move the file (refuses to overwrite a different existing file)
            if os.path.abspath(old_path) != os.path.abspath(new_path):
                _safe_move(old_path, new_path)
                moved = True

                # Try to remove empty source directories
                try:
                    old_dir = os.path.dirname(old_path)
                    while old_dir and old_dir != "/comics/untagged":
                        if os.path.isdir(old_dir) and not os.listdir(old_dir):
                            os.rmdir(old_dir)
                            old_dir = os.path.dirname(old_dir)
                        else:
                            break
                except OSError:
                    pass  # Ignore errors when cleaning up directories

            # Update comic record
            with transaction.atomic():
                comic.file_path = new_path
                comic.last_organized_path = new_path
                comic.state = Comic.STATE_WRITTEN
                comic.save()

        except FileOverwriteError as e:
            return {
                "success": False,
                "message": str(e),
                "error": str(e),
                "conflict": True,
                "profile": profile_name,
                "old_path": old_path,
                "new_path": new_path,
                "moved": False,
                "dry_run": dry_run,
            }
        except Exception as e:
            error = str(e)
            return {
                "success": False,
                "message": f"Failed to move file: {error}",
                "error": error,
                "profile": profile_name,
                "old_path": old_path,
                "new_path": new_path,
                "moved": False,
                "dry_run": dry_run,
            }

    return {
        "success": True,
        "message": "Comic organized successfully" if moved else "File already in correct location",
        "profile": profile_name,
        "old_path": old_path,
        "new_path": new_path,
        "moved": moved,
        "dry_run": dry_run,
    }


def reorganize_comic(comic: Comic) -> dict:
    """
    Re-organize a comic that's already been organized, written, or done.
    Moves the file to its current correct location based on organizer profiles.
    Does NOT change workflow state.

    Returns:
        Dict with success, moved, old_path, new_path, profile, error
    """
    if comic.medium == Comic.MEDIUM_PHYSICAL:
        return {"success": True, "moved": False, "message": "Physical comic"}

    if comic.state not in (Comic.STATE_ORGANIZED, Comic.STATE_WRITTEN, Comic.STATE_DONE):
        return {
            "success": False,
            "moved": False,
            "error": f"Comic must be organized, written, or done (current: {comic.state})",
        }

    preview = preview_organization(comic)
    old_path = comic.file_path
    new_path = preview["new_path"]

    if os.path.abspath(old_path) == os.path.abspath(new_path):
        # Already correct — just clear the flag
        if comic.needs_reorganize:
            comic.needs_reorganize = False
            comic.expected_path = None
            comic.save(update_fields=["needs_reorganize", "expected_path"])
        return {
            "success": True,
            "moved": False,
            "old_path": old_path,
            "new_path": new_path,
            "profile": preview["selected_profile"],
        }

    if not os.path.exists(old_path):
        return {"success": False, "moved": False, "error": f"Source file not found: {old_path}"}

    try:
        new_folder = os.path.dirname(new_path)
        os.makedirs(new_folder, exist_ok=True)

        _safe_move(old_path, new_path)

        # Clean up empty source directories
        try:
            old_dir = os.path.dirname(old_path)
            while old_dir and old_dir != LIBRARY_BASE:
                if os.path.isdir(old_dir) and not os.listdir(old_dir):
                    os.rmdir(old_dir)
                    old_dir = os.path.dirname(old_dir)
                else:
                    break
        except OSError:
            pass

        with transaction.atomic():
            comic.file_path = new_path
            comic.last_organized_path = new_path
            comic.needs_reorganize = False
            comic.expected_path = None
            comic.save()

        return {
            "success": True,
            "moved": True,
            "old_path": old_path,
            "new_path": new_path,
            "profile": preview["selected_profile"],
        }

    except FileOverwriteError as e:
        return {"success": False, "moved": False, "error": str(e), "conflict": True}
    except PermissionError:
        raise
    except OSError as e:
        import errno as _errno
        if e.errno == _errno.ENOSPC:
            raise
        return {"success": False, "moved": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "moved": False, "error": str(e)}


def organize_all_comics(dry_run: bool = False) -> dict:
    """
    Batch organize all ready comics.

    Digital comics must be in 'deduplicated' state.
    Physical comics advance from 'formatted' or 'deduplicated' — they skip deduplication.

    Args:
        dry_run: If True, don't actually move files or update state

    Returns:
        Dict with batch results
    """
    from django.db.models import Q

    # Digital comics need to be in deduplicated state.
    # Physical comics can advance from formatted or deduplicated — they skip deduplication.
    comics = Comic.objects.filter(
        Q(state=Comic.STATE_DEDUPLICATED) |
        Q(state=Comic.STATE_FORMATTED, medium=Comic.MEDIUM_PHYSICAL)
    )
    total_count = comics.count()

    if total_count == 0:
        return {
            "success": True,
            "message": "No comics ready to organize",
            "total_processed": 0,
            "total_moved": 0,
            "total_errors": 0,
            "dry_run": dry_run,
        }

    processed = 0
    moved = 0
    errors = 0

    for comic in comics:
        result = organize_comic(comic, dry_run=dry_run)
        processed += 1

        if result["success"]:
            if result["moved"]:
                moved += 1
        else:
            errors += 1

    return {
        "success": True,
        "message": f"Processed {processed} comics, moved {moved}, errors: {errors}",
        "total_processed": processed,
        "total_moved": moved,
        "total_errors": errors,
        "dry_run": dry_run,
    }


def preview_organization(comic: Comic) -> dict:
    """
    Preview where a comic would be organized without moving it.

    Args:
        comic: The Comic model instance

    Returns:
        Dict with preview information
    """
    # Get all profile matches
    profile_matches = preview_profile_matches(comic)

    # Find selected profile
    selected_profile = None
    for pm in profile_matches:
        if pm["is_selected"]:
            selected_profile = OrganizerProfile.objects.get(id=pm["profile_id"])
            break

    # Generate paths; fall back to the catch-all default profile.
    profile = selected_profile or get_default_profile()
    folder_path, filename = generate_paths(comic, profile)
    profile_name = profile.name
    base = profile.base_folder or LIBRARY_BASE

    # Build full paths
    old_path = comic.file_path
    file_ext = os.path.splitext(old_path)[1] if old_path else ".cbz"
    new_folder = os.path.join(base, folder_path)
    new_path = os.path.join(new_folder, filename + file_ext)

    return {
        "comic_id": str(comic.id),
        "comic_str": str(comic),
        "current_state": comic.state,
        "old_path": old_path,
        "new_folder": new_folder,
        "new_filename": filename + file_ext,
        "new_path": new_path,
        "selected_profile": profile_name,
        "profile_matches": profile_matches,
        "would_move": old_path != new_path if old_path else False,
    }


def _normalize_for_match(text: str) -> str:
    """Normalize text for fuzzy filename matching (lowercase, strip punctuation)."""
    import re
    text = re.sub(r'[^a-z0-9 ]', '', text.lower())
    return re.sub(r' +', ' ', text).strip()


def _find_file_in_folder(folder: str, series: str, number: str) -> str | None:
    """
    Search a folder for a CBZ file matching a comic's series and number.

    Returns the path if a single unambiguous match is found, None otherwise.
    """
    if not os.path.isdir(folder):
        return None

    import re
    series_norm = _normalize_for_match(series or "")
    # Normalize number: strip leading zeros for comparison
    number_normalized = (number or "").lstrip("0") or "0"

    candidates = []
    for fname in os.listdir(folder):
        if not fname.lower().endswith(".cbz"):
            continue
        fname_norm = _normalize_for_match(fname)
        # Check series name appears in filename (normalized)
        if series_norm and series_norm not in fname_norm:
            continue
        # Match #027, #27, etc. - extract number and normalize
        num_match = re.search(r'#(\d+)', fname)
        if num_match:
            fname_num = num_match.group(1).lstrip("0") or "0"
            if fname_num == number_normalized:
                candidates.append(os.path.join(folder, fname))

    # Only return if we found exactly one match (avoid ambiguity)
    if len(candidates) == 1:
        return candidates[0]
    return None


def sync_library_paths() -> dict:
    """
    Sync database file_path values with actual filesystem locations.

    For each digital comic in organized/written state where file_path doesn't
    exist on disk:
    1. Check the organizer's computed target path
    2. If not there, scan the target folder for a matching CBZ by series+number
    3. Update the DB if the file is found

    Returns:
        Dict with sync results
    """
    comics = list(
        Comic.objects.filter(
            state__in=[Comic.STATE_ORGANIZED, Comic.STATE_WRITTEN],
            medium=Comic.MEDIUM_DIGITAL,
        ).exclude(file_path__isnull=True).exclude(file_path="")
    )

    # Build path→comic lookup for collision detection
    path_to_comic = {}
    for c in Comic.objects.filter(medium=Comic.MEDIUM_DIGITAL).exclude(
        file_path__isnull=True
    ):
        path_to_comic[c.file_path] = c.pk

    total = len(comics)
    already_ok = 0
    synced = 0
    removed_dupes = 0
    not_found = 0
    errors = []

    for comic in comics:
        # File already exists at recorded path
        if os.path.exists(comic.file_path):
            already_ok += 1
            continue

        # File is missing - try to find it
        try:
            preview = preview_organization(comic)
            target_path = preview["new_path"]
            target_folder = preview["new_folder"]
            found_path = None

            # Strategy 1: exact target path
            if os.path.exists(target_path):
                found_path = target_path
            else:
                # Strategy 2: scan target folder for matching file
                found_path = _find_file_in_folder(
                    target_folder, comic.series, comic.number
                )

            if found_path and found_path not in path_to_comic:
                # File found, no other record claims it - update path
                old_path = comic.file_path
                comic.file_path = found_path
                comic.last_organized_path = found_path
                comic.save()
                path_to_comic.pop(old_path, None)
                path_to_comic[found_path] = comic.pk
                synced += 1
            elif found_path and found_path in path_to_comic:
                # File already belongs to another record - this is a stale dupe
                other_pk = path_to_comic[found_path]
                if other_pk != comic.pk:
                    comic.delete()
                    path_to_comic.pop(comic.file_path, None)
                    removed_dupes += 1
            else:
                not_found += 1
                errors.append(
                    f"{comic.series} #{comic.number}: not found at DB path, "
                    f"target path, or in target folder"
                )
        except Exception as e:
            not_found += 1
            errors.append(f"{comic.series} #{comic.number}: {str(e)}")

    return {
        "success": True,
        "message": (
            f"Scanned {total} comics: {synced} paths synced, "
            f"{removed_dupes} stale duplicates removed, "
            f"{already_ok} already correct, {not_found} not found"
        ),
        "total": total,
        "synced": synced,
        "removed_dupes": removed_dupes,
        "already_ok": already_ok,
        "not_found": not_found,
        "errors": errors,
    }


def get_organization_stats() -> dict:
    """
    Get statistics about organization state.

    Returns:
        Dict with counts and info
    """
    total_profiles = OrganizerProfile.objects.count()
    enabled_profiles = OrganizerProfile.objects.filter(is_enabled=True).count()

    pending_comics = Comic.objects.filter(
        state=Comic.STATE_DEDUPLICATED,
        medium=Comic.MEDIUM_DIGITAL,
    ).count()

    organized_comics = Comic.objects.filter(state=Comic.STATE_ORGANIZED).count()

    return {
        "total_profiles": total_profiles,
        "enabled_profiles": enabled_profiles,
        "disabled_profiles": total_profiles - enabled_profiles,
        "pending_organization": pending_comics,
        "already_organized": organized_comics,
    }
