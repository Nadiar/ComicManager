"""
Utility functions for ComicInfo.xml handling.

Provides read, write, and comparison functionality for ComicInfo.xml
files embedded in CBZ archives.
"""

import errno
import fcntl
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from defusedxml.ElementTree import fromstring as _safe_fromstring
import zipfile
from typing import Any

from django.db.models import IntegerField
from django.db.models.expressions import RawSQL

from django.utils.html import strip_tags

from .models import Comic


def html_to_text(html: str) -> str:
    """Convert HTML to plain text, preserving paragraph breaks.

    Converts <p>, <br>, and block-level tags to newlines before stripping.
    """
    if not html:
        return ""
    text = re.sub(r'<br\s*/?>', '\n', html)
    text = re.sub(r'</p>\s*', '\n', text)
    text = re.sub(r'<p[^>]*>', '', text)
    text = strip_tags(text)
    # Collapse multiple blank lines but preserve single breaks
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def natural_number_annotation():
    """Return a RawSQL annotation for natural sorting of the 'number' field.

    Extracts the leading integer from the number field so that
    "1", "2", "10" sort numerically instead of lexicographically.
    Non-numeric values (e.g. "½", "Annual") sort last.
    """
    return RawSQL(
        "CASE WHEN number ~ '^[0-9]+' "
        "THEN CAST(SUBSTRING(number FROM '^[0-9]+') AS INTEGER) "
        "ELSE 2147483647 END",
        (),
        output_field=IntegerField(),
    )


def natural_sort_key(comic):
    """Python sort key for natural number ordering on Comic instances."""
    num = comic.number or ""
    match = re.match(r'^(\d+)', num)
    return (comic.series or "", int(match.group(1)) if match else 2147483647, num)


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
    "Imprint": "imprint",
    "Summary": "summary",
    "Notes": "notes",
    "Genre": "genre",
    "Web": "web",
    "PageCount": "page_count",
    "Format": "format",
    "Characters": "characters",
    "Teams": "teams",
    "Locations": "locations",
    "StoryArc": "story_arc",
    "Tags": "tags",
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
    "publisher", "imprint", "summary", "notes", "genre", "web", "format", "characters",
    "teams", "locations", "story_arc", "tags", "scan_information", "series_group", "main_character_or_team",
    "writer", "penciller", "inker", "colorist", "letterer", "cover_artist", "editor",
    "storage_location",
]

