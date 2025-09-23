"""
Management command to import a dataman.dat file into the database.

Usage:
    python manage.py import_datamanager /path/to/dataman.dat
    python manage.py import_datamanager /path/to/dataman.dat --clear
"""

from django.core.management.base import BaseCommand

from apps.tagging.parser import import_datamanager_file


class Command(BaseCommand):
    help = "Import a ComicRack DataManager XML file (dataman.dat)"

    def add_arguments(self, parser):
        parser.add_argument(
            "file_path",
            type=str,
            help="Path to the dataman.dat file",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear all existing rulesets before importing",
        )

    def handle(self, *args, **options):
        file_path = options["file_path"]
        clear_existing = options["clear"]

        if clear_existing:
            self.stdout.write(self.style.WARNING("Clearing all existing rulesets..."))

        self.stdout.write(f"Importing from {file_path}...")

        try:
            with open(file_path, "rb") as f:
                created, skipped = import_datamanager_file(f, clear_existing=clear_existing)
        except FileNotFoundError:
            self.stderr.write(self.style.ERROR(f"File not found: {file_path}"))
            return
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error importing file: {e}"))
            return

        self.stdout.write(
            self.style.SUCCESS(f"Import complete: {created} rulesets created, {skipped} skipped (duplicates)")
        )
