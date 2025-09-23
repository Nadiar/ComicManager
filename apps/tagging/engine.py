"""
DataManager Rule Matching and Action Execution Engine.

Supports all 17 rule modifiers and 8 action modifiers from ComicRack's DataManager.
"""

import re
from typing import Any

from apps.core.models import Comic

from .models import DataManagerRuleset


# ============================================================================
# Field Mapping: DataManager field names -> Comic model attributes
# ============================================================================

FIELD_MAP = {
    # Core metadata fields (direct model attributes)
    "Series": "series",
    "Title": "title",
    "Publisher": "publisher",
    "Writer": "writer",
    "Format": "format",
    "Volume": "volume",
    "Notes": "notes",
    "Number": "number",
    "Year": "year",
    # Organizational fields (direct model attributes)
    "SeriesGroup": "series_group",
    "MainCharacterOrTeam": "main_character_or_team",
    # Custom values (stored in custom_values JSONField)
    "First Series": ("custom_values", "First Series"),
    "Second Series": ("custom_values", "Second Series"),
    "IsStarWars": ("custom_values", "IsStarWars"),
    "BBY": ("custom_values", "BBY"),
    "Tags": ("custom_values", "Tags"),
    "SW": ("custom_values", "SW"),
    "Universe": ("custom_values", "Universe"),
    "comicvine_issue": ("custom_values", "comicvine_issue"),
    "comicvine_volume": ("custom_values", "comicvine_volume"),
    "DataManager_Processed": ("custom_values", "DataManager_Processed"),
    "Datamanager_processed": ("custom_values", "Datamanager_processed"),
    "ADs": ("custom_values", "ADs"),
    "Review": ("custom_values", "Review"),
    "SeriesComplete": ("custom_values", "SeriesComplete"),
    # File-based fields (read-only for rules, not settable via actions)
    "FileName": "file_path",
    "Original Format": "original_format",
}


def get_comic_field_value(comic: Comic, field_name: str) -> str:
    """
    Get the value of a field from a Comic object.

    Args:
        comic: The Comic model instance
        field_name: The DataManager field name

    Returns:
        The field value as a string, or empty string if not found
    """
    mapping = FIELD_MAP.get(field_name)

    if mapping is None:
        # Unknown field - check custom_values as fallback
        return str(comic.custom_values.get(field_name, ""))

    if isinstance(mapping, tuple):
        # Custom value field: ("custom_values", "key")
        _, key = mapping
        return str(comic.custom_values.get(key, ""))

    # Direct model attribute
    value = getattr(comic, mapping, None)
    return str(value) if value is not None else ""


def set_comic_field_value(comic: Comic, field_name: str, value: str) -> bool:
    """
    Set the value of a field on a Comic object.

    Args:
        comic: The Comic model instance
        field_name: The DataManager field name
        value: The value to set

    Returns:
        True if the field was set, False if the field is read-only or unknown
    """
    mapping = FIELD_MAP.get(field_name)

    if mapping is None:
        # Unknown field - store in custom_values
        comic.custom_values[field_name] = value
        return True

    if isinstance(mapping, tuple):
        # Custom value field: ("custom_values", "key")
        _, key = mapping
        comic.custom_values[key] = value
        return True

    # Direct model attribute - check if writable
    if mapping in ("file_path",):  # Read-only fields
        return False

    setattr(comic, mapping, value if value else None)
    return True


# ============================================================================
# Rule Modifiers - Match conditions against comic field values
# ============================================================================


def split_pipe_values(value: str) -> list[str]:
    """Split a pipe-delimited value string into a list of values."""
    return [v.strip() for v in value.split("||") if v.strip()]


def match_is(field_value: str, rule_value: str) -> bool:
    """Exact match (case-insensitive)."""
    return field_value.lower() == rule_value.lower()


