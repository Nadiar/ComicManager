"""
Library Organizer Engine - Rule matching logic for profiles.
"""

from apps.core.models import Comic

from .models import OrganizerProfile


# Field name mapping from .lop format to Comic model
FIELD_MAP = {
    # Direct model fields
    "Series": "series",
    "Title": "title",
    "Number": "number",
    "Volume": "volume",
    "Year": "year",
    "Month": "month",
    "Publisher": "publisher",
    "Format": "format",
    "Genre": "genre",
    "Writer": "writer",
    "Penciller": "penciller",
    "Inker": "inker",
    "Colorist": "colorist",
    "Letterer": "letterer",
    "Cover Artist": "cover_artist",
    "Editor": "editor",
    "Summary": "summary",
    "Notes": "notes",
    "Characters": "characters",
    "Web": "web",

    # Special mapped fields
    "Series Group": "series_group",
    "SeriesGroup": "series_group",
    "Main Character Or Team": "main_character_or_team",
    "MainCharacterOrTeam": "main_character_or_team",
    "Main Character": "main_character_or_team",

    # Tags field - standard model field
    "Tags": "tags",

    # Numeric fields
    "Count": "count",
    "Page Count": "page_count",
}

# Fields that support numeric comparison operators
NUMERIC_FIELDS = {"Count", "Page Count", "Volume", "Year", "Month"}


def matches_profile(comic: Comic, profile: OrganizerProfile) -> bool:
    """
    Check if a comic matches a profile's ExcludeRules.

    The ExcludeMode determines how matching works:
    - "Only": Profile ONLY processes comics that MATCH the rules
    - "Do not": Profile processes comics that DO NOT match the rules

    Args:
        comic: The Comic model instance
        profile: The OrganizerProfile to check

    Returns:
        True if the comic should be processed by this profile
    """
    rules = profile.exclude_rules

    if not rules or not rules.get("rules"):
        # No rules = matches everything
        return True

    mode = rules.get("mode", "Only")
    operator = rules.get("operator", "All")

    # Evaluate all top-level rules
    rule_results = [evaluate_rule_item(comic, rule) for rule in rules.get("rules", [])]

    # Combine results based on operator
    if operator == "All":
        matches = all(rule_results) if rule_results else True
    else:  # "Any"
        matches = any(rule_results) if rule_results else False

    # Apply mode
    if mode == "Only":
        return matches
    else:  # "Do not"
        return not matches


def evaluate_rule_item(comic: Comic, rule_item: dict) -> bool:
    """
    Evaluate a single rule item (either a rule or a group).

    Args:
        comic: The Comic model instance
        rule_item: Dict with type="rule" or type="group"

    Returns:
        True if the rule/group matches
    """
    item_type = rule_item.get("type", "rule")

    if item_type == "group":
        return evaluate_group(comic, rule_item)
    else:
        return evaluate_single_rule(comic, rule_item)


def evaluate_group(comic: Comic, group: dict) -> bool:
    """
    Evaluate a group of rules with AND/OR logic.

    Args:
        comic: The Comic model instance
        group: Dict with operator and rules list

    Returns:
        True if the group matches
    """
    operator = group.get("operator", "All")
    rules = group.get("rules", [])

    if not rules:
        return True

    results = [evaluate_rule_item(comic, rule) for rule in rules]

    if operator == "All":
        return all(results)
    else:  # "Any"
        return any(results)


def evaluate_single_rule(comic: Comic, rule: dict) -> bool:
    """
    Evaluate a single rule against a comic.

    Args:
        comic: The Comic model instance
        rule: Dict with field, operator, value

    Returns:
        True if the rule matches
    """
    field_name = rule.get("field", "")
    operator = rule.get("operator", "is")
    rule_value = rule.get("value", "")

    # Get the comic field value
    comic_value = get_field_value(comic, field_name)

    # Normalize to lowercase for comparison
    comic_value_lower = (comic_value or "").lower()
    rule_value_lower = rule_value.lower()

    # Numeric comparison operators
    if operator in ("greater than", "less than", "greater than or equal to", "less than or equal to"):
        try:
            comic_num = float(comic_value) if comic_value else 0
            rule_num = float(rule_value) if rule_value else 0
        except (ValueError, TypeError):
            return False
        if operator == "greater than":
            return comic_num > rule_num
        elif operator == "less than":
            return comic_num < rule_num
        elif operator == "greater than or equal to":
            return comic_num >= rule_num
        else:  # less than or equal to
            return comic_num <= rule_num

    # Apply operator
    if operator == "is":
        return comic_value_lower == rule_value_lower

    elif operator == "contains":
        return rule_value_lower in comic_value_lower

    elif operator == "does not contain":
        return rule_value_lower not in comic_value_lower

    elif operator == "starts with":
        return comic_value_lower.startswith(rule_value_lower)

    elif operator == "ends with":
        return comic_value_lower.endswith(rule_value_lower)

    elif operator == "is not":
        return comic_value_lower != rule_value_lower

    else:
        # Unknown operator - default to no match
        return False


def get_field_value(comic: Comic, field_name: str) -> str:
    """
    Get the value of a field from a comic for rule matching.

    Args:
        comic: The Comic model instance
        field_name: The field name from the .lop file

    Returns:
        String value of the field (empty string if not found)
    """
    # Map field name to model attribute
    model_attr = FIELD_MAP.get(field_name)

    if model_attr:
        value = getattr(comic, model_attr, None)
        return str(value) if value is not None else ""

    # Check if it's a Custom field reference
    if field_name.startswith("Custom(") and field_name.endswith(")"):
        custom_key = field_name[7:-1]  # Extract key from Custom(X)
        return comic.custom_values.get(custom_key, "")

    # Fall back to custom_values lookup
    return comic.custom_values.get(field_name, "")


def find_matching_profile(comic: Comic) -> OrganizerProfile | None:
    """
    Find the first enabled profile that matches the comic.

    Profiles are evaluated in priority order (lower priority = evaluated first).

    Args:
        comic: The Comic model instance

    Returns:
        The matching OrganizerProfile or None if no match
    """
    profiles = OrganizerProfile.objects.filter(is_enabled=True).order_by('priority')

    for profile in profiles:
        if matches_profile(comic, profile):
            return profile

    return None


def preview_profile_matches(comic: Comic) -> list[dict]:
    """
    Preview which profiles would match a comic.

    Args:
        comic: The Comic model instance

    Returns:
        List of dicts with profile info and match status
    """
    profiles = OrganizerProfile.objects.filter(is_enabled=True).order_by('priority')

    results = []
    first_match_found = False

    for profile in profiles:
        matches = matches_profile(comic, profile)
        is_selected = matches and not first_match_found

        results.append({
            "profile_id": profile.id,
            "profile_name": profile.name,
            "priority": profile.priority,
            "matches": matches,
            "is_selected": is_selected,  # First matching profile
        })

        if matches and not first_match_found:
            first_match_found = True

    return results