# Human-readable display labels for comic fields, used by metadata-comparison views
FIELD_LABELS = {
    "title": "Title",
    "series": "Series",
    "number": "Issue #",
    "count": "Count",
    "volume": "Volume",
    "year": "Year",
    "month": "Month",
    "day": "Day",
    "publisher": "Publisher",
    "imprint": "Imprint",
    "summary": "Summary",
    "notes": "Notes",
    "genre": "Genre",
    "web": "Web URL",
    "page_count": "Page Count",
    "format": "Format",
    "characters": "Characters",
    "teams": "Teams",
    "locations": "Locations",
    "story_arc": "Story Arc",
    "tags": "Tags",
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

# Registry of all possible columns for comic tables
COLUMNS_REGISTRY = {
    # Core Metadata
    "series": {"label": "Series", "sort": "series", "attr": "series"},
    "number": {"label": "Issue #", "sort": "number", "attr": "number"},
    "title": {"label": "Title", "sort": "title", "attr": "title"},
    "count": {"label": "Count", "sort": "count", "attr": "count"},
    "volume": {"label": "Volume", "sort": "volume", "attr": "volume"},
    "year": {"label": "Year", "sort": "year", "attr": "year"},
    "month": {"label": "Month", "sort": "month", "attr": "month"},
    "day": {"label": "Day", "sort": "day", "attr": "day"},
    "publisher": {"label": "Publisher", "sort": "publisher", "attr": "publisher"},
    "imprint": {"label": "Imprint", "sort": "imprint", "attr": "imprint"},
    "summary": {"label": "Summary", "sort": "summary", "attr": "summary"},
    "notes": {"label": "Notes", "sort": "notes", "attr": "notes"},
    "genre": {"label": "Genre", "sort": "genre", "attr": "genre"},
    "web": {"label": "Web URL", "sort": "web", "attr": "web"},
    "format": {"label": "Format", "sort": "format", "attr": "format"},
    "characters": {"label": "Characters", "sort": "characters", "attr": "characters"},
    "teams": {"label": "Teams", "sort": "teams", "attr": "teams"},
    "locations": {"label": "Locations", "sort": "locations", "attr": "locations"},
    "tags": {"label": "Tags", "sort": "tags", "attr": "tags"},
    "scan_info": {"label": "Scan Info", "sort": "scan_information", "attr": "scan_information"},
    "series_group": {"label": "Series Group", "sort": "series_group", "attr": "series_group"},
    "main_char": {"label": "Main Character/Team", "sort": "main_character_or_team", "attr": "main_character_or_team"},
    
    # Credits
    "writer": {"label": "Writer", "sort": "writer", "attr": "writer"},
    "penciller": {"label": "Penciller", "sort": "penciller", "attr": "penciller"},
    "inker": {"label": "Inker", "sort": "inker", "attr": "inker"},
    "colorist": {"label": "Colorist", "sort": "colorist", "attr": "colorist"},
    "letterer": {"label": "Letterer", "sort": "letterer", "attr": "letterer"},
    "cover_artist": {"label": "Cover", "sort": "cover_artist", "attr": "cover_artist"},
    "editor": {"label": "Editor", "sort": "editor", "attr": "editor"},
    
    # File / System
    "path": {"label": "Path", "sort": "file_path", "attr": "file_path"},
    "file_format": {"label": "File Format", "sort": "file_format", "attr": "file_format"},
    "file_size": {"label": "Size", "sort": "file_size", "attr": "file_size"},
    "pages": {"label": "Pages", "sort": "page_count", "attr": "page_count"},
    "id": {"label": "ID", "sort": "id", "attr": "id"},
    "state": {"label": "State", "sort": "state", "attr": "state"},
    "medium": {"label": "Medium", "sort": "medium", "attr": "medium"},
    "imported": {"label": "Imported", "sort": "imported_at", "attr": "imported_at"},
    "updated": {"label": "Updated", "sort": "updated_at", "attr": "updated_at"},
    "last_written": {"label": "Last Written", "sort": "last_written", "attr": "last_written"},
    
    # Custom Values / ComicVine
    "first_series": {"label": "First Series", "sort": "custom_values__First Series", "attr": "custom_values.First Series"},
    "second_series": {"label": "Second Series", "sort": "custom_values__Second Series", "attr": "custom_values.Second Series"},
    "scrape_score": {"label": "Scrape Score", "sort": "custom_values__scrape_score", "attr": "custom_values.scrape_score"},
    "scrape_source": {"label": "Scrape Source", "sort": "custom_values__scrape_source", "attr": "custom_values.scrape_source"},
    "cv_issue": {"label": "CV Issue", "sort": "custom_values__comicvine_issue", "attr": "custom_values.comicvine_issue"},
    "cv_volume": {"label": "CV Volume", "sort": "custom_values__comicvine_volume", "attr": "custom_values.comicvine_volume"},
    "dm_processed": {"label": "DataManager Processed", "sort": "custom_values__DataManager_Processed", "attr": "custom_values.DataManager_Processed"},
    "cv_issue_count": {"label": "CV Issue Count", "sort": "custom_values__comicvine_issue_count", "attr": "custom_values.comicvine_issue_count"},
    "starwars": {"label": "IsStarWars", "sort": "custom_values__IsStarWars", "attr": "custom_values.IsStarWars"},
    "has_alt_covers": {"label": "Has Alt Covers", "sort": "custom_values__HasAltCovers", "attr": "custom_values.HasAltCovers"},
}

DEFAULT_COLUMNS = ["series", "number", "count", "title", "volume", "year", "publisher", "format", "pages", "state"]

# Proposed/pre-scrape columns
COLUMNS_REGISTRY.update({
    "proposed_series": {"label": "Proposed Series", "sort": "proposed_series", "attr": "proposed_series"},
    "proposed_number": {"label": "Proposed #",      "sort": "proposed_number", "attr": "proposed_number"},
    "proposed_volume": {"label": "Proposed Vol",    "sort": "proposed_volume", "attr": "proposed_volume"},
    "proposed_year":   {"label": "Proposed Year",   "sort": "proposed_year",   "attr": "proposed_year"},
})

STATE_NEW_DEFAULT_COLUMNS = [
    "proposed_series", "proposed_number", "proposed_volume", "proposed_year",
    "publisher", "format", "pages", "file_format",
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
    root = _safe_fromstring(xml_content)
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
                # Ensure all values are strings to prevent PostgreSQL type mismatch
                custom_values[name] = str(value)

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
            "label": FIELD_LABELS.get(field, field.replace("_", " ").title()),
            "db_value": db_value,
            "xml_value": xml_value,
            "status": status,
        })

    return comparisons


