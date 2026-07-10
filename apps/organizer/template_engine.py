"""
Library Organizer Template Engine - Renders folder/file templates with comic metadata.

Template Syntax:
- {<field>} - Field value without prefix space
- { <field>} - Field value with leading space (omitted if field is empty)
- {#<number3>} - Number with # prefix, padded to 3 digits
- {<volume0>} - Volume with 0 default if empty
- {<Custom(X)>} - Custom value with key X
- {<month>} - Month converted to name via months mapping
- Conditional segments: { - (<storyarc>{ <altNumber2>})} - renders only if storyarc exists
"""

import re
from typing import Any

from apps.core.models import Comic

from .models import OrganizerProfile


# Field name mapping from template placeholders to Comic model
TEMPLATE_FIELD_MAP = {
    # Direct model fields
    "series": "series",
    "title": "title",
    "number": "number",
    "volume": "volume",
    "year": "year",
    "month": "month",
    "day": "day",
    "publisher": "publisher",
    "format": "format",
    "genre": "genre",
    "writer": "writer",
    "penciller": "penciller",
    "inker": "inker",
    "colorist": "colorist",
    "letterer": "letterer",
    "coverartist": "cover_artist",
    "editor": "editor",
    "summary": "summary",
    "notes": "notes",
    "characters": "characters",
    "web": "web",
    "count": "count",

    # Special mapped fields
    "seriesgroup": "series_group",
    "maincharacter": "main_character_or_team",
    "maincharacterorteam": "main_character_or_team",
    "storyarc": "_storyarc",
    "altnumber": "_altnumber",
    "startyear": "_startyear",
}


def render_template(template: str, comic: Comic, profile: OrganizerProfile) -> str:
    """
    Render a template string with comic metadata.

    Args:
        template: The template string (folder or file template)
        comic: The Comic model instance
        profile: The OrganizerProfile (for months mapping, etc.)

    Returns:
        The rendered path string
    """
    result = template

    # Replace backslashes with forward slashes for path normalization
    result = result.replace('\\', '/')

    # Process nested conditional segments first (innermost to outermost)
    result = process_conditional_segments(result, comic, profile)

    # Process remaining simple placeholders
    result = process_simple_placeholders(result, comic, profile)

    # Clean up the path
    result = clean_path(result, profile)

    return result


def process_conditional_segments(template: str, comic: Comic, profile: OrganizerProfile) -> str:
    """
    Process conditional segments that only render if their main field has a value.

    Pattern: { - (<storyarc>{ <altNumber2>})}
    This renders " - (storyarc altNumber)" only if storyarc has a value.

    Uses balanced brace matching to handle nested segments correctly.
    """
    result = template

    max_iterations = 20  # Prevent infinite loops
    iteration = 0

    while iteration < max_iterations:
        # Find the innermost { that contains a <field> pattern
        # Work from innermost to outermost to handle nesting correctly

        best_match = None
        best_start = -1

        # Find all opening braces and check if they contain a field placeholder
        i = 0
        while i < len(result):
            if result[i] == '{':
                # Find matching closing brace
                depth = 1
                j = i + 1
                while j < len(result) and depth > 0:
                    if result[j] == '{':
                        depth += 1
                    elif result[j] == '}':
                        depth -= 1
                    j += 1

                if depth == 0:
                    segment = result[i:j]
                    # Check if this segment has a direct field (not nested in another brace)
                    # Pattern: {prefix<field>suffix} where prefix doesn't contain {
                    inner = segment[1:-1]  # Remove outer braces

                    # Check if this is a direct field reference (no nested { before the <)
                    field_match = re.match(r'^([^{<]*)<([^>]+)>(.*)$', inner, re.DOTALL)
                    if field_match:
                        prefix = field_match.group(1)
                        # Only process if prefix doesn't contain unbalanced braces
                        if '{' not in prefix:
                            # This is an innermost field - process it
                            if best_start == -1 or i > best_start:
                                best_match = (i, j, field_match.group(1), field_match.group(2), field_match.group(3))
                                best_start = i
            i += 1

        if best_match is None:
            break

        start, end, prefix, field_spec, suffix = best_match

        # Get the field value
        value = get_placeholder_value(comic, field_spec, profile)

        if value:
            # Field has value - render this segment
            illegal = profile.illegal_characters or OrganizerProfile.get_default_illegal_characters()
            slash_repl = illegal.get('/', '-')
            value = value.replace('/', slash_repl)
            replacement = f"{prefix}{value}{suffix}"
        else:
            # Field is empty - remove entire segment
            replacement = ""

        result = result[:start] + replacement + result[end:]
        iteration += 1

    return result


