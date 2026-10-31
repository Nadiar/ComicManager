"""
Management command to import existing tagged comics from the library folder.

Scans /comics/library for .cbz files, reads their ComicInfo.xml metadata,
and creates Comic records with state='written' (already fully processed).

Optionally reads ComicRack's ComicDb.xml to enrich imports with Tags,
Teams, Locations, and CustomValuesStore data not present in ComicInfo.xml.
"""

import os
import re
import zipfile
import defusedxml.ElementTree as ET
from collections import Counter
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand
from django.conf import settings

from apps.core.archives import misnamed_format
from apps.core.models import Comic
from apps.core.utils import FIELD_MAP


class MisnamedArchiveError(ValueError):
    """A .cbz that is really a RAR or 7-Zip archive."""


_CHAR_REF = re.compile(r"&#(?:(\d+)|[xX]([0-9a-fA-F]+));")


def decode_custom_value(text: str) -> str:
    """
    Decode the character references ComicRack writes in a CustomValuesStore: a
    comma or equals sign inside a name or value is stored as &#44; or &#61;,
    because the store separates its pairs with them.
    """
    def char(m):
        try:
            return chr(int(m.group(1)) if m.group(1) else int(m.group(2), 16))
        except (ValueError, OverflowError):
            return m.group(0)
    return _CHAR_REF.sub(char, text)


def comicdb_root(folder: str) -> str:
    """A ComicRack folder in the form match_comicdb_paths compares: forward slashes and a trailing slash."""
    return folder.replace("\\", "/").rstrip("/") + "/"


