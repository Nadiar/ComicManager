"""
Tagging Service - Applies DataManager rules and manages state transitions.
"""

from django.db import transaction

from apps.core.models import Comic

from .engine import apply_datamanager_rules, preview_matching_rules
from .models import DataManagerRuleset








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