def match_is_any_of(field_value: str, rule_value: str) -> bool:
    """Match any of the pipe-delimited values (case-insensitive)."""
    values = split_pipe_values(rule_value)
    field_lower = field_value.lower()
    return any(field_lower == v.lower() for v in values)


def match_not(field_value: str, rule_value: str) -> bool:
    """Exact inequality (case-insensitive)."""
    return field_value.lower() != rule_value.lower()


def match_contains(field_value: str, rule_value: str) -> bool:
    """Substring match (case-insensitive)."""
    return rule_value.lower() in field_value.lower()


def match_contains_any_of(field_value: str, rule_value: str) -> bool:
    """Match if field contains any of the pipe-delimited values (case-insensitive)."""
    values = split_pipe_values(rule_value)
    field_lower = field_value.lower()
    return any(v.lower() in field_lower for v in values)


def match_not_contains(field_value: str, rule_value: str) -> bool:
    """Negative substring match (case-insensitive)."""
    return rule_value.lower() not in field_value.lower()


def match_not_contains_any_of(field_value: str, rule_value: str) -> bool:
    """Match if field does not contain any of the pipe-delimited values."""
    values = split_pipe_values(rule_value)
    field_lower = field_value.lower()
    return not any(v.lower() in field_lower for v in values)


def match_starts_with(field_value: str, rule_value: str) -> bool:
    """Prefix match (case-insensitive)."""
    return field_value.lower().startswith(rule_value.lower())


def match_starts_with_any_of(field_value: str, rule_value: str) -> bool:
    """Match if field starts with any of the pipe-delimited values."""
    values = split_pipe_values(rule_value)
    field_lower = field_value.lower()
    return any(field_lower.startswith(v.lower()) for v in values)


def match_not_starts_with(field_value: str, rule_value: str) -> bool:
    """Negative prefix match (case-insensitive)."""
    return not field_value.lower().startswith(rule_value.lower())


def match_regex(field_value: str, rule_value: str) -> bool:
    """Regular expression match."""
    try:
        pattern = re.compile(rule_value, re.IGNORECASE)
        return bool(pattern.search(field_value))
    except re.error:
        return False


def match_not_regex(field_value: str, rule_value: str) -> bool:
    """Negative regular expression match."""
    try:
        pattern = re.compile(rule_value, re.IGNORECASE)
        return not bool(pattern.search(field_value))
    except re.error:
        return True  # If regex is invalid, consider it not matching


# Modifier dispatch table
RULE_MODIFIERS = {
    "Is": match_is,
    "IsAnyOf": match_is_any_of,
    "Not": match_not,
    "Contains": match_contains,
    "ContainsAnyOf": match_contains_any_of,
    "NotContains": match_not_contains,
    "NotContainsAnyOf": match_not_contains_any_of,
    "StartsWith": match_starts_with,
    "StartsWithAnyOf": match_starts_with_any_of,
    "NotStartsWith": match_not_starts_with,
    "RegEx": match_regex,
    "NotRegEx": match_not_regex,
}


def evaluate_rule(comic: Comic, rule: dict) -> bool:
    """
    Evaluate a single rule against a comic.

    Args:
        comic: The Comic model instance
        rule: Dict with "field", "modifier", "value" keys

    Returns:
        True if the rule matches, False otherwise
    """
    field_name = rule.get("field", "")
    modifier = rule.get("modifier", "")
    rule_value = rule.get("value", "")

    field_value = get_comic_field_value(comic, field_name)

    match_func = RULE_MODIFIERS.get(modifier)
    if match_func is None:
        # Unknown modifier - default to no match
        return False

    return match_func(field_value, rule_value)


def evaluate_ruleset(comic: Comic, ruleset: DataManagerRuleset) -> bool:
    """
    Evaluate all rules in a ruleset against a comic.

    Args:
        comic: The Comic model instance
        ruleset: The DataManagerRuleset instance

    Returns:
        True if the ruleset matches (based on AND/OR mode), False otherwise
    """
    if not ruleset.rules:
        return False

    results = [evaluate_rule(comic, rule) for rule in ruleset.rules]

    if ruleset.mode == DataManagerRuleset.MODE_AND:
        return all(results)
    else:  # OR mode
        return any(results)


