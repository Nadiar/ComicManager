"""
Management command to scan the untagged folder and import new comics.

Scans /comics/untagged for comic files (.cbz, .cbr, .pdf), extracts basic
metadata from filenames, and creates Comic records with state='new'.
"""

import os
import re
import zipfile
from pathlib import Path

from django.core.management.base import BaseCommand
from django.conf import settings

from apps.core.models import Comic, get_setting
from apps.core.cbz_utils import list_pages


class Command(BaseCommand):
    help = "Scan the untagged folder for new comics and import them into the database"

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
            help="Override the untagged path (default: /comics/untagged)",
        )
        parser.add_argument(
            "--no-cleanup",
            action="store_true",
            help="Skip removing or flagging comics whose files no longer exist",
        )

    def handle(self, *args, **options):
        untagged_path = options["path"] or getattr(settings, "UNTAGGED_DIR", "/comics/untagged")
        dry_run = options["dry_run"]
        no_cleanup = options["no_cleanup"]

        if not os.path.exists(untagged_path):
            self.stderr.write(self.style.ERROR(f"Untagged path does not exist: {untagged_path}"))
            return

        self.stdout.write(f"Scanning untagged folder: {untagged_path}")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no changes will be made"))

        # Cleanup: remove comics whose files no longer exist
        if not no_cleanup:
            self._cleanup_missing_files(untagged_path, dry_run)

        # Find all comic files
        extensions = (".cbz", ".cbr", ".cb7", ".pdf")
        comic_files = []
        for ext in extensions:
            comic_files.extend(Path(untagged_path).rglob(f"*{ext}"))

        self.stdout.write(f"Found {len(comic_files)} comic files")

        imported = 0
        skipped = 0
        errors = 0

        for file_path in comic_files:
            file_path_str = str(file_path)

            # Check if already imported
            if Comic.objects.filter(file_path=file_path_str).exists():
                skipped += 1
                continue

            try:
                # Parse filename for proposed metadata
                parsed = self.parse_filename(file_path.stem)

                # Get file info
                file_stat = file_path.stat()
                file_format = file_path.suffix.lower().lstrip(".")

                # Extract page count for CBZ files
                page_count = None
                is_corrupted = False
                if file_format == "cbz":
                    page_count, is_corrupted = self.get_cbz_page_count(file_path)

                # Detect flags for review queue
                flags = self.detect_flags(
                    file_format=file_format,
                    page_count=page_count,
                    filename=file_path.name,
                    parsed=parsed,
                    is_corrupted=is_corrupted,
                )

                comic_data = {
                    "file_path": file_path_str,
                    "file_format": file_format,
                    "file_size": file_stat.st_size,
                    "page_count": page_count,
                    "state": Comic.STATE_NEW,
                    "medium": Comic.MEDIUM_DIGITAL,
                    "proposed_series": parsed.get("series"),
                    "proposed_number": parsed.get("number"),
                    "proposed_volume": parsed.get("volume"),
                    "proposed_year": parsed.get("year"),
                    "flags": flags,
                }

                if dry_run:
                    self.stdout.write(
                        f"  Would import: {parsed.get('series', 'Unknown')} "
                        f"#{parsed.get('number', '?')} ({parsed.get('year', '?')})"
                    )
                    self.stdout.write(f"    File: {file_path.name}")
                    self.stdout.write(f"    Format: {file_format}, Size: {file_stat.st_size:,} bytes, Pages: {page_count or '?'}")
                    if flags:
                        self.stdout.write(self.style.WARNING(f"    Flags: {', '.join(flags.keys())}"))
                else:
                    Comic.objects.create(**comic_data)
                    imported += 1
                    flag_str = f" [{', '.join(flags.keys())}]" if flags else ""
                    self.stdout.write(
                        f"  Imported: {parsed.get('series', 'Unknown')} "
                        f"#{parsed.get('number', '?')} ({parsed.get('year', '?')}){flag_str}"
                    )

            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Error processing {file_path.name}: {e}"))
                errors += 1

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Imported: {imported}"))
        self.stdout.write(f"Skipped (already exists): {skipped}")
        if errors:
            self.stdout.write(self.style.WARNING(f"Errors: {errors}"))

    def parse_filename(self, filename: str) -> dict:
        """
        Parse comic filename to extract series, number, volume, and year.

        Handles common patterns like:
        - "Detective Comics 1094 (2025) (Digital) (PyrateGoneKiwi)"
        - "Batman #050 (2018)"
        - "Amazing Spider-Man v2 #001 (1999)"
        - "X-Men (2021) 001"
        - "Batman Beyond - Neo-Gothic 006 (2024) (Digital) (Walkabout-Empire)"
        - "Catwoman 061 (2024) (Digital) (Goobadaddy-Empire)"
        """
        result = {
            "series": None,
            "number": None,
            "volume": None,
            "year": None,
        }

        clean_name = filename

        # First extract year from parentheses - (2025), (2021), etc.
        year_match = re.search(r'\((\d{4})\)', clean_name)
        if year_match:
            result["year"] = int(year_match.group(1))

        # Remove ALL parenthesized content (year, Digital, scanner names, etc.)
        clean_name = re.sub(r'\s*\([^)]*\)', '', clean_name).strip()

        # Extract volume - v2, Vol. 3, Volume 4
        vol_match = re.search(r'\b[vV](?:ol(?:ume)?\.?\s*)?(\d+)\b', clean_name)
        if vol_match:
            result["volume"] = int(vol_match.group(1))
            clean_name = re.sub(r'\b[vV](?:ol(?:ume)?\.?\s*)?\d+\b', '', clean_name).strip()

        # Extract issue number - multiple patterns
        # Try hash format first: #001, #1, #12.1
        num_match = re.search(r'#(\d+(?:\.\d+)?)', clean_name)
        if num_match:
            result["number"] = num_match.group(1).lstrip("0") or "0"
            clean_name = clean_name.replace(num_match.group(0), "").strip()
        else:
            # Try trailing number (most common): "Catwoman 061", "Batman Beyond - Neo-Gothic 006"
            # Match 2-4 digit numbers at end of string (after stripping parentheses)
            num_match = re.search(r'\s+(\d{2,4})\s*$', clean_name)
            if num_match:
                result["number"] = num_match.group(1).lstrip("0") or "0"
                clean_name = clean_name[:num_match.start()].strip()
            else:
                # Try single digit or decimal: "Issue 5", "Batman 1.5"
                num_match = re.search(r'\s+(\d+(?:\.\d+)?)\s*$', clean_name)
                if num_match:
                    result["number"] = num_match.group(1).lstrip("0") or "0"
                    clean_name = clean_name[:num_match.start()].strip()

        # What's left is the series name
        series = clean_name.strip()
        # Clean up extra spaces
        series = re.sub(r'\s+', ' ', series)
        # Remove trailing dashes or hyphens (but preserve internal ones like "Spider-Man")
        series = re.sub(r'\s*-\s*$', '', series)
        series = re.sub(r'\s+-$', '', series)

        if series:
            result["series"] = series

        return result

    def get_cbz_page_count(self, cbz_path: Path) -> tuple[int | None, bool]:
        """
        Count image files inside a CBZ archive.

        Returns (count, is_corrupted):
        - (count, False) on success (count may be None if no images found)
        - (None, True) if the archive is corrupted or truncated
        """
        try:
            with zipfile.ZipFile(cbz_path, "r") as zf:
                count = len(list_pages(zf.namelist()))
                return (count if count > 0 else None, False)
        except (zipfile.BadZipFile, EOFError):
            return (None, True)

    def detect_flags(
        self,
        file_format: str,
        page_count: int | None,
        filename: str,
        parsed: dict,
        is_corrupted: bool = False,
    ) -> dict:
        """
        Detect issues that need user review.

        Flags:
        - corrupted_archive: CBZ archive is corrupted or truncated
        - low_page_count: Less than 5 pages (configurable)
        - is_pdf: PDF files need manual review
        - no_series: Couldn't parse series name from filename
        - cover_only: Likely just a cover (≤3 pages + "cover" in filename)
        - needs_conversion: CBR/CB7 files need conversion to CBZ
        """
        flags = {}
        filename_lower = filename.lower()

        # Corrupted or truncated archive
        if is_corrupted:
            flags["corrupted_archive"] = True

        # 1.2 - Low page count (default threshold: 5)
        min_pages = get_setting("min_page_count", 5)
        if page_count is not None and page_count < min_pages:
            flags["low_page_count"] = True

        # 1.3 - PDF files need review
        if file_format == "pdf":
            flags["is_pdf"] = True

        # 1.4 - No series could be parsed
        if not parsed.get("series"):
            flags["no_series"] = True

        # 1.7 - Cover-only files (≤3 pages and "cover" in filename)
        cover_threshold = get_setting("cover_page_threshold", 3)
        if page_count is not None and page_count <= cover_threshold:
            if "cover" in filename_lower:
                flags["cover_only"] = True

        # 1.8 - Needs conversion (CBR, CB7)
        if file_format in ("cbr", "cb7"):
            flags["needs_conversion"] = True

        return flags

    def _cleanup_missing_files(self, untagged_path: str, dry_run: bool):
        """Drop untouched comics whose files are gone and flag the rest."""
        from apps.core.services import check_missing_files

        result = check_missing_files(untagged_path, dry_run=dry_run)
        if result["skipped"]:
            self.stdout.write(self.style.WARNING(f"Skipped cleanup: {result['reason']}"))
        verb = "Would remove" if dry_run else "Removed"
        if result["removed"]:
            self.stdout.write(f"{verb} {result['removed']} new comic(s) with missing files")
        if result["flagged"]:
            self.stdout.write(f"Flagged {result['flagged']} comic(s) as file_missing")
        self.stdout.write("")
