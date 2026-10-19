"""
Fill in the Imprint of comics imported before 1.1.1 from the <Imprint> element
in their ComicInfo.xml. Older versions dropped it on import, and a write would
replace the ComicInfo.xml without it. Only comics without an imprint are
changed, and the files are only read.

Usage:
    python manage.py backfill_imprint --dry-run
    python manage.py backfill_imprint
"""

import os

from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.core.models import Comic
from apps.core.utils import read_comicinfo_xml


class Command(BaseCommand):
    help = "Fill in empty Imprint fields from the ComicInfo.xml in each comic's file"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List the imprints that would be set without changing anything",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        comics = (
            Comic.objects.filter(medium=Comic.MEDIUM_DIGITAL)
            .exclude(file_path__isnull=True)
            .exclude(file_path="")
            .filter(Q(imprint__isnull=True) | Q(imprint=""))
            .order_by("file_path")
        )

        checked = filled = missing = 0
        for comic in comics.iterator():
            checked += 1
            if not os.path.exists(comic.file_path):
                missing += 1
                continue
            data = read_comicinfo_xml(comic.file_path) or {}
            imprint = str(data.get("imprint") or "").strip()
            if not imprint:
                continue
            filled += 1
            if dry_run:
                self.stdout.write(f"  Would set {imprint}: {comic.file_path}")
                continue
            # Saving the field marks library comics Needs Re-organize, like an edit
            comic.imprint = imprint
            comic.save(update_fields=["imprint", "updated_at"])
            self.stdout.write(f"  Set {imprint}: {comic.file_path}")

        self.stdout.write("")
        self.stdout.write(f"Checked {checked} comic(s) without an imprint.")
        if missing:
            self.stdout.write(self.style.WARNING(f"Skipped {missing} whose file is missing."))
        if dry_run:
            self.stdout.write(f"Would set the imprint on {filled}. Run without --dry-run to set them.")
            return
        self.stdout.write(self.style.SUCCESS(f"Set the imprint on {filled}."))
        if filled:
            self.stdout.write(
                "Comics already in the library are now marked Needs Re-organize. Check the new "
                "paths on the Path Audit page before running Re-organize."
            )