# Mapping from CVMatch attribute -> DB/XML field name
CV_FIELD_MAP = {
    "series": "series",
    "issue_number": "number",
    "title": "title",
    "issue_count": "count",
    "publisher": "publisher",
    "description": "summary",
    "web": "web",
    "characters": "characters",
    "teams": "teams",
    "locations": "locations",
    "story_arcs": "story_arc",
    "writer": "writer",
    "penciller": "penciller",
    "inker": "inker",
    "colorist": "colorist",
    "letterer": "letterer",
    "cover_artist": "cover_artist",
    "editor": "editor",
}

# DB/XML fields that have no CV equivalent
DB_ONLY_FIELDS = [
    "volume", "month", "day", "imprint", "notes", "genre", "format", "tags",
    "scan_information", "series_group", "main_character_or_team", "page_count",
]

# CV fields that have no direct DB equivalent
CV_ONLY_FIELDS = [
    ("cover_date", "Cover Date"),
    ("start_year", "Start Year"),
]


def compare_all_sources(comic, xml_data, cv_local_match, cv_api_match):
    """4-way comparison: DB vs ComicInfo.xml vs comicvine.db vs ComicVine API.

    Returns {
        "common": [{"field", "label", "db", "xml", "cv_local", "cv_api", "status"}],
        "extras": [{"field", "label", "source", "value"}],
    }
    """
    from django.utils.html import strip_tags

    if xml_data is None:
        xml_data = {}

    common = []

    # Common fields: fields shared between CV and DB/XML
    for cv_attr, db_field in CV_FIELD_MAP.items():
        db_val = getattr(comic, db_field, None)
        xml_val = xml_data.get(db_field)
        cv_local_val = getattr(cv_local_match, cv_attr, None) if cv_local_match else None
        cv_api_val = getattr(cv_api_match, cv_attr, None) if cv_api_match else None

        # Strip HTML from CV descriptions
        if cv_attr == "description":
            if cv_local_val:
                cv_local_val = strip_tags(str(cv_local_val))
            if cv_api_val:
                cv_api_val = strip_tags(str(cv_api_val))

        # Normalize to strings for comparison
        vals = {}
        for key, v in [("db", db_val), ("xml", xml_val), ("cv_local", cv_local_val), ("cv_api", cv_api_val)]:
            vals[key] = str(v).strip() if v is not None else ""

        # Determine status
        non_empty = [v for v in vals.values() if v]
        if not non_empty:
            status = "empty"
        elif len(set(non_empty)) == 1:
            status = "match"
        else:
            status = "differ"

        common.append({
            "field": db_field,
            "label": FIELD_LABELS.get(db_field, db_field.replace("_", " ").title()),
            "db": db_val,
            "xml": xml_val,
            "cv_local": cv_local_val,
            "cv_api": cv_api_val,
            "status": status,
        })

    # Extra fields: DB/XML only
    extras = []
    for db_field in DB_ONLY_FIELDS:
        db_val = getattr(comic, db_field, None)
        xml_val = xml_data.get(db_field)
        label = FIELD_LABELS.get(db_field, db_field.replace("_", " ").title())
        if db_val is not None and str(db_val).strip():
            extras.append({"field": db_field, "label": label, "source": "db", "value": db_val})
        if xml_val is not None and str(xml_val).strip():
            extras.append({"field": db_field, "label": label, "source": "xml", "value": xml_val})

    # Extra fields: CV only
    for cv_attr, label in CV_ONLY_FIELDS:
        cv_local_val = getattr(cv_local_match, cv_attr, None) if cv_local_match else None
        cv_api_val = getattr(cv_api_match, cv_attr, None) if cv_api_match else None
        if cv_local_val is not None and str(cv_local_val).strip():
            extras.append({"field": cv_attr, "label": label, "source": "cv_local", "value": cv_local_val})
        if cv_api_val is not None and str(cv_api_val).strip():
            extras.append({"field": cv_attr, "label": label, "source": "cv_api", "value": cv_api_val})

    return {"common": common, "extras": extras}


