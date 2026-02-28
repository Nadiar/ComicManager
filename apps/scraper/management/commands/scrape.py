"""
Management command to scrape comics against the ComicVine database.

Matches unscraped comics using:
1. Cover image hash matching (phash/ahash) with metadata cross-validation
2. Metadata matching (series + issue number) as fallback
"""

from django.core.management.base import BaseCommand

from apps.core.models import Comic
from apps.scraper.comicvine import ComicVineScraper, CVMatch
from apps.scraper.hasher import extract_cover_hashes
from apps.scraper.services import (
    metadata_alignment_score,
    normalize_issue_number,
    series_matches,
    apply_cv_match,
)


class Command(BaseCommand):
    help = "Scrape comics against the ComicVine database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show matches without updating the database",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit number of comics to process",
        )
        parser.add_argument(
            "--comic-id",
            type=str,
            default=None,
            help="Scrape a specific comic by UUID",
        )
        parser.add_argument(
            "--method",
            type=str,
            choices=["hash", "metadata", "both"],
            default="both",
            help="Matching method to use (default: both)",
        )
        parser.add_argument(
            "--max-distance",
            type=int,
            default=10,
            help="Maximum hamming distance for hash matching (default: 10)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        limit = options["limit"]
        comic_id = options["comic_id"]
        method = options["method"]
        max_distance = options["max_distance"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no changes will be made"))

        scraper = ComicVineScraper()

        # Get comics to scrape
        if comic_id:
            comics = Comic.objects.filter(id=comic_id)
            if not comics.exists():
                self.stderr.write(self.style.ERROR(f"Comic not found: {comic_id}"))
                return
        else:
            # Get comics in 'imported' state that need scraping
            comics = Comic.objects.filter(
                state=Comic.STATE_IMPORTED,
                medium=Comic.MEDIUM_DIGITAL,
            )
            if limit:
                comics = comics[:limit]

        total = comics.count()
        self.stdout.write(f"Processing {total} comic(s)")

        matched = 0
        failed = 0

        for comic in comics:
            self.stdout.write(f"\n--- {comic.proposed_series} #{comic.proposed_number} ---")
            self.stdout.write(f"    File: {comic.file_path}")

            match = None

            # Try hash matching first (most reliable)
            if method in ("hash", "both") and comic.file_path:
                match = self._try_hash_match(comic, scraper, max_distance)

            # Fall back to metadata matching
            if not match and method in ("metadata", "both"):
                match = self._try_metadata_match(comic, scraper)

            if match:
                matched += 1
                self.stdout.write(self.style.SUCCESS(
                    f"    MATCH: {match.series} #{match.issue_number} "
                    f"({match.start_year}) - {match.publisher}"
                ))
                self.stdout.write(f"    CV Issue ID: {match.issue_id}")
                self.stdout.write(f"    Match type: {match.match_type} (score: {match.match_score})")

                if not dry_run:
                    apply_cv_match(comic, match)
            else:
                failed += 1
                self.stdout.write(self.style.WARNING("    NO MATCH FOUND"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Matched: {matched}"))
        self.stdout.write(f"Failed: {failed}")

    def _try_hash_match(self, comic: Comic, scraper: ComicVineScraper, max_distance: int):
        """Try to match comic by cover image hash with metadata cross-validation."""
        self.stdout.write("    Trying hash match...")

        # Extract cover hashes
        hashes = extract_cover_hashes(comic.file_path)
        if not hashes:
            self.stdout.write("    Could not extract cover hashes")
            return None

        self.stdout.write(f"    Cover phash: {hashes.phash_hex}")
        self.stdout.write(f"    Cover ahash: {hashes.ahash_hex}")

        # Store hashes on comic for future use
        comic.phash = hashes.phash_hex
        comic.ahash = hashes.ahash_hex

        # Find matches
        matches = scraper.match_by_hash_fast(
            hashes.phash,
            hashes.ahash,
            max_distance=max_distance,
            limit=10,  # Get more candidates for cross-validation
        )

        if not matches:
            return None

        self.stdout.write(f"    Found {len(matches)} hash candidates")

        # Cross-validate hash matches against parsed metadata
        validated = []
        for match in matches:
            score = metadata_alignment_score(comic, match)
            if score > 0:
                validated.append((match, score))
                self.stdout.write(
                    f"      ✓ {match.series} #{match.issue_number} "
                    f"({match.start_year}) - alignment: {score}"
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"      ✗ {match.series} #{match.issue_number} "
                        f"({match.start_year}) - metadata mismatch"
                    )
                )

        if validated:
            # Sort by: alignment score (desc), then hash score (asc)
            validated.sort(key=lambda x: (-x[1], x[0].match_score))
            best = validated[0][0]
            # Update match_type to indicate validation
            best.match_type = f"{best.match_type}+meta"
            return best

        # No validated matches - return None to fall back to metadata-only
        self.stdout.write(self.style.WARNING("    No hash matches passed metadata validation"))
        return None

    def _try_metadata_match(self, comic: Comic, scraper: ComicVineScraper):
        """Try to match comic by series name and issue number."""
        self.stdout.write("    Trying metadata match (fallback)...")

        cv_series = comic.series or comic.proposed_series
        cv_number = comic.number or comic.proposed_number
        cv_year = comic.year or comic.proposed_year

        if not cv_series or not cv_number:
            self.stdout.write("    Missing series or number, skipping metadata match")
            return None

        matches = scraper.match_by_metadata(
            series=cv_series,
            issue_number=cv_number,
            year=cv_year,
        )

        if matches:
            best = matches[0]
            if len(matches) > 1:
                self.stdout.write(f"    Found {len(matches)} metadata matches")
                for m in matches[:3]:
                    self.stdout.write(
                        f"      - {m.series} #{m.issue_number} ({m.start_year}) - {m.publisher}"
                    )
            return best

        return None
