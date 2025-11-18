"""
Management command to scrape comics against the ComicVine database.

Matches unscraped comics using:
1. Cover image hash matching (phash/ahash) with metadata cross-validation
2. Metadata matching (series + issue number) as fallback
"""

import re

from django.core.management.base import BaseCommand
from django.utils.html import strip_tags

from apps.core.models import Comic
from apps.core.utils import html_to_text
from apps.scraper.comicvine import ComicVineScraper, CVMatch
from apps.scraper.hasher import extract_cover_hashes


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
                    self._apply_match(comic, match)
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
            score = self._metadata_alignment_score(comic, match)
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

    def _metadata_alignment_score(self, comic: Comic, match: CVMatch) -> int:
        """
        Score how well a CV match aligns with parsed metadata.

        Returns:
            0 = no alignment (reject)
            1 = partial/tentative alignment (hash match, no metadata to validate OR issue matches)
            2 = good alignment (series similar + issue matches)
            3 = excellent alignment (series + issue + year match)
        """
        # If we have no parsed metadata, we can't validate - return 1 (tentative match)
        # This allows hash-only matches when filename parsing fails
        if not comic.proposed_series and not comic.proposed_number:
            return 1  # Tentative - hash matched but can't validate

        score = 0

        # Normalize issue numbers for comparison
        proposed_num = self._normalize_issue_number(comic.proposed_number)
        match_num = self._normalize_issue_number(match.issue_number)

        # If we have a proposed number, it must match
        if proposed_num and match_num:
            if proposed_num != match_num:
                return 0
            score = 1  # Issue number matches

        # Check series name similarity
        if comic.proposed_series and match.series:
            if self._series_matches(comic.proposed_series, match.series):
                score = 2  # Series matches

                # Check year alignment
                if comic.proposed_year and match.start_year:
                    try:
                        proposed_year = int(comic.proposed_year)
                        match_year = int(match.start_year)
                        # Allow ±2 year tolerance (cover date vs start year)
                        if abs(proposed_year - match_year) <= 2:
                            score = 3  # Year also matches
                    except (ValueError, TypeError):
                        pass
        elif not comic.proposed_series and score == 0:
            # No series to compare, but we got here - give tentative score
            score = 1

        return score

    def _normalize_issue_number(self, num: str | None) -> str:
        """Normalize issue number for comparison."""
        if not num:
            return ""
        # Remove leading zeros, convert to lowercase
        return num.lstrip("0").lower() or "0"

    def _series_matches(self, proposed: str, matched: str) -> bool:
        """
        Check if series names are similar enough to be the same series.

        Handles cases like:
        - "Batgirl" vs "Batgirl"
        - "Batman" vs "Batman (2016)"
        - "X-Men" vs "X-Men: Gold"
        """
        # Normalize: lowercase, remove punctuation, collapse whitespace
        def normalize(s: str) -> str:
            s = s.lower()
            s = re.sub(r"[^\w\s]", " ", s)  # Replace punctuation with space
            s = re.sub(r"\s+", " ", s).strip()  # Collapse whitespace
            return s

        proposed_norm = normalize(proposed)
        matched_norm = normalize(matched)

        # Exact match
        if proposed_norm == matched_norm:
            return True

        # One contains the other (handles "Batman" vs "Batman 2016")
        if proposed_norm in matched_norm or matched_norm in proposed_norm:
            return True

        # Check if first word matches (handles "Batgirl" vs "Batgirl Returns")
        proposed_words = proposed_norm.split()
        matched_words = matched_norm.split()
        if proposed_words and matched_words and proposed_words[0] == matched_words[0]:
            # First word matches - likely same series
            return True

        return False

    def _try_metadata_match(self, comic: Comic, scraper: ComicVineScraper):
        """Try to match comic by series name and issue number."""
        self.stdout.write("    Trying metadata match (fallback)...")

        if not comic.proposed_series or not comic.proposed_number:
            self.stdout.write("    Missing series or number, skipping metadata match")
            return None

        matches = scraper.match_by_metadata(
            series=comic.proposed_series,
            issue_number=comic.proposed_number,
            year=comic.proposed_year,
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

    def _apply_match(self, comic: Comic, match):
        """Apply ComicVine match data to comic and update state."""
        # Copy confirmed data from match
        comic.series = match.series
        comic.number = match.issue_number
        comic.title = match.title
        comic.publisher = match.publisher
        comic.count = match.issue_count

        # Parse year from start_year or cover_date
        if match.start_year:
            try:
                comic.volume = int(match.start_year)
            except ValueError:
                pass

        if match.cover_date:
            # cover_date format: "2025-04-01"
            try:
                parts = match.cover_date.split("-")
                comic.year = int(parts[0])
                if len(parts) > 1:
                    comic.month = int(parts[1])
                if len(parts) > 2:
                    comic.day = int(parts[2])
            except (ValueError, IndexError):
                pass

        if match.description:
            comic.summary = html_to_text(match.description)

        # Set Notes with CV reference (like ComicRack)
        if not comic.notes and match.issue_id:
            comic.notes = f"Scraped metadata from ComicVine [CVDB{match.issue_id}]."

        if match.teams:
            comic.teams = match.teams
        if match.locations:
            comic.locations = match.locations

        # Store ComicVine IDs in custom_values
        comic.custom_values["comicvine_issue"] = str(match.issue_id)
        comic.custom_values["comicvine_volume"] = str(match.volume_id)
        if match.issue_count:
            comic.custom_values["comicvine_issue_count"] = str(match.issue_count)

        # Record scrape source
        comic.custom_values["scrape_source"] = match.match_type
        comic.custom_values["scrape_score"] = str(match.match_score)

        # Update state
        comic.state = Comic.STATE_SCRAPED

        comic.save()