def process_simple_placeholders(template: str, comic: Comic, profile: OrganizerProfile) -> str:
    """
    Process simple placeholders: {<field>} or { <field>}
    """
    result = template

    # Pattern for placeholders: {<field>} or { <field>} or {#<number3>}
    pattern = r'\{([^<]*)<([^>]+)>\}'

    def replace_placeholder(match):
        prefix = match.group(1)  # Space or # or other prefix
        field_spec = match.group(2)  # Field name with optional modifiers

        value = get_placeholder_value(comic, field_spec, profile)

        if value:
            illegal = profile.illegal_characters or OrganizerProfile.get_default_illegal_characters()
            slash_repl = illegal.get('/', '-')
            value = value.replace('/', slash_repl)
            return f"{prefix}{value}"
        else:
            # Empty value - return empty (removes prefix too)
            return ""

    result = re.sub(pattern, replace_placeholder, result)

    return result


def get_placeholder_value(comic: Comic, field_spec: str, profile: OrganizerProfile) -> str:
    """
    Get the value for a placeholder field specification.

    Handles:
    - Simple fields: series, publisher, format
    - Padded numbers: number3, number2 (padded to N digits)
    - Default values: volume0 (use 0 if empty)
    - Month conversion: month (converts to name)
    - Custom fields: Custom(X)
    - Indexed list fields: writer[1] (first writer), writer[2] (second writer)
    - Name parts: writer[1][f] (first name), writer[1][l] (last name)
    """
    # Check for Custom(X) syntax
    if field_spec.startswith("Custom(") and field_spec.endswith(")"):
        custom_key = field_spec[7:-1]
        return comic.custom_values.get(custom_key, "")

    # Check for index/name-part syntax: field[N] or field[N][f] or field[N][l]
    index_match = re.match(r'^(.+?)\[(\d+)\](?:\[([fl])\])?$', field_spec)
    if index_match:
        base_field = index_match.group(1)
        index = int(index_match.group(2)) - 1  # 1-based to 0-based
        name_part = index_match.group(3)  # 'f', 'l', or None
        full_value = get_simple_value(comic, base_field, profile)
        items = [v.strip() for v in full_value.split(",") if v.strip()]
        if index < 0 or index >= len(items):
            return ""
        selected = items[index]
        if name_part == "f":
            return selected.split()[0] if selected.split() else selected
        if name_part == "l":
            return selected.split()[-1] if selected.split() else selected
        return selected

    # Check for padding suffix (number3, altNumber2, volume0, etc.)
    padding_match = re.match(r'^(.+?)(\d+)$', field_spec)
    if padding_match:
        base_field = padding_match.group(1)
        pad_width = int(padding_match.group(2))
        return get_padded_value(comic, base_field, pad_width, profile)

    # Simple field lookup
    return get_simple_value(comic, field_spec, profile)


def get_simple_value(comic: Comic, field: str, profile: OrganizerProfile) -> str:
    """Get a simple field value without padding."""
    field_lower = field.lower()

    # Map field name to model attribute
    model_attr = TEMPLATE_FIELD_MAP.get(field_lower)

    # Special cases
    if field_lower == "month":
        # Convert month number to name
        month_val = comic.month
        if month_val:
            months_map = profile.months or OrganizerProfile.get_default_months()
            return months_map.get(str(month_val), str(month_val))
        return ""

    if model_attr == "_storyarc":
        return comic.story_arc or ""

    if model_attr == "_altnumber":
        return comic.custom_values.get("AlternateNumber", "")

    if model_attr == "_startyear":
        return comic.custom_values.get("StartYear", str(comic.year or ""))

    if model_attr:
        value = getattr(comic, model_attr, None)
        if value is not None:
            return str(value)
        return ""

    # Check custom_values as fallback
    return comic.custom_values.get(field, "")