# ============================================================================
# Action Modifiers - Apply changes to comic fields
# ============================================================================


def action_set_value(comic: Comic, field_name: str, value: str) -> str | None:
    """Set field to the specified value."""
    old_value = get_comic_field_value(comic, field_name)
    set_comic_field_value(comic, field_name, value)
    return old_value if old_value != value else None


def action_add(comic: Comic, field_name: str, value: str) -> str | None:
    """Append value to existing field (with comma separator if not empty)."""
    old_value = get_comic_field_value(comic, field_name)
    if old_value:
        new_value = f"{old_value}, {value}"
    else:
        new_value = value
    set_comic_field_value(comic, field_name, new_value)
    return old_value if old_value != new_value else None


def action_remove(comic: Comic, field_name: str, value: str) -> str | None:
    """Remove substring from field value."""
    old_value = get_comic_field_value(comic, field_name)
    new_value = old_value.replace(value, "").strip()
    # Clean up double spaces and trailing commas
    new_value = re.sub(r"\s+", " ", new_value)
    new_value = re.sub(r",\s*,", ",", new_value)
    new_value = new_value.strip(", ")
    set_comic_field_value(comic, field_name, new_value)
    return old_value if old_value != new_value else None


def action_replace(comic: Comic, field_name: str, value: str) -> str | None:
    """Replace pattern with replacement. Value format: "pattern||replacement"."""
    old_value = get_comic_field_value(comic, field_name)
    parts = value.split("||")
    if len(parts) != 2:
        return None
    pattern, replacement = parts
    new_value = old_value.replace(pattern, replacement)
    set_comic_field_value(comic, field_name, new_value)
    return old_value if old_value != new_value else None


def action_regex_var_replace(comic: Comic, field_name: str, value: str) -> str | None:
    """
    Replace using regex with named groups.

    The regex pattern can contain named groups like (?<SW>...).
    The captured value replaces the entire field.
    """
    old_value = get_comic_field_value(comic, field_name)
    try:
        # Convert Python-style named groups: (?P<name>...) is standard Python
        # but DataManager uses (?<name>...) style
        pattern = value.replace("(?<", "(?P<")
        match = re.search(pattern, old_value, re.IGNORECASE)
        if match:
            # Use the first named group's value, or the full match
            groups = match.groupdict()
            if groups:
                new_value = next(iter(groups.values()))
            else:
                new_value = match.group(0)
            set_comic_field_value(comic, field_name, new_value)
            return old_value if old_value != new_value else None
    except re.error:
        pass
    return None


def action_regex_var_append(comic: Comic, field_name: str, value: str) -> str | None:
    """
    Append captured regex group value to field.

    Similar to RegExVarReplace but appends instead of replacing.
    """
    old_value = get_comic_field_value(comic, field_name)
    try:
        pattern = value.replace("(?<", "(?P<")
        # The pattern should be applied to the field itself
        match = re.search(pattern, old_value, re.IGNORECASE)
        if match:
            groups = match.groupdict()
            if groups:
                captured = next(iter(groups.values()))
                new_value = f"{old_value}, {captured}" if old_value else captured
                set_comic_field_value(comic, field_name, new_value)
                return old_value if old_value != new_value else None
    except re.error:
        pass
    return None


# Action modifier dispatch table
ACTION_MODIFIERS = {
    "SetValue": action_set_value,
    "Add": action_add,
    "Remove": action_remove,
    "Replace": action_replace,
    "RegExVarReplace": action_regex_var_replace,
    "RegExVarAppend": action_regex_var_append,
}


