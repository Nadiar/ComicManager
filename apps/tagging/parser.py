"""
Parser for ComicRack DataManager XML files (dataman.dat).

Converts the nested XML structure into flat DataManagerRuleset records.
"""

import xml.etree.ElementTree as ET
from typing import BinaryIO

from .models import DataManagerRuleset


def parse_datamanager_xml(file_obj: BinaryIO) -> list[dict]:
    """
    Parse a dataman.dat XML file and return a list of ruleset dicts.

    Args:
        file_obj: File-like object containing the XML data

    Returns:
        List of dicts ready to create DataManagerRuleset records:
        [
            {
                "name": "Green Lantern",
                "group_path": "DC Series Groups/Cosmic/OA",
                "comment": "Any and all lantern related",
                "mode": "AND",
                "priority": 0,
                "rules": [{"field": "Series", "modifier": "Contains", "value": "Green Lantern"}],
                "actions": [{"field": "SeriesGroup", "modifier": "SetValue", "value": "OA"}],
            },
            ...
        ]
    """
    # Read and decode, handling BOM
    content = file_obj.read()
    if isinstance(content, bytes):
        # Handle UTF-8 BOM if present
        if content.startswith(b"\xef\xbb\xbf"):
            content = content[3:]
        content = content.decode("utf-8")

    # Remove Windows line endings
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    root = ET.fromstring(content)
    rulesets = []
    priority_counter = [0]  # Use list to allow mutation in nested function

    def process_element(element, group_path: str = ""):
        """Recursively process groups and rulesets."""
        for child in element:
            if child.tag == "group":
                # Nested group - build path and recurse
                group_name = child.get("name", "")
                new_path = f"{group_path}/{group_name}" if group_path else group_name
                process_element(child, new_path)

            elif child.tag == "ruleset":
                # Found a ruleset - extract it
                ruleset_data = extract_ruleset(child, group_path, priority_counter[0])
                if ruleset_data:
                    rulesets.append(ruleset_data)
                    priority_counter[0] += 1

            elif child.tag == "disabled":
                # Disabled section - skip entirely
                # Could optionally import as is_enabled=False
                pass

            elif child.tag == "filtersanddefaults":
                # Group-level defaults - skip (we inherit mode from ruleset)
                pass

    process_element(root)
    return rulesets


def extract_ruleset(element, group_path: str, priority: int) -> dict | None:
    """
    Extract a single ruleset element into a dict.

    Args:
        element: XML element with tag "ruleset"
        group_path: Parent group path
        priority: Order in which this ruleset was encountered

    Returns:
        Dict with ruleset data, or None if invalid
    """
    name = element.get("name", "").strip()
    if not name:
        return None

    mode = element.get("rulesetmode", "AND").upper()
    if mode not in ("AND", "OR"):
        mode = "AND"

    comment = element.get("comment", "")

    rules = []
    actions = []

    for child in element:
        if child.tag == "rule":
            rule = extract_rule(child)
            if rule:
                rules.append(rule)
        elif child.tag == "action":
            action = extract_action(child)
            if action:
                actions.append(action)

    # Skip rulesets with no rules or no actions
    if not rules or not actions:
        return None

    return {
        "name": name,
        "group_path": group_path,
        "comment": comment,
        "mode": mode,
        "priority": priority,
        "rules": rules,
        "actions": actions,
    }


def extract_rule(element) -> dict | None:
    """Extract a rule element into a dict."""
    field = element.get("field", "").strip()
    modifier = element.get("modifier", "").strip()
    value = element.get("value", "")

    if not field or not modifier:
        return None

    return {
        "field": field,
        "modifier": modifier,
        "value": value,
    }


def extract_action(element) -> dict | None:
    """Extract an action element into a dict."""
    field = element.get("field", "").strip()
    modifier = element.get("modifier", "").strip()
    value = element.get("value", "")

    if not field or not modifier:
        return None

    return {
        "field": field,
        "modifier": modifier,
        "value": value,
    }


def import_datamanager_file(file_obj: BinaryIO, clear_existing: bool = False) -> tuple[int, int]:
    """
    Import a dataman.dat file into the database.

    Args:
        file_obj: File-like object containing the XML data
        clear_existing: If True, delete all existing rulesets first

    Returns:
        Tuple of (created_count, skipped_count)
    """
    if clear_existing:
        DataManagerRuleset.objects.all().delete()

    rulesets = parse_datamanager_xml(file_obj)

    created = 0
    skipped = 0

    for ruleset_data in rulesets:
        # Check if a ruleset with same name and group_path exists
        exists = DataManagerRuleset.objects.filter(
            name=ruleset_data["name"],
            group_path=ruleset_data["group_path"],
        ).exists()

        if exists:
            skipped += 1
            continue

        DataManagerRuleset.objects.create(
            name=ruleset_data["name"],
            group_path=ruleset_data["group_path"],
            comment=ruleset_data["comment"],
            mode=ruleset_data["mode"],
            priority=ruleset_data["priority"],
            rules=ruleset_data["rules"],
            actions=ruleset_data["actions"],
            is_enabled=True,
        )
        created += 1

    return created, skipped


def export_datamanager_xml() -> str:
    """
    Export all rulesets back to DataManager XML format.

    Returns:
        XML string in dataman.dat format
    """
    root = ET.Element("collection", version="2.7.5")

    # Group rulesets by their group_path hierarchy
    rulesets = DataManagerRuleset.objects.filter(is_enabled=True).order_by("priority")

    # Build a tree structure from flat group_paths
    groups: dict = {}  # path -> element

    for ruleset in rulesets:
        # Find or create the parent group element
        parent = root
        if ruleset.group_path:
            parts = ruleset.group_path.split("/")
            current_path = ""
            for part in parts:
                current_path = f"{current_path}/{part}" if current_path else part
                if current_path not in groups:
                    group_elem = ET.SubElement(parent, "group", name=part)
                    ET.SubElement(group_elem, "filtersanddefaults", rulesetmode="AND")
                    groups[current_path] = group_elem
                parent = groups[current_path]

        # Create the ruleset element
        ruleset_elem = ET.SubElement(parent, "ruleset", name=ruleset.name, rulesetmode=ruleset.mode)
        if ruleset.comment:
            ruleset_elem.set("comment", ruleset.comment)

        # Add rules
        for rule in ruleset.rules:
            ET.SubElement(
                ruleset_elem,
                "rule",
                field=rule["field"],
                modifier=rule["modifier"],
                value=rule["value"],
            )

        # Add actions
        for action in ruleset.actions:
            ET.SubElement(
                ruleset_elem,
                "action",
                field=action["field"],
                modifier=action["modifier"],
                value=action["value"],
            )

    # Convert to string with XML declaration
    ET.indent(root, space="  ")
    xml_str = ET.tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n{xml_str}'