# Standard ComicInfo.xml field names — these should never appear in CustomValues
_STANDARD_XML_FIELDS = set(FIELD_MAP.keys()) | {
    "Tags", "Teams", "Locations", "Characters", "Genre",
    "Notes", "Summary", "Pages", "PageCount",
}


def _build_pages_element(cbz_path: str) -> list[dict] | None:
    """Read image dimensions from a CBZ file for the Pages element.

    Returns a list of page dicts with Image, ImageWidth, ImageHeight, and Type.
    """
    from io import BytesIO
    try:
        from PIL import Image
    except ImportError:
        return None

    if not cbz_path or not os.path.exists(cbz_path):
        return None

    try:
        with zipfile.ZipFile(cbz_path, "r") as zf:
            from .cbz_utils import list_pages
            image_files = list_pages(zf.namelist())
            if not image_files:
                return None

            pages = []
            for idx, name in enumerate(image_files):
                page = {"Image": str(idx)}
                try:
                    with zf.open(name) as f:
                        img = Image.open(BytesIO(f.read()))
                        page["ImageWidth"] = str(img.width)
                        page["ImageHeight"] = str(img.height)
                except Exception:
                    pass
                if idx == 0:
                    page["Type"] = "FrontCover"
                pages.append(page)
            return pages
    except (zipfile.BadZipFile, OSError):
        return None


