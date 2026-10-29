"""
Fill in fields that older versions dropped on import from the ComicInfo.xml in
each comic's file: the Imprint (before 1.1.2) and the Story Arc. A write would
replace the ComicInfo.xml without them. Only empty fields are changed, and the
files are only read.

Usage:
    python manage.py backfill_from_files --dry-run
    python manage.py backfill_from_files
"""

import os

from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.core.models import Comic
from apps.core.utils import read_comicinfo_xml

# Fields older imports dropped, and how the output names them
FIELDS = {"imprint": "imprint", "story_arc": "story arc"}


class Command(BaseCommand):
    help = "Fill in empty Imprint and Story Arc fields from the ComicInfo.xml in each comic's file"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List the values that would be set without changing anything",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        empty = Q()
        for field in FIELDS:
            empty |= Q(**{f"{field}__isnull": True}) | Q(**{field: ""})
        comics = (
            Comic.objects.filter(medium=Comic.MEDIUM_DIGITAL)
            .exclude(file_path__isnull=True)
            .exclude(file_path="")
            .filter(empty)
            .order_by("file_path")
        )

        checked = missing = 0
        filled = dict.fromkeys(FIELDS, 0)
        for comic in comics.iterator():
            checked += 1
            if not os.path.exists(comic.file_path):
                missing += 1
                continue
            data = read_comicinfo_xml(comic.file_path) or {}
            values = {}
            for field in FIELDS:
                value = str(data.get(field) or "").strip()
                if value and not getattr(comic, field):
                    values[field] = value
            if not values:
                continue
            for field in values:
                filled[field] += 1
            shown = ", ".join(f"{FIELDS[field]} {value}" for field, value in values.items())
            if dry_run:
                self.stdout.write(f"  Would set {shown}: {comic.file_path}")
                continue
            # Saving the imprint marks library comics Needs Re-organize, like an edit
            for field, value in values.items():
                setattr(comic, field, value)
            comic.save(update_fields=[*values, "updated_at"])
            self.stdout.write(f"  Set {shown}: {comic.file_path}")

        counts = " and ".join(f"the {FIELDS[field]} on {n}" for field, n in filled.items())
        self.stdout.write("")
        self.stdout.write(f"Checked {checked} comic(s) with an empty imprint or story arc.")
        if missing:
            self.stdout.write(self.style.WARNING(f"Skipped {missing} whose file is missing."))
        if dry_run:
            self.stdout.write(f"Would set {counts}. Run without --dry-run to set them.")
            return
        self.stdout.write(self.style.SUCCESS(f"Set {counts}."))
        if filled["imprint"]:
            self.stdout.write(
                "Comics already in the library are now marked Needs Re-organize. Check the new "
                "paths on the Path Audit page before running Re-organize."
            )
