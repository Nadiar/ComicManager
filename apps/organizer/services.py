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


def organize_comic(comic: Comic, dry_run: bool = False) -> dict:
    """
    Organize a single comic - move file to library location and update state.

    Args:
        comic: The Comic model instance
        dry_run: If True, don't actually move files or update state

    Returns:
        Dict with organization results
    """
    # Physical comics have no file to move
    if comic.medium == Comic.MEDIUM_PHYSICAL:
        return {
            "success": True,
            "message": "Physical comic - no file to organize",
            "profile": None,
            "old_path": None,
            "new_path": None,
            "moved": False,
            "dry_run": dry_run,
        }

    # Check state
    if comic.state != Comic.STATE_DEDUPLICATED:
        return {
            "success": False,
            "message": f"Comic must be in 'deduplicated' state, but is '{comic.state}'",
            "profile": None,
            "old_path": comic.file_path,
            "new_path": None,
            "moved": False,
            "dry_run": dry_run,
        }

    # Duplicate gate: block comics marked as duplicates
    if comic.is_duplicate:
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

    # Find matching profile
    profile = find_matching_profile(comic)

    if profile is None:
        # Use fallback path if no profile matches
        folder_path, filename = generate_fallback_path(comic)
        profile_name = "(fallback)"
    else:
        folder_path, filename = generate_paths(comic, profile)
        profile_name = profile.name

    # Build full destination path
    old_path = comic.file_path
    file_ext = os.path.splitext(old_path)[1]  # .cbz, .cbr, etc.
    new_folder = os.path.join(LIBRARY_BASE, folder_path)
    new_path = os.path.join(new_folder, filename + file_ext)

    # Check if destination already exists (avoid overwrite)
    if os.path.exists(new_path) and os.path.abspath(old_path) != os.path.abspath(new_path):
        # Add unique suffix
        base_name = filename
        counter = 1
        while os.path.exists(new_path):
            new_path = os.path.join(new_folder, f"{base_name}_{counter}{file_ext}")
            counter += 1

    # Perform the move (or simulate)
    moved = False
    error = None

    if not dry_run:
        try:
            # Create destination directory
            os.makedirs(new_folder, exist_ok=True)

            # Move the file
            if os.path.abspath(old_path) != os.path.abspath(new_path):
                shutil.move(old_path, new_path)
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
                comic.state = Comic.STATE_ORGANIZED
                comic.save()

        except Exception as e:
            error = str(e)
            return {
                "success": False,
                "message": f"Failed to move file: {error}",
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


def generate_fallback_path(comic: Comic) -> tuple[str, str]:
    """
    Generate a fallback path when no profile matches.

    Returns:
        Tuple of (folder_path, filename)
    """
    # Simple fallback: Publisher/Series (Volume)/
    publisher = comic.publisher or "Unknown Publisher"
    series = comic.series or "Unknown Series"
    volume = comic.volume

    # Sanitize for filesystem
    publisher = sanitize_segment(publisher)
    series = sanitize_segment(series)

    if volume:
        folder = f"{publisher}/{series} ({volume})"
    else:
        folder = f"{publisher}/{series}"

    # Filename: Series #Number (Year)
    number = comic.number or ""
    year = comic.year or ""

    if number and year:
        filename = f"{series} #{number} ({year})"
    elif number:
        filename = f"{series} #{number}"
    else:
        filename = series

    filename = sanitize_segment(filename)

    return (folder, filename)


def sanitize_segment(text: str) -> str:
    """Sanitize a path segment for the filesystem."""
    # Replace illegal characters
    replacements = {
        ':': ' - ',
        '/': '',
        '\\': '',
        '<': '[',
        '>': ']',
        '|': '!',
        '"': "'",
        '*': '',
        '?': '',
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)

    # Collapse multiple spaces
    import re
    text = re.sub(r' +', ' ', text)

    return text.strip()


def organize_all_comics(dry_run: bool = False) -> dict:
    """
    Batch organize all comics in 'deduplicated' state.

    Args:
        dry_run: If True, don't actually move files

    Returns:
        Dict with batch results
    """
    comics = Comic.objects.filter(
        state=Comic.STATE_DEDUPLICATED,
        medium=Comic.MEDIUM_DIGITAL,
    )
    total_count = comics.count()

    if total_count == 0:
        return {
            "success": True,
            "message": "No comics in 'deduplicated' state to organize",
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

    # Generate paths
    if selected_profile:
        folder_path, filename = generate_paths(comic, selected_profile)
        profile_name = selected_profile.name
    else:
        folder_path, filename = generate_fallback_path(comic)
        profile_name = "(fallback)"

    # Build full paths
    old_path = comic.file_path
    file_ext = os.path.splitext(old_path)[1] if old_path else ".cbz"
    new_folder = os.path.join(LIBRARY_BASE, folder_path)
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