def generate_comicinfo_xml(comic: Comic, cbz_path: str = None) -> str:
    """
    Generate ComicInfo.xml content from a Comic model instance.

    Args:
        comic: The Comic model instance.
        cbz_path: Optional path to CBZ file (for Pages element with image dimensions).

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

    # Add Notes with CV reference (like ComicRack) — only if notes field is empty
    if not comic.notes:
        cv_issue_id = (comic.custom_values or {}).get("comicvine_issue")
        if cv_issue_id:
            notes_elem = ET.SubElement(root, "Notes")
            notes_elem.text = f"Scraped metadata from ComicVine [CVDB{cv_issue_id}]."

    # Add Pages element with image dimensions
    if cbz_path is None:
        cbz_path = comic.file_path
    pages = _build_pages_element(cbz_path)
    if pages:
        pages_elem = ET.SubElement(root, "Pages")
        for page in pages:
            page_elem = ET.SubElement(pages_elem, "Page")
            for attr, val in page.items():
                page_elem.set(attr, val)

    # Add CustomValues — filter out standard fields and empty values
    custom_values = comic.custom_values or {}
    filtered_cv = {}
    for name, value in custom_values.items():
        # Skip standard XML fields that shouldn't be in CustomValues
        if name in _STANDARD_XML_FIELDS:
            continue
        # Normalize DataManager_Processed casing to match ComicRack
        if name.lower() == "datamanager_processed":
            name = "DataManager_Processed"
            value = "Yes" if value else ""
        filtered_cv[name] = str(value)

    if filtered_cv:
        cv_elem = ET.SubElement(root, "CustomValues")
        for name, value in sorted(filtered_cv.items()):
            cv = ET.SubElement(cv_elem, "CustomValue")
            cv.set("name", name)
            cv.set("value", value)

    # Pretty-print with indentation
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode")


_NUMBERLESS_FORMATS = frozenset({
    "TPB", "Omnibus", "Graphic Novel", "Hard Cover", "Absolute Edition",
})


def validate_comic_for_write(comic) -> list[str]:
    """
    Return a list of missing required field names. Empty list means the comic is valid.
    Not enforced by force_write (the escape hatch path).
    """
    errors = []
    custom = comic.custom_values or {}
    inducks_story_only = (
        custom.get("scrape_source") == "inducks"
        and not custom.get("inducks_issuecode")
        and custom.get("inducks_storycode")
    )

    if not (comic.series or "").strip():
        errors.append("series")
    if not inducks_story_only:
        if not (comic.number or "").strip():
            if (comic.format or "").strip() not in _NUMBERLESS_FORMATS:
                errors.append("number")
        if not (comic.publisher or "").strip():
            errors.append("publisher")
    return errors


# Linux FICLONE ioctl: reflink-clone one file into another. On copy-on-write
# filesystems (btrfs, XFS) this is near-instant and consumes no extra space,
# because the clone shares the original's data blocks until one side is written.
_FICLONE = 0x40049409


def _try_reflink(src: str, dst: str) -> bool:
    """Reflink-clone src onto dst. Returns True on success, False if the
    filesystem does not support reflinks (e.g. ext4) or src/dst differ in
    device. Never falls back to a byte copy: callers choose what to do when a
    cheap clone is not available."""
    try:
        with open(src, "rb") as s, open(dst, "wb") as d:
            fcntl.ioctl(d.fileno(), _FICLONE, s.fileno())
        shutil.copystat(src, dst)
        return True
    except OSError:
        return False


def _patch_offset(zf: zipfile.ZipFile) -> int:
    """
    Where _patch_comicinfo_entry starts writing: over the old ComicInfo.xml
    when it is the last entry in the file (true after the first patch), so
    repeated writes do not pile up old copies; otherwise at the central
    directory.
    """
    infos = zf.infolist()
    if infos:
        last = max(infos, key=lambda i: i.header_offset)
        if last.filename.lower() == "comicinfo.xml":
            return last.header_offset
    return zf.start_dir


def _patch_comicinfo_entry(zip_path: str, xml_bytes: bytes) -> None:
    """Replace (or add) the ComicInfo.xml entry in an existing archive using
    ZIP append mode. Page images are never read, decompressed, or recompressed.

    Append mode does not overwrite an existing entry of the same name; it would
    write a duplicate. Drop any stale ComicInfo.xml from the in-memory directory
    first (match case-insensitively, since casing varies across taggers) so the
    rewritten central directory points only at the new entry. Writing starts at
    _patch_offset, and the file is truncated after the new central directory."""
    with zipfile.ZipFile(zip_path, "a", zipfile.ZIP_DEFLATED) as zf:
        offset = _patch_offset(zf)
        for info in [i for i in zf.infolist()
                     if i.filename.lower() == "comicinfo.xml"]:
            zf.NameToInfo.pop(info.filename, None)
            zf.filelist.remove(info)
        zf.start_dir = offset
        zf.writestr("ComicInfo.xml", xml_bytes)


def _index_backup_path(zip_path: str) -> str:
    folder, name = os.path.split(zip_path)
    return os.path.join(folder, f".{name}.cm-index")


def _fsync_file(path: str) -> None:
    """fsync a file, or a folder (to persist a rename inside it)."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _save_index_backup(zip_path: str) -> str:
    """
    Save everything the patch will overwrite (the old ComicInfo.xml when it is
    the last entry, the central directory and end record) to a hidden file
    next to the archive before an in-place patch.

    An in-place patch writes the new entry over these bytes and only writes the
    new index at the end. If it is interrupted in between, the original archive
    is exactly the bytes before the patch offset plus this saved tail, which
    restore_index_backup puts back.
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        start = _patch_offset(zf)
    size = os.path.getsize(zip_path)
    backup = _index_backup_path(zip_path)
    with open(zip_path, "rb") as src, open(backup, "wb") as out:
        src.seek(start)
        out.write(start.to_bytes(8, "little"))
        out.write(src.read(size - start))
        out.flush()
        os.fsync(out.fileno())
    return backup


def restore_index_backup(zip_path: str) -> bool:
    """
    Undo an interrupted in-place ComicInfo write using the saved index.
    Returns True if a backup was found and the archive was restored.
    """
    backup = _index_backup_path(zip_path)
    if not os.path.exists(backup):
        return False
    with open(backup, "rb") as f:
        start = int.from_bytes(f.read(8), "little")
        tail = f.read()
    with open(zip_path, "r+b") as f:
        f.truncate(start)
        f.seek(start)
        f.write(tail)
        f.flush()
        os.fsync(f.fileno())
    zipfile.ZipFile(zip_path, "r").close()
    os.remove(backup)
    return True


def _check_writable(path: str) -> None:
    """
    Raise a PermissionError that says the file is read-only when it cannot be
    opened for writing. Opening it for update does not change it.
    """
    try:
        with open(path, "r+b"):
            pass
    except PermissionError as e:
        raise PermissionError(e.errno, "File is read-only", path) from e


def write_comicinfo_xml(cbz_path: str, comic: Comic) -> bool:
    """
    Write/update ComicInfo.xml inside a CBZ file.

    Patches only the ComicInfo.xml entry: the page images are never read,
    decompressed, or recompressed, so this stays cheap even on multi-gigabyte
    archives. Two paths, picked by what the filesystem supports:

    - CoW filesystems (btrfs/XFS): patch a near-free reflink clone in the same
      directory, then atomically swap it over the original. Fast and crash-safe.
    - Other filesystems (e.g. ext4): patch the archive in place. Still fast (no
      O(size) copy). The archive index is saved to a hidden file first, so an
      interrupted write can be undone exactly (restore_index_backup); the
      backup is removed once the patched archive is synced to disk.

    Returns True on success. Raises on failure (missing or read-only file,
    damaged archive) so callers can report the reason.
    """
    if not cbz_path or not os.path.exists(cbz_path):
        raise FileNotFoundError(errno.ENOENT, "File not found", cbz_path or "")

    # A backup left by an interrupted earlier in-place write: put the
    # archive back before reading it
    restore_index_backup(cbz_path)

    # Generate new XML content (pass cbz_path for Pages element)
    xml_bytes = generate_comicinfo_xml(comic, cbz_path=cbz_path).encode("utf-8")

    # Probe for a cheap reflink clone in the same directory (so a later
    # os.replace stays on one filesystem). If it works, patch the clone and
    # swap atomically; the original is untouched until then.
    fd, tmp_path = tempfile.mkstemp(prefix=".cm-", suffix=".tmp", dir=os.path.dirname(cbz_path))
    os.close(fd)
    try:
        if _try_reflink(cbz_path, tmp_path):
            _patch_comicinfo_entry(tmp_path, xml_bytes)
            # Sync the patched clone before the swap and the folder after
            # it, so a power loss leaves the old or the new archive, never
            # a renamed file whose data was not written yet
            _fsync_file(tmp_path)
            os.replace(tmp_path, cbz_path)
            _fsync_file(os.path.dirname(cbz_path) or ".")
            return True
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    # No reflink available: drop the empty probe file and patch in place
    # rather than paying for a full O(size) byte copy.
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    # Patching in place needs write access to the file itself. Check it before
    # the index backup is saved, so a read-only file fails with a clear reason
    # and leaves no backup behind.
    _check_writable(cbz_path)
    backup = _save_index_backup(cbz_path)
    try:
        _patch_comicinfo_entry(cbz_path, xml_bytes)
        _fsync_file(cbz_path)
    except Exception:
        restore_index_backup(cbz_path)
        raise
    os.remove(backup)
    return True


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
