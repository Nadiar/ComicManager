"""
Generate a small set of synthetic comics for trying out a fresh install.

Usage:
    python manage.py make_sample_library /comics/untagged
"""

from django.core.management.base import BaseCommand

from apps.core.sample_data import make_sample_library


class Command(BaseCommand):
    help = "Write synthetic sample comics into a folder (never touches real files)"

    def add_arguments(self, parser):
        parser.add_argument("folder", help="Folder to write the sample comics into")

    def handle(self, *args, **options):
        created = make_sample_library(options["folder"])
        self.stdout.write(f"Created {len(created)} sample comics in {options['folder']}")
