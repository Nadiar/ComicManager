"""
Utility functions for ComicInfo.xml handling.

Provides read, write, and comparison functionality for ComicInfo.xml
files embedded in CBZ archives.
"""

import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from typing import Any

from .models import Comic


# Field mapping: XML tag -> DB field name
FIELD_MAP = {
    "Title": "title",
    "Series": "series",
    "Number": "number",
    "Count": "count",
    "Volume": "volume",
    "Year": "year",
    "Month": "month",
    "Day": "day",
    "Publisher": "publisher",
    "Summary": "summary",
    "Notes": "notes",
    "Genre": "genre",
    "Web": "web",
    "PageCount": "page_count",
    "Format": "format",
    "Characters": "characters",
    "ScanInformation": "scan_information",
    "SeriesGroup": "series_group",
    "MainCharacterOrTeam": "main_character_or_team",
    "Writer": "writer",
    "Penciller": "penciller",
    "Inker": "inker",
    "Colorist": "colorist",
    "Letterer": "letterer",
    "CoverArtist": "cover_artist",
    "Editor": "editor",
}

# Reverse mapping: DB field -> XML tag
REVERSE_FIELD_MAP = {v: k for k, v in FIELD_MAP.items()}

# Integer fields that need type conversion
INT_FIELDS = {"count", "volume", "year", "month", "day", "page_count"}

# Fields that are editable in the UI
EDITABLE_FIELDS = [
    "series", "number", "title", "count", "volume", "year", "month", "day",
    "publisher", "summary", "notes", "genre", "web", "format", "characters",
    "scan_information", "series_group", "main_character_or_team",
    "writer", "penciller", "inker", "colorist", "letterer", "cover_artist", "editor",
]


def read_comicinfo_xml(cbz_path: str) -> dict | None:
    """
    Read and parse ComicInfo.xml from a CBZ file.

    Returns a dict mapping DB field names to values, or None if not found.
    """
    if not cbz_path or not os.path.exists(cbz_path):
        return None

    try:
        with zipfile.ZipFile(cbz_path, "r") as zf:
            # Find ComicInfo.xml (case-insensitive)
            comic_info_name = None
            for name in zf.namelist():
                if name.lower() == "comicinfo.xml":
                    comic_info_name = name
                    break

            if not comic_info_name:
                return None

            with zf.open(comic_info_name) as f:
                return parse_comicinfo_xml(f.read())

    except (zipfile.BadZipFile, ET.ParseError, OSError):
        return None


def parse_comicinfo_xml(xml_content: bytes) -> dict:
    """Parse ComicInfo.xml content into a dictionary matching Comic model fields."""
    root = ET.fromstring(xml_content)
    data = {}

    for xml_tag, model_field in FIELD_MAP.items():
        element = root.find(xml_tag)
        if element is not None and element.text:
            value = element.text.strip()
            if model_field in INT_FIELDS:
                try:
                    value = int(value)
                except ValueError:
                    value = None
            data[model_field] = value

    # Parse CustomValues into a dict
    custom_values = {}
    custom_values_elem = root.find("CustomValues")
    if custom_values_elem is not None:
        for cv in custom_values_elem.findall("CustomValue"):
            name = cv.get("name")
            value = cv.get("value")
            if name and value:
                custom_values[name] = value

    if custom_values:
        data["custom_values"] = custom_values

    return data


