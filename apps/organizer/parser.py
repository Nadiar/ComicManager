"""
Library Organizer Parser - Imports .lop XML files from ComicRack.
"""

import re
import xml.etree.ElementTree as ET
from html import unescape
from typing import Any

from django.db import transaction

from .models import OrganizerProfile


def parse_lop_file(file_path: str) -> list[dict]:
    """
    Parse a .lop XML file and return list of profile dicts.

    Args:
        file_path: Path to the .lop XML file

    Returns:
        List of profile dictionaries ready for OrganizerProfile creation
    """
    tree = ET.parse(file_path)
    root = tree.getroot()

    profiles = []
    priority = 0

    for profile_elem in root.findall('Profile'):
        profile_data = parse_profile(profile_elem, priority)
        if profile_data:
            profiles.append(profile_data)
            priority += 1

    # Sort by name to get proper ordering (01, 02, 02.5, 03, etc.)
    profiles.sort(key=lambda p: extract_sort_key(p['name']))

    # Reassign priorities after sorting
    for i, profile in enumerate(profiles):
        profile['priority'] = i

    return profiles


def extract_sort_key(name: str) -> tuple:
    """Extract numeric sort key from profile name like '01 - Marvel/DC'."""
    match = re.match(r'^(\d+(?:\.\d+)?)', name)
    if match:
        num_str = match.group(1)
        # Handle decimal priorities like "02.5"
        return (float(num_str), name)
    return (999, name)


def parse_profile(profile_elem: ET.Element, priority: int) -> dict | None:
    """Parse a single Profile element."""
    name = profile_elem.get('Name', 'Unnamed Profile')

    # Skip disabled/template profiles
    mode = get_text(profile_elem, 'Mode', 'Move')
    if mode == 'Simulate':
        # This is likely a disabled template profile
        return None

    # Parse templates - unescape HTML entities
    folder_template = unescape(get_text(profile_elem, 'FolderTemplate', ''))
    file_template = unescape(get_text(profile_elem, 'FileTemplate', ''))
    base_folder = get_text(profile_elem, 'BaseFolder', '/comics/library')

    # Parse exclude rules
    exclude_rules = parse_exclude_rules(profile_elem.find('ExcludeRules'))

    # Parse illegal characters mapping
    illegal_characters = parse_item_mapping(profile_elem.find('IllegalCharacters'))

    # Parse months mapping
    months = parse_item_mapping(profile_elem.find('Months'))

    # Parse flags
    remove_empty_folder = get_bool(profile_elem, 'RemoveEmptyFolder', True)
    auto_space_fields = get_bool(profile_elem, 'AutoSpaceFields', True)
    replace_multiple_spaces = get_bool(profile_elem, 'ReplaceMultipleSpaces', True)

    return {
        'name': name,
        'priority': priority,
        'is_enabled': True,
        'folder_template': folder_template,
        'file_template': file_template,
        'base_folder': base_folder,
        'exclude_rules': exclude_rules,
        'illegal_characters': illegal_characters,
        'months': months,
        'remove_empty_folder': remove_empty_folder,
        'auto_space_fields': auto_space_fields,
        'replace_multiple_spaces': replace_multiple_spaces,
    }


def parse_exclude_rules(rules_elem: ET.Element | None) -> dict:
    """
    Parse ExcludeRules element with nested ExcludeGroup elements.

    Returns structure like:
    {
        "operator": "All",  # Top-level operator
        "mode": "Only",     # "Only" = profile processes matching comics
        "rules": [...]      # List of rules and groups
    }
    """
    if rules_elem is None:
        return {"operator": "All", "mode": "Only", "rules": []}

    operator = rules_elem.get('Operator', 'All')
    mode = rules_elem.get('ExcludeMode', 'Only')

    rules = []
    for child in rules_elem:
        if child.tag == 'ExcludeRule':
            rules.append(parse_single_rule(child))
        elif child.tag == 'ExcludeGroup':
            rules.append(parse_exclude_group(child))

    return {
        "operator": operator,
        "mode": mode,
        "rules": rules,
    }


def parse_exclude_group(group_elem: ET.Element) -> dict:
    """Parse an ExcludeGroup element (nested rules)."""
    operator = group_elem.get('Operator', 'All')

    rules = []
    for child in group_elem:
        if child.tag == 'ExcludeRule':
            rules.append(parse_single_rule(child))
        elif child.tag == 'ExcludeGroup':
            # Nested groups (recursive)
            rules.append(parse_exclude_group(child))

    return {
        "type": "group",
        "operator": operator,
        "rules": rules,
    }


def parse_single_rule(rule_elem: ET.Element) -> dict:
    """Parse a single ExcludeRule element."""
    return {
        "type": "rule",
        "field": rule_elem.get('Field', ''),
        "operator": rule_elem.get('Operator', 'is'),
        "value": rule_elem.get('Value', ''),
    }


def parse_item_mapping(mapping_elem: ET.Element | None) -> dict:
    """Parse Item elements into a dict mapping (for IllegalCharacters, Months)."""
    if mapping_elem is None:
        return {}

    result = {}
    for item in mapping_elem.findall('Item'):
        name = item.get('Name', '')
        value = item.get('Value', '')
        if name:
            # Unescape HTML entities like &quot; &lt; &gt;
            result[unescape(name)] = unescape(value)

    return result


def get_text(elem: ET.Element, tag: str, default: str = '') -> str:
    """Get text content of a child element."""
    child = elem.find(tag)
    if child is not None and child.text:
        return child.text
    return default


def get_bool(elem: ET.Element, tag: str, default: bool = False) -> bool:
    """Get boolean value of a child element."""
    text = get_text(elem, tag, str(default).lower())
    return text.lower() == 'true'


@transaction.atomic
def import_profiles(file_path: str, clear_existing: bool = True) -> dict:
    """
    Import profiles from a .lop file into the database.

    Args:
        file_path: Path to the .lop XML file
        clear_existing: If True, delete existing profiles before import

    Returns:
        Dict with import results
    """
    profiles_data = parse_lop_file(file_path)

    if clear_existing:
        deleted_count = OrganizerProfile.objects.count()
        OrganizerProfile.objects.all().delete()
    else:
        deleted_count = 0

    created_profiles = []
    for data in profiles_data:
        profile = OrganizerProfile.objects.create(**data)
        created_profiles.append(profile)

    return {
        "success": True,
        "deleted_count": deleted_count,
        "imported_count": len(created_profiles),
        "profiles": [p.name for p in created_profiles],
    }
