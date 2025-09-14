"""
Management command to import existing tagged comics from the library folder.

Scans /comics/library for .cbz files, reads their ComicInfo.xml metadata,
and creates Comic records with state='written' (already fully processed).
"""

import os
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from django.core.management.base import BaseCommand
from django.conf import settings

from apps.core.models import Comic


class Command(BaseCommand):
    help = "Import existing tagged comics from the library folder into the database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be imported without actually importing",
        )
        parser.add_argument(
            "--path",
            type=str,
            default=None,
            help="Override the library path (default: /comics/library)",
        )

    def handle(self, *args, **options):
        library_path = options["path"] or getattr(settings, "LIBRARY_DIR", "/comics/library")
        dry_run = options["dry_run"]

        if not os.path.exists(library_path):
            self.stderr.write(self.style.ERROR(f"Library path does not exist: {library_path}"))
            return

        self.stdout.write(f"Scanning library: {library_path}")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no changes will be made"))

        cbz_files = list(Path(library_path).rglob("*.cbz"))
        self.stdout.write(f"Found {len(cbz_files)} .cbz files")

        imported = 0
        skipped = 0
        errors = 0

        for cbz_path in cbz_files:
            file_path_str = str(cbz_path)

            # Check if already imported
            if Comic.objects.filter(file_path=file_path_str).exists():
                skipped += 1
                continue

            try:
                comic_data = self.extract_comic_info(cbz_path)
                if comic_data is None:
                    self.stderr.write(self.style.WARNING(f"No ComicInfo.xml in: {cbz_path.name}"))
                    errors += 1
                    continue

                comic_data["file_path"] = file_path_str
                comic_data["file_format"] = "cbz"
                comic_data["file_size"] = cbz_path.stat().st_size
                comic_data["state"] = Comic.STATE_WRITTEN
                comic_data["medium"] = Comic.MEDIUM_DIGITAL

                if dry_run:
                    self.stdout.write(f"  Would import: {comic_data.get('series', 'Unknown')} #{comic_data.get('number', '?')}")
                else:
                    Comic.objects.create(**comic_data)
                    imported += 1

                    if imported % 100 == 0:
                        self.stdout.write(f"  Imported {imported} comics...")

            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Error processing {cbz_path.name}: {e}"))
                errors += 1

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Imported: {imported}"))
        self.stdout.write(f"Skipped (already exists): {skipped}")
        if errors:
            self.stdout.write(self.style.WARNING(f"Errors: {errors}"))

    def extract_comic_info(self, cbz_path: Path) -> dict | None:
        """Extract metadata from ComicInfo.xml inside a CBZ file."""
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
                    return self.parse_comic_info_xml(f.read())

        except zipfile.BadZipFile:
            raise ValueError("Invalid or corrupted CBZ file")

    def parse_comic_info_xml(self, xml_content: bytes) -> dict:
        """Parse ComicInfo.xml content into a dictionary matching Comic model fields."""
        root = ET.fromstring(xml_content)

        # Direct field mappings (XML tag -> model field)
        field_map = {
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
            # Credits
            "Writer": "writer",
            "Penciller": "penciller",
            "Inker": "inker",
            "Colorist": "colorist",
            "Letterer": "letterer",
            "CoverArtist": "cover_artist",
            "Editor": "editor",
        }

        # Integer fields that need conversion
        int_fields = {"count", "volume", "year", "month", "day", "page_count"}

        data = {}

        for xml_tag, model_field in field_map.items():
            element = root.find(xml_tag)
            if element is not None and element.text:
                value = element.text.strip()
                if model_field in int_fields:
                    try:
                        value = int(value)
                    except ValueError:
                        value = None
                data[model_field] = value

        # Parse CustomValues into the custom_values JSONField
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