def compare_db_vs_xml(comic: Comic, xml_data: dict | None) -> list[dict]:
    """
    Compare database fields against XML data.

    Returns a list of comparison items:
    [
        {
            "field": "series",
            "label": "Series",
            "db_value": "Batman",
            "xml_value": "Batman",
            "status": "match" | "differ" | "db_only" | "xml_only"
        },
        ...
    ]
    """
    if xml_data is None:
        xml_data = {}

    comparisons = []

    # Human-readable labels for fields
    field_labels = {
        "title": "Title",
        "series": "Series",
        "number": "Issue #",
        "count": "Count",
        "volume": "Volume",
        "year": "Year",
        "month": "Month",
        "day": "Day",
        "publisher": "Publisher",
        "summary": "Summary",
        "notes": "Notes",
        "genre": "Genre",
        "web": "Web URL",
        "page_count": "Page Count",
        "format": "Format",
        "characters": "Characters",
        "scan_information": "Scan Info",
        "series_group": "Series Group",
        "main_character_or_team": "Main Character/Team",
        "writer": "Writer",
        "penciller": "Penciller",
        "inker": "Inker",
        "colorist": "Colorist",
        "letterer": "Letterer",
        "cover_artist": "Cover Artist",
        "editor": "Editor",
    }

    for field in EDITABLE_FIELDS:
        db_value = getattr(comic, field, None)
        xml_value = xml_data.get(field)

        # Normalize for comparison
        db_str = str(db_value) if db_value is not None else ""
        xml_str = str(xml_value) if xml_value is not None else ""

        if db_str and xml_str:
            status = "match" if db_str == xml_str else "differ"
        elif db_str and not xml_str:
            status = "db_only"
        elif xml_str and not db_str:
            status = "xml_only"
        else:
            status = "empty"

        comparisons.append({
            "field": field,
            "label": field_labels.get(field, field.replace("_", " ").title()),
            "db_value": db_value,
            "xml_value": xml_value,
            "status": status,
        })

    return comparisons


def generate_comicinfo_xml(comic: Comic) -> str:
    """
    Generate ComicInfo.xml content from a Comic model instance.

    Returns XML as a string.
    """
    root = ET.Element("ComicInfo")
    root.set("xmlns:xsd", "http://www.w3.org/2001/XMLSchema")
    root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")

    # Add standard fields
    for xml_tag, model_field in FIELD_MAP.items():
        value = getattr(comic, model_field, None)
        if value is not None:
            elem = ET.SubElement(root, xml_tag)
            elem.text = str(value)

    # Add CustomValues
    custom_values = comic.custom_values or {}
    if custom_values:
        cv_elem = ET.SubElement(root, "CustomValues")
        for name, value in custom_values.items():
            cv = ET.SubElement(cv_elem, "CustomValue")
            cv.set("name", name)
            cv.set("value", str(value))

    # Pretty-print with indentation
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode")


def write_comicinfo_xml(cbz_path: str, comic: Comic) -> bool:
    """
    Write/update ComicInfo.xml inside a CBZ file.

    Creates a new archive with the updated XML, preserving all other files.
    Returns True on success, False on failure.
    """
    if not cbz_path or not os.path.exists(cbz_path):
        return False

    try:
        # Generate new XML content
        xml_content = generate_comicinfo_xml(comic)

        # Create a temporary file for the new archive
        fd, tmp_path = tempfile.mkstemp(suffix=".cbz")
        os.close(fd)

        try:
            with zipfile.ZipFile(cbz_path, "r") as zf_in:
                with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf_out:
                    # Copy all files except ComicInfo.xml
                    for item in zf_in.namelist():
                        if item.lower() != "comicinfo.xml":
                            zf_out.writestr(item, zf_in.read(item))

                    # Write new ComicInfo.xml
                    zf_out.writestr("ComicInfo.xml", xml_content.encode("utf-8"))

            # Replace original with new file
            shutil.move(tmp_path, cbz_path)
            return True

        except Exception:
            # Clean up temp file on error
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    except (zipfile.BadZipFile, OSError, PermissionError):
        return False


def update_comic_from_form(comic: Comic, form_data: dict[str, Any]) -> None:
    """
    Update a Comic instance from form data.

    Handles type conversion for integer fields.
    """
    for field in EDITABLE_FIELDS:
        if field in form_data:
            value = form_data[field]

            # Handle empty strings
            if value == "":
                value = None

            # Convert to int for integer fields
            if field in INT_FIELDS and value is not None:
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    value = None

            setattr(comic, field, value)