def match_comicdb_paths(book_paths, rel_paths: set, roots=None) -> tuple[dict, list]:
    """
    Match ComicDb.xml Book paths to the scanned library files.

    ComicRack stores full paths such as B:\\Comics\\ComicRack\\Marvel\\X.cbz.
    Without roots, each Book path is matched by the longest end of it that is
    a library file (relative path), and the folder before that end is its
    root. With roots (ComicRack folders), a Book only matches when the path
    under one of them is a library file. When two Books match the same file,
    the given root that comes first wins, or else the root that matches the
    most files.

    Returns ({book path: relative path}, [(root as written in ComicDb.xml, files), ...]),
    roots in the order they win.
    """
    wanted = [comicdb_root(r) for r in roots or []]
    found = {}  # relative path -> [(root, book path)]
    counts = Counter()
    shown = {}  # root -> root as written in ComicDb.xml
    for book_path in book_paths:
        path = book_path.replace("\\", "/")
        root = None
        if wanted:
            for r in wanted:
                if path[:len(r)].lower() == r.lower() and path[len(r):] in rel_paths:
                    root = r
                    break
        else:
            i = path.find("/")
            while i != -1:
                if path[i + 1:] in rel_paths:
                    root = path[:i + 1]
                    break
                i = path.find("/", i + 1)
        if root is None:
            continue
        counts[root] += 1
        shown.setdefault(root, book_path[:len(root)])
        found.setdefault(path[len(root):], []).append((root, book_path))

    if wanted:
        order = [r for r in wanted if r in counts]
    else:
        order = sorted(counts, key=lambda r: (-counts[r], r))
    rank = {r: i for i, r in enumerate(order)}
    matched = {}
    for rel_path, books in found.items():
        root, book_path = min(books, key=lambda b: rank[b[0]])
        matched[book_path] = rel_path
    return matched, [(shown[r], counts[r]) for r in order]


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
        parser.add_argument(
            "--comicdb",
            type=str,
            default=None,
            help="Path to ComicRack's ComicDb.xml for enriching imports with Tags, Teams, Locations, and "
                 "CustomValuesStore, and for importing files without ComicInfo.xml from their ComicDb.xml entry",
        )
        parser.add_argument(
            "--comicdb-root",
            action="append",
            default=None,
            help="ComicRack's library folder as written in ComicDb.xml, for example B:\\Comics\\ComicRack. "
                 "Found automatically when left out. Repeat it for more folders; the first one wins when "
                 "a file is under more than one",
        )

    def handle(self, *args, **options):
        library_path = options["path"] or getattr(settings, "LIBRARY_DIR", "/comics/library")
        dry_run = options["dry_run"]
        comicdb_path = options["comicdb"]

        if options["comicdb_root"] and not comicdb_path:
            self.stderr.write(self.style.ERROR("--comicdb-root only works together with --comicdb"))
            return

        if not os.path.exists(library_path):
            self.stderr.write(self.style.ERROR(f"Library path does not exist: {library_path}"))
            return

        # Ensure library_path ends without trailing slash for consistent relative path calculation
        library_path = library_path.rstrip("/")

        self.stdout.write(f"Scanning library: {library_path}")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no changes will be made"))

        cbz_files = [
            p for p in Path(library_path).rglob("*")
            if p.suffix.lower() == ".cbz" and not p.name.startswith(".") and p.is_file()
        ]
        self.stdout.write(f"Found {len(cbz_files)} .cbz files")

        # Parse ComicDb.xml if provided
        comicdb_lookup = {}
        comicdb_files = {}
        if comicdb_path:
            if not os.path.exists(comicdb_path):
                self.stderr.write(self.style.ERROR(f"ComicDb.xml not found: {comicdb_path}"))
                return
            self.stdout.write(f"Parsing ComicDb.xml: {comicdb_path}")
            book_data, book_paths = self.parse_comicdb(comicdb_path)
            self.stdout.write(f"Loaded {len(book_paths)} entries from ComicDb.xml")
            rel_paths = {str(p)[len(library_path):].lstrip("/") for p in cbz_files}
            comicdb_files, roots = match_comicdb_paths(book_paths, rel_paths, options["comicdb_root"])
            if cbz_files and not comicdb_files:
                # Stop here: a second run skips the comics already imported, so
                # they could not be enriched later
                under = ""
                if options["comicdb_root"]:
                    under = " under " + ", ".join(options["comicdb_root"])
                self.stderr.write(self.style.ERROR(
                    f"No ComicDb.xml entry{under} matches a .cbz file in {library_path}, so nothing was "
                    f"imported. The library folder must hold the same folders and file names as ComicRack's "
                    f"library folder."
                ))
                if book_paths:
                    self.stderr.write(f"First entry in ComicDb.xml: {book_paths[0]}")
                return
            self.stdout.write(f"ComicDb.xml entries matching files in {library_path}: {len(comicdb_files)}")
            for root, count in roots[:5]:
                self.stdout.write(f"  {root}  ({count} file{'' if count == 1 else 's'})")
            if len(roots) > 5:
                self.stdout.write(f"  and {len(roots) - 5} more folders")
            if len(roots) > 1:
                self.stdout.write(
                    "A file found under more than one of these ComicRack folders uses the entry from the "
                    "first one. Use --comicdb-root to choose the folders yourself."
                )
            comicdb_lookup = {comicdb_files[p]: data for p, data in book_data.items() if p in comicdb_files}

        # Next to the audit log in /app/logs, which is mounted to data/logs on the
        # host (the image's /app is not writable by the container user)
        log_dir = Path(settings.AUDIT_LOG_PATH).parent
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "import_errors.log"

        imported = 0
        skipped = 0
        errors = 0
        misnamed = 0
        enriched = 0
        from_comicdb = 0
        # Files without ComicInfo.xml; imported from their ComicDb.xml entry below
        no_info = []

        with open(log_path, "a") as log_file:
            run_header = f"\n--- Import run {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | library: {library_path} ---\n"
            log_file.write(run_header)

        def log_error(msg: str) -> None:
            with open(log_path, "a") as lf:
                lf.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")

        def save(comic_data: dict, cbz_path: Path) -> None:
            nonlocal imported, enriched
            file_path_str = str(cbz_path)
            comic_data["file_path"] = file_path_str
            comic_data["file_format"] = "cbz"
            comic_data["file_size"] = cbz_path.stat().st_size
            comic_data["state"] = Comic.STATE_WRITTEN
            comic_data["medium"] = Comic.MEDIUM_DIGITAL

            # Enrich with ComicDb.xml data if available
            if comicdb_lookup:
                rel_path = file_path_str[len(library_path):].lstrip("/")
                if rel_path in comicdb_lookup:
                    db_extra = comicdb_lookup[rel_path]
                    # Set fields that ComicInfo.xml might not have
                    for field in ("tags", "teams", "locations", "main_character_or_team", "series_group"):
                        if field in db_extra and not comic_data.get(field):
                            comic_data[field] = db_extra[field]
                    # Merge custom values (ComicInfo.xml takes precedence)
                    if "custom_values" in db_extra:
                        merged_cv = dict(db_extra["custom_values"])
                        merged_cv.update(comic_data.get("custom_values", {}))
                        comic_data["custom_values"] = merged_cv
                    enriched += 1

            if dry_run:
                extra = ""
                rel_path = file_path_str[len(library_path):].lstrip("/")
                if comicdb_lookup and rel_path in comicdb_lookup:
                    extra = " [+ComicDb]"
                self.stdout.write(f"  Would import: {comic_data.get('series', 'Unknown')} #{comic_data.get('number', '?')}{extra}")
            else:
                Comic.objects.create(**comic_data)
            imported += 1

            if not dry_run and imported % 100 == 0:
                self.stdout.write(f"  Imported {imported} comics...")

        for cbz_path in cbz_files:
            file_path_str = str(cbz_path)

            # Check if already imported
            if Comic.objects.filter(file_path=file_path_str).exists():
                skipped += 1
                continue

            try:
                comic_data = self.extract_comic_info(cbz_path)
                if comic_data is None and comicdb_files:
                    no_info.append(cbz_path)
                    continue
                if comic_data is None:
                    msg = f"No ComicInfo.xml in: {cbz_path.name}"
                    self.stderr.write(self.style.WARNING(msg))
                    log_error(msg)
                    errors += 1
                    continue

                save(comic_data, cbz_path)

            except Exception as e:
                msg = f"Error processing {cbz_path.name}: {e}"
                self.stderr.write(self.style.ERROR(msg))
                log_error(msg)
                errors += 1
                if isinstance(e, MisnamedArchiveError):
                    misnamed += 1

        if no_info:
            self.stdout.write(f"Reading ComicDb.xml entries for {len(no_info)} file(s) without ComicInfo.xml")
            wanted = {str(p)[len(library_path):].lstrip("/"): p for p in no_info}
            book_paths = {p: rel for p, rel in comicdb_files.items() if rel in wanted}
            books = self.parse_comicdb_books(comicdb_path, book_paths)
            for rel_path, cbz_path in wanted.items():
                comic_data = books.get(rel_path)
                if not comic_data or not comic_data.get("series"):
                    msg = f"No ComicInfo.xml and no ComicDb.xml entry for: {cbz_path.name}"
                    self.stderr.write(self.style.WARNING(msg))
                    log_error(msg)
                    errors += 1
                    continue
                try:
                    save(comic_data, cbz_path)
                    from_comicdb += 1
                except Exception as e:
                    msg = f"Error processing {cbz_path.name}: {e}"
                    self.stderr.write(self.style.ERROR(msg))
                    log_error(msg)
                    errors += 1

        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"Would import: {imported}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Imported: {imported}"))
        self.stdout.write(f"Skipped (already exists): {skipped}")
        if comicdb_files and dry_run:
            self.stdout.write(f"Would be enriched from ComicDb.xml: {enriched}")
            self.stdout.write(f"Would be imported from ComicDb.xml (no ComicInfo.xml in the file): {from_comicdb}")
        elif comicdb_files:
            self.stdout.write(f"Enriched from ComicDb.xml: {enriched}")
            self.stdout.write(f"Imported from ComicDb.xml (no ComicInfo.xml in the file): {from_comicdb}")
        if errors:
            self.stdout.write(self.style.WARNING(f"Errors: {errors}"))
            self.stdout.write(self.style.WARNING(f"Error log: {log_path}"))
        if misnamed:
            self.stdout.write(self.style.WARNING(
                f"{misnamed} of the errors are RAR/7-Zip archives named .cbz. Convert them with "
                f"`python manage.py convert_misnamed_archives`, then run import_library again."
            ))

    def parse_comicdb(self, comicdb_path: str) -> tuple[dict, list]:
        """
        Parse ComicRack's ComicDb.xml into a lookup dict keyed by the Book's
        path as written in ComicDb.xml, plus the list of all Book paths.

        Uses iterparse for memory efficiency with large files (~44K entries).
        """
        lookup = {}
        book_paths = []
        for event, elem in ET.iterparse(comicdb_path, events=("end",)):
            if elem.tag != "Book":
                continue

            file_attr = elem.get("File", "")
            if file_attr:
                book_paths.append(file_attr)

            book_data = {}

            # Tags
            tags_el = elem.find("Tags")
            if tags_el is not None and tags_el.text:
                book_data["tags"] = tags_el.text.strip()

            # Teams
            teams_el = elem.find("Teams")
            if teams_el is not None and teams_el.text:
                book_data["teams"] = teams_el.text.strip()

            # Locations
            locations_el = elem.find("Locations")
            if locations_el is not None and locations_el.text:
                book_data["locations"] = locations_el.text.strip()

            # MainCharacterOrTeam
            mcot_el = elem.find("MainCharacterOrTeam")
            if mcot_el is not None and mcot_el.text:
                book_data["main_character_or_team"] = mcot_el.text.strip()

            # SeriesGroup
            sg_el = elem.find("SeriesGroup")
            if sg_el is not None and sg_el.text:
                book_data["series_group"] = sg_el.text.strip()

            # CustomValuesStore: ",key=value,key=value,...", with commas and
            # equals signs inside names and values written as &#44; and &#61;
            cvs_el = elem.find("CustomValuesStore")
            if cvs_el is not None and cvs_el.text:
                custom = {}
                for pair in cvs_el.text.strip().strip(",").split(","):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        k, v = decode_custom_value(k.strip()), decode_custom_value(v.strip())
                        if k and v:
                            custom[k] = v
                if custom:
                    book_data["custom_values"] = custom

            if book_data and file_attr:
                lookup[file_attr] = book_data

            elem.clear()

        return lookup, book_paths

    def parse_comicdb_books(self, comicdb_path: str, book_paths: dict) -> dict:
        """
        Read the full metadata of the given Books ({path in ComicDb.xml:
        relative path}) from ComicDb.xml, keyed by relative path. ComicRack's
        Book elements use the same field names as ComicInfo.xml, so they are
        parsed with the same parser.
        """
        from xml.etree.ElementTree import tostring

        books = {}
        for event, elem in ET.iterparse(comicdb_path, events=("end",)):
            if elem.tag != "Book":
                continue
            rel_path = book_paths.get(elem.get("File", ""))
            if rel_path is not None:
                books[rel_path] = self.parse_comic_info_xml(tostring(elem))
            elem.clear()
        return books

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
            if misnamed_format(cbz_path):
                raise MisnamedArchiveError(
                    "RAR or 7-Zip archive named .cbz; convert it with "
                    "`manage.py convert_misnamed_archives`, then run import_library again"
                )
            raise ValueError("Invalid or corrupted CBZ file")

    def parse_comic_info_xml(self, xml_content: bytes) -> dict:
        """Parse ComicInfo.xml content into a dictionary matching Comic model fields."""
        root = ET.fromstring(xml_content)

        # Integer fields that need conversion
        int_fields = {"count", "volume", "year", "month", "day", "page_count"}

        data = {}

        # Same XML tag -> model field map as reading and writing ComicInfo.xml
        for xml_tag, model_field in FIELD_MAP.items():
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
