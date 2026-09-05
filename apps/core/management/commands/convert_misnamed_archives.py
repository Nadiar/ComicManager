"""
Convert comics named .cbz that are really RAR or 7-Zip archives into real CBZ
files, in place.

Usage:
    python manage.py convert_misnamed_archives --dry-run
    python manage.py convert_misnamed_archives
    python manage.py convert_misnamed_archives --path /comics/untagged
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.core.archives import convert_archive_to_cbz, misnamed_format
from apps.core.models import Comic


class Command(BaseCommand):
    help = "Convert .cbz files that are really RAR or 7-Zip archives into real CBZ files"

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            type=str,
            default=None,
            help="Folder to search (default: /comics/library)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List the misnamed archives without converting anything",
        )

    def handle(self, *args, **options):
        from apps.core.tasks import _convert_comic_to_cbz

        root = options["path"] or getattr(settings, "LIBRARY_DIR", "/comics/library")
        dry_run = options["dry_run"]
        if not Path(root).is_dir():
            self.stderr.write(self.style.ERROR(f"Folder does not exist: {root}"))
            return

        self.stdout.write(f"Searching {root} for RAR/7-Zip archives named .cbz")
        found = converted = failed = not_imported = 0

        for path in sorted(Path(root).rglob("*")):
            if path.suffix.lower() != ".cbz" or path.name.startswith(".") or not path.is_file():
                continue
            actual = misnamed_format(path)
            if not actual:
                continue
            found += 1
            kind = "RAR" if actual == "cbr" else "7-Zip"
            if dry_run:
                self.stdout.write(f"  Would convert ({kind}): {path}")
                continue

            comic = Comic.objects.filter(file_path=str(path)).first()
            if comic:
                # Record the real format so the regular conversion handles it
                comic.file_format = actual
                result = _convert_comic_to_cbz(comic)
                ok, error = result["success"], result["error"]
            else:
                try:
                    convert_archive_to_cbz(path, path)
                    ok, error = True, None
                    not_imported += 1
                except Exception as e:
                    ok, error = False, str(e)

            if ok:
                converted += 1
                self.stdout.write(f"  Converted ({kind}): {path}")
            else:
                failed += 1
                self.stderr.write(self.style.ERROR(f"  Failed ({kind}): {path}: {error}"))

        self.stdout.write("")
        if dry_run:
            self.stdout.write(f"Found {found} misnamed archive(s). Run without --dry-run to convert them.")
            return
        self.stdout.write(self.style.SUCCESS(f"Converted: {converted}"))
        if failed:
            self.stdout.write(self.style.WARNING(f"Failed: {failed} (originals left unchanged)"))
        if not_imported:
            self.stdout.write(
                "Some converted files were not in the database yet; "
                "run `python manage.py import_library` to import them."
            )
