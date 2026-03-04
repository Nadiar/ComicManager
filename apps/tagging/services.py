"""
Tagging Service - Applies DataManager rules and manages state transitions.
"""

from django.db import transaction

from apps.core.models import Comic

from .engine import apply_datamanager_rules, preview_matching_rules
from .models import DataManagerRuleset


def tag_comic(comic: Comic) -> dict:
    """
    Apply DataManager rules to a comic and transition state from 'counted' to 'tagged'.

    Args:
        comic: The Comic model instance

    Returns:
        Dict with:
        - "success": Whether the operation succeeded
        - "message": Human-readable status message
        - "matched_rulesets": List of ruleset names that matched
        - "changes": List of field changes made
    """
    if comic.state != Comic.STATE_COUNTED:
        return {
            "success": False,
            "message": f"Comic must be in 'counted' state, but is '{comic.state}'",
            "matched_rulesets": [],
            "changes": [],
        }

    with transaction.atomic():
        result = apply_datamanager_rules(comic, save=False)

        # Mark as processed by DataManager
        comic.custom_values["DataManager_Processed"] = "Yes"

        # Clear unknown_publisher if this publisher is now covered by a ruleset
        if comic.publisher and comic.has_flag("unknown_publisher"):
            from .engine import is_publisher_known
            if is_publisher_known(comic.publisher):
                comic.remove_flag("unknown_publisher")

        # Transition state
        comic.state = Comic.STATE_TAGGED
        comic.save()

    matched_count = result["matched_count"]
    changes_count = result["changes_count"]

    if matched_count > 0:
        message = f"Applied {matched_count} ruleset(s), made {changes_count} change(s)"
    else:
        message = "No matching rulesets found, state advanced to tagged"

    return {
        "success": True,
        "message": message,
        "matched_rulesets": result["matched_rulesets"],
        "changes": result["changes"],
    }


def tag_all_comics() -> dict:
    """
    Batch process all comics in 'counted' state.

    Returns:
        Dict with:
        - "success": Whether the operation succeeded
        - "total_processed": Number of comics processed
        - "total_matched": Number of comics with at least one matching ruleset
        - "total_changes": Total number of field changes made
    """
    comics = Comic.objects.filter(state=Comic.STATE_COUNTED)
    total_count = comics.count()

    if total_count == 0:
        return {
            "success": True,
            "message": "No comics in 'counted' state to process",
            "total_processed": 0,
            "total_matched": 0,
            "total_changes": 0,
        }

    processed = 0
    matched = 0
    total_changes = 0

    for comic in comics:
        result = tag_comic(comic)
        processed += 1
        if result["matched_rulesets"]:
            matched += 1
        total_changes += len(result["changes"])

    return {
        "success": True,
        "message": f"Processed {processed} comics, {matched} had matching rules, {total_changes} total changes",
        "total_processed": processed,
        "total_matched": matched,
        "total_changes": total_changes,
    }


def preview_tagging(comic: Comic) -> dict:
    """
    Preview which DataManager rules would match a comic without applying changes.

    Args:
        comic: The Comic model instance

    Returns:
        Dict with:
        - "comic_id": UUID of the comic
        - "comic_str": String representation of the comic
        - "current_state": Current workflow state
        - "matched_rulesets": List of matching ruleset info with potential changes
    """
    preview = preview_matching_rules(comic)

    return {
        "comic_id": str(comic.id),
        "comic_str": str(comic),
        "current_state": comic.state,
        "matched_count": len(preview),
        "matched_rulesets": preview,
    }


def get_tagging_stats() -> dict:
    """
    Get statistics about tagging state and ruleset coverage.

    Returns:
        Dict with counts and percentages
    """
    total_rulesets = DataManagerRuleset.objects.count()
    enabled_rulesets = DataManagerRuleset.objects.filter(is_enabled=True).count()

    counted_comics = Comic.objects.filter(state=Comic.STATE_COUNTED).count()
    tagged_comics = Comic.objects.filter(state=Comic.STATE_TAGGED).count()

    # Count rulesets by top-level group
    groups = {}
    for rs in DataManagerRuleset.objects.filter(is_enabled=True):
        top_group = rs.top_level_group or "(ungrouped)"
        groups[top_group] = groups.get(top_group, 0) + 1

    return {
        "total_rulesets": total_rulesets,
        "enabled_rulesets": enabled_rulesets,
        "disabled_rulesets": total_rulesets - enabled_rulesets,
        "pending_tagging": counted_comics,
        "already_tagged": tagged_comics,
        "rulesets_by_group": groups,
    }
