"""
Set Year, Month and Day from ComicVine's in-store date on comics that were
scraped before their publisher was added to the in-store date list
(Settings > Scraping > Use in-store date for). The dates come from the local
comicvine.db; without one, scrape the comics again instead.

Only comics with a ComicVine issue ID are changed. Issues without an in-store
date in comicvine.db keep their date.

Usage:
    python manage.py apply_store_dates --dry-run
    python manage.py apply_store_dates
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from apps.core.models import Comic
from apps.scraper.comicvine import ComicVineScraper
from apps.scraper.cv_sources import is_cv_db_available
from apps.scraper.services import store_date_publishers, valid_store_date


class Command(BaseCommand):
    help = "Set the date of scraped comics from ComicVine's in-store date for the publishers in the in-store date list"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List the dates that would change without changing anything",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        names = store_date_publishers()
        if not names:
            raise CommandError("No publishers are set under Settings > Scraping > Use in-store date for.")
        if not is_cv_db_available():
            raise CommandError("No local comicvine.db. Scrape the comics again to use their in-store date.")

        listed = Q()
        for name in names:
            listed |= Q(publisher__icontains=name)
        comics = []
        for comic in Comic.objects.filter(listed, custom_values__has_key="comicvine_issue").order_by("series", "number"):
            try:
                comics.append((comic, int(comic.custom_values["comicvine_issue"])))
            except (TypeError, ValueError):
                continue

        dates = ComicVineScraper().get_store_dates(issue_id for _, issue_id in comics)
        changed = same = no_date = 0
        for comic, issue_id in comics:
            store = valid_store_date(dates.get(issue_id))
            if not store:
                no_date += 1
                continue
            new = tuple(int(part) for part in store.split("-"))
            old = (comic.year, comic.month, comic.day)
            if old == new:
                same += 1
                continue
            changed += 1
            shown = "-".join(f"{part:02d}" if part else "?" for part in old)
            label = f"{comic.series} #{comic.number}" if comic.series else comic.file_path
            if dry_run:
                self.stdout.write(f"  Would change {shown} to {store}: {label}")
                continue
            comic.year, comic.month, comic.day = new
            comic.save(update_fields=["year", "month", "day", "updated_at"])
            self.stdout.write(f"  Changed {shown} to {store}: {label}")

        self.stdout.write("")
        self.stdout.write(f"Checked {len(comics)} scraped comic(s) from the listed publishers.")
        if same:
            self.stdout.write(f"{same} already have their in-store date.")
        if no_date:
            self.stdout.write(f"{no_date} have no in-store date in comicvine.db and keep their date.")
        if dry_run:
            self.stdout.write(f"Would change the date of {changed}. Run without --dry-run to change them.")
            return
        self.stdout.write(self.style.SUCCESS(f"Changed the date of {changed}."))
        if changed:
            self.stdout.write(
                "Comics already written by ComicManager show as Stale Metadata on the dashboard; "
                "use Write Stale there to update their files. The others get the new date in "
                "their file the next time they are written."
            )