def apply_action(comic: Comic, action: dict) -> dict | None:
    """
    Apply a single action to a comic.

    Args:
        comic: The Comic model instance
        action: Dict with "field", "modifier", "value" keys

    Returns:
        Dict with change info if a change was made, None otherwise
    """
    field_name = action.get("field", "")
    modifier = action.get("modifier", "")
    action_value = action.get("value", "")

    action_func = ACTION_MODIFIERS.get(modifier)
    if action_func is None:
        return None

    old_value = action_func(comic, field_name, action_value)

    if old_value is not None:
        return {
            "field": field_name,
            "old_value": old_value,
            "new_value": get_comic_field_value(comic, field_name),
            "modifier": modifier,
        }
    return None


def apply_ruleset_actions(comic: Comic, ruleset: DataManagerRuleset) -> list[dict]:
    """
    Apply all actions from a ruleset to a comic.

    Args:
        comic: The Comic model instance
        ruleset: The DataManagerRuleset instance

    Returns:
        List of change dicts for each field that was modified
    """
    changes = []
    for action in ruleset.actions:
        change = apply_action(comic, action)
        if change:
            change["ruleset_name"] = ruleset.name
            change["ruleset_id"] = ruleset.id
            changes.append(change)
    return changes


# ============================================================================
# Main Entry Points
# ============================================================================


def find_matching_rulesets(comic: Comic) -> list[DataManagerRuleset]:
    """
    Find all rulesets that match a comic.

    Args:
        comic: The Comic model instance

    Returns:
        List of matching DataManagerRuleset instances, in priority order
    """
    rulesets = DataManagerRuleset.objects.filter(is_enabled=True).order_by("priority")
    return [rs for rs in rulesets if evaluate_ruleset(comic, rs)]


def apply_datamanager_rules(comic: Comic, save: bool = True) -> dict:
    """
    Apply ALL matching DataManager rulesets to a comic (cascading).

    Rules are evaluated in priority order. Each rule is evaluated against
    the CURRENT state of the comic (after previous rules have been applied).
    This means later rules see the changes made by earlier rules.

    Args:
        comic: The Comic model instance
        save: Whether to save the comic after applying rules

    Returns:
        Dict with:
        - "matched_rulesets": List of ruleset names that matched
        - "changes": List of all field changes made
        - "comic": The modified comic instance
    """
    rulesets = DataManagerRuleset.objects.filter(is_enabled=True).order_by("priority")
    matched_names = []
    all_changes = []

    for ruleset in rulesets:
        # Evaluate against CURRENT state (after previous rules applied)
        if evaluate_ruleset(comic, ruleset):
            matched_names.append(ruleset.name)
            changes = apply_ruleset_actions(comic, ruleset)
            all_changes.extend(changes)

    if save and all_changes:
        comic.save()

    return {
        "matched_rulesets": matched_names,
        "matched_count": len(matched_names),
        "changes": all_changes,
        "changes_count": len(all_changes),
        "comic": comic,
    }


def preview_matching_rules(comic: Comic) -> list[dict]:
    """
    Preview which rules would match a comic without applying changes.

    Args:
        comic: The Comic model instance

    Returns:
        List of dicts with ruleset info and what would change
    """
    matched = find_matching_rulesets(comic)
    preview = []

    for ruleset in matched:
        # Create a copy to preview changes without modifying original
        preview_changes = []
        for action in ruleset.actions:
            field_name = action.get("field", "")
            current_value = get_comic_field_value(comic, field_name)
            preview_changes.append({
                "field": field_name,
                "current_value": current_value,
                "action": action.get("modifier"),
                "new_value": action.get("value"),
            })

        preview.append({
            "ruleset_id": ruleset.id,
            "ruleset_name": ruleset.name,
            "group_path": ruleset.group_path,
            "mode": ruleset.mode,
            "rule_count": ruleset.rule_count,
            "changes": preview_changes,
        })

    return preview