def _pad_number(value: Any, pad_width: int) -> str:
    """Zero-pad the leading integer of an issue number, preserving any decimal or suffix.

    Examples: '23.1' -> '023.1', '7' -> '007', '0' -> '000', '1.MU' -> '001.MU'.
    Values with no leading integer (e.g. '½') are returned unchanged.
    """
    if not value:
        return ""
    value = str(value).strip()
    match = re.match(r"^(\d+)(.*)$", value)
    if match:
        return match.group(1).zfill(pad_width) + match.group(2)
    return value


def get_padded_value(comic: Comic, field: str, pad_width: int, profile: OrganizerProfile) -> str:
    """Get a field value with padding/default handling."""
    field_lower = field.lower()

    # volume0 means use 0 as default if empty
    if field_lower == "volume":
        value = comic.volume
        if value is None:
            # Check if suffix was 0 (meaning use 0 as default)
            return "0" if pad_width == 0 else ""
        return str(value)

    # For number fields, pad with zeros while preserving any decimal/suffix part
    if field_lower == "number":
        return _pad_number(comic.number, pad_width)

    if field_lower == "altnumber":
        return _pad_number(comic.custom_values.get("AlternateNumber", ""), pad_width)

    # Default behavior for other fields
    return get_simple_value(comic, field, profile)


def clean_path(path: str, profile: OrganizerProfile) -> str:
    """
    Clean up a rendered path:
    - Apply illegal character replacements to each segment
    - Remove empty path segments
    - Collapse multiple spaces
    - Trim whitespace
    """
    # Get illegal character replacements (excluding / which is our path separator)
    illegal_chars = profile.illegal_characters or OrganizerProfile.get_default_illegal_characters()
    # Don't replace / in segments - it's our path separator
    segment_illegal_chars = {k: v for k, v in illegal_chars.items() if k != '/'}

    # Clean up path segments
    segments = path.split('/')
    cleaned_segments = []

    for segment in segments:
        # Apply illegal character replacements to the segment
        for char, replacement in segment_illegal_chars.items():
            segment = segment.replace(char, replacement)

        # Replace multiple spaces with single space (if enabled)
        if profile.replace_multiple_spaces:
            segment = re.sub(r' +', ' ', segment)

        # Trim whitespace
        segment = segment.strip()

        # Skip empty segments
        if not segment:
            continue

        # Remove segments that are just punctuation/spaces
        if re.match(r'^[\s\-\(\)\[\]\.]+$', segment):
            continue

        cleaned_segments.append(segment)

    return '/'.join(cleaned_segments)


def sanitize_filename(filename: str, profile: OrganizerProfile) -> str:
    """
    Sanitize a filename for the filesystem.

    Args:
        filename: The rendered filename
        profile: The OrganizerProfile for settings

    Returns:
        Sanitized filename safe for the filesystem
    """
    result = filename

    # Apply illegal character replacements
    illegal_chars = profile.illegal_characters or OrganizerProfile.get_default_illegal_characters()
    for char, replacement in illegal_chars.items():
        result = result.replace(char, replacement)

    # Replace multiple spaces
    if profile.replace_multiple_spaces:
        result = re.sub(r' +', ' ', result)

    # Trim whitespace
    result = result.strip()

    # Ensure we have a valid filename
    if not result:
        result = "unnamed"

    return result


def generate_paths(comic: Comic, profile: OrganizerProfile) -> tuple[str, str]:
    """
    Generate the full folder and file paths for a comic.

    Args:
        comic: The Comic model instance
        profile: The OrganizerProfile to use

    Returns:
        Tuple of (folder_path, filename) without file extension
    """
    folder_path = render_template(profile.folder_template, comic, profile)
    filename = render_template(profile.file_template, comic, profile)

    # Sanitize filename
    filename = sanitize_filename(filename, profile)

    return (folder_path, filename)
