"""
ComicVine local database scraper.

Matches comics against the local ComicVine SQLite database using:
1. Cover image hash matching (phash/ahash with hamming distance)
2. Metadata matching (series name + issue number)
"""

import sqlite3
from dataclasses import dataclass
from typing import Optional

from django.conf import settings


@dataclass
class CVMatch:
    """Result of a ComicVine match."""
    issue_id: int
    volume_id: int
    series: str
    issue_number: str
    title: Optional[str]
    cover_date: Optional[str]
    publisher: Optional[str]
    start_year: Optional[str]
    issue_count: Optional[int]
    description: Optional[str]
    image_url: Optional[str]
    cover_url: Optional[str]  # URL to cover image from comic_covers table
    cover_urls: Optional[list[str]] = None  # All cover URLs for this issue (variants)
    match_type: str = ""  # 'phash', 'ahash', 'metadata'
    match_score: int = 0  # hamming distance for hash, 0 for exact metadata


class ComicVineScraper:
    """Scraper that queries the local ComicVine SQLite database."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or getattr(settings, "CV_DB_PATH", "/cv_db/comicvine.db")

    def _get_connection(self):
        """Get a read-only connection to the CV database."""
        return sqlite3.connect(f"file:{self.db_path}?immutable=1", uri=True)

    def match_by_hash(self, phash: int, ahash: int, max_distance: int = 10) -> list[CVMatch]:
        """
        Find matching comics by cover image hash.

        Uses hamming distance to find similar covers. Returns matches
        sorted by distance (best first).
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Get all covers and compute hamming distance in Python
        # (SQLite doesn't have efficient bitwise operations for this)
        cursor.execute("""
            SELECT
                cc.cvid,
                cc.ct_phash,
                cc.ct_ahash,
                i.volume_id,
                i.name as issue_title,
                i.issue_number,
                i.cover_date,
                i.description,
                i.image_url,
                v.name as series,
                v.start_year,
                v.count_of_issues,
                p.name as publisher
            FROM comic_covers cc
            JOIN cv_issue i ON cc.cvid = i.id
            JOIN cv_volume v ON i.volume_id = v.id
            LEFT JOIN cv_publisher p ON v.publisher_id = p.id
            WHERE cc.ct_phash IS NOT NULL OR cc.ct_ahash IS NOT NULL
        """)

        matches = []
        for row in cursor:
            cv_phash = int(row[1]) if row[1] else None
            cv_ahash = int(row[2]) if row[2] else None

            # Compute hamming distances
            phash_dist = self._hamming_distance(phash, cv_phash) if cv_phash else 999
            ahash_dist = self._hamming_distance(ahash, cv_ahash) if cv_ahash else 999

            # Check if either hash matches within threshold
            if phash_dist <= max_distance or ahash_dist <= max_distance:
                best_dist = min(phash_dist, ahash_dist)
                match_type = "phash" if phash_dist <= ahash_dist else "ahash"

                matches.append(CVMatch(
                    issue_id=row[0],
                    volume_id=row[3],
                    title=row[4],
                    issue_number=row[5],
                    cover_date=row[6],
                    description=row[7],
                    image_url=row[8],
                    series=row[9],
                    start_year=row[10],
                    issue_count=row[11],
                    publisher=row[12],
                    match_type=match_type,
                    match_score=best_dist,
                ))

        conn.close()

        # Sort by match score (best first)
        matches.sort(key=lambda m: m.match_score)
        return matches

    def match_by_hash_fast(self, phash: int, ahash: int, max_distance: int = 10, limit: int = 10) -> list[CVMatch]:
        """
        Fast hash matching using SQL-based hamming distance.

        Uses a SQL user-defined function to compute hamming distance
        directly in the database, filtering results efficiently.
        """
        conn = self._get_connection()

        # Register hamming distance function (takes two args, computes XOR + popcount)
        def calc_hamming(a, b):
            if a is None or b is None:
                return 64  # Max distance if null
            return bin(int(a) ^ int(b)).count("1")

        conn.create_function("calc_hamming", 2, calc_hamming)

        cursor = conn.cursor()

        # Convert to strings for the database (hashes stored as text/integers)
        phash_str = str(phash)
        ahash_str = str(ahash)

        # Query with hamming distance filter - very fast with the UDF
        cursor.execute("""
            SELECT
                cc.cvid,
                cc.ct_phash,
                cc.ct_ahash,
                i.volume_id,
                i.name as issue_title,
                i.issue_number,
                i.cover_date,
                i.description,
                i.image_url,
                v.name as series,
                v.start_year,
                v.count_of_issues,
                p.name as publisher,
                cc.cv_url,
                calc_hamming(cc.ct_phash, ?) as phash_dist,
                calc_hamming(cc.ct_ahash, ?) as ahash_dist
            FROM comic_covers cc
            JOIN cv_issue i ON cc.cvid = i.id
            JOIN cv_volume v ON i.volume_id = v.id
            LEFT JOIN cv_publisher p ON v.publisher_id = p.id
            WHERE cc.ct_phash IS NOT NULL
              AND cc.ct_ahash IS NOT NULL
              AND calc_hamming(cc.ct_phash, ?) <= ?
              AND calc_hamming(cc.ct_ahash, ?) <= ?
            ORDER BY (calc_hamming(cc.ct_phash, ?) + calc_hamming(cc.ct_ahash, ?)) ASC
            LIMIT ?
        """, (phash_str, ahash_str, phash_str, max_distance, ahash_str, max_distance, phash_str, ahash_str, limit))

        matches = []
        for row in cursor.fetchall():
            phash_dist = row[14]
            ahash_dist = row[15]
            combined_score = phash_dist + ahash_dist
            match_type = f"hash(p:{phash_dist},a:{ahash_dist})"

            matches.append(CVMatch(
                issue_id=row[0],
                volume_id=row[3],
                title=row[4],
                issue_number=row[5],
                cover_date=row[6],
                description=row[7],
                image_url=row[8],
                series=row[9],
                start_year=row[10],
                issue_count=row[11],
                publisher=row[12],
                cover_url=row[13],
                match_type=match_type,
                match_score=combined_score,
            ))

        conn.close()
        return matches

    def match_by_metadata(self, series: str, issue_number: str, year: int = None) -> list[CVMatch]:
        """
        Find matching comics by series name and issue number.

        Uses fuzzy matching on series name via FTS if available.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Normalize issue number (remove leading zeros)
        issue_num_normalized = issue_number.lstrip("0") or "0"

        # Try exact match first (no cover join - covers fetched separately)
        query = """
            SELECT
                i.id as issue_id,
                i.volume_id,
                i.name as issue_title,
                i.issue_number,
                i.cover_date,
                i.description,
                i.image_url,
                v.name as series,
                v.start_year,
                v.count_of_issues,
                p.name as publisher
            FROM cv_issue i
            JOIN cv_volume v ON i.volume_id = v.id
            LEFT JOIN cv_publisher p ON v.publisher_id = p.id
            WHERE LOWER(v.name) = LOWER(?)
              AND (i.issue_number = ? OR i.issue_number = ?)
        """
        params = [series, issue_number, issue_num_normalized]

        # Add year filter if provided
        if year:
            query += " AND v.start_year = ?"
            params.append(str(year))

        query += " ORDER BY v.count_of_issues DESC LIMIT 10"

        cursor.execute(query, params)
        matches = []

        for row in cursor.fetchall():
            matches.append(CVMatch(
                issue_id=row[0],
                volume_id=row[1],
                title=row[2],
                issue_number=row[3],
                cover_date=row[4],
                description=row[5],
                image_url=row[6],
                series=row[7],
                start_year=row[8],
                issue_count=row[9],
                publisher=row[10],
                cover_url=None,  # Will be populated by enrich_matches_with_covers
                match_type="metadata",
                match_score=0,
            ))

        # If no exact match, try LIKE match
        if not matches:
            cursor.execute("""
                SELECT
                    i.id as issue_id,
                    i.volume_id,
                    i.name as issue_title,
                    i.issue_number,
                    i.cover_date,
                    i.description,
                    i.image_url,
                    v.name as series,
                    v.start_year,
                    v.count_of_issues,
                    p.name as publisher
                FROM cv_issue i
                JOIN cv_volume v ON i.volume_id = v.id
                LEFT JOIN cv_publisher p ON v.publisher_id = p.id
                WHERE LOWER(v.name) LIKE LOWER(?)
                  AND (i.issue_number = ? OR i.issue_number = ?)
                ORDER BY v.count_of_issues DESC
                LIMIT 10
            """, (f"%{series}%", issue_number, issue_num_normalized))

            for row in cursor.fetchall():
                matches.append(CVMatch(
                    issue_id=row[0],
                    volume_id=row[1],
                    title=row[2],
                    issue_number=row[3],
                    cover_date=row[4],
                    description=row[5],
                    image_url=row[6],
                    series=row[7],
                    start_year=row[8],
                    issue_count=row[9],
                    publisher=row[10],
                    cover_url=None,  # Will be populated by enrich_matches_with_covers
                    match_type="metadata",
                    match_score=1,  # fuzzy match penalty
                ))

        conn.close()
        return matches

    def get_issue_details(self, issue_id: int) -> Optional[CVMatch]:
        """Get full details for a specific issue by ID."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                i.id as issue_id,
                i.volume_id,
                i.name as issue_title,
                i.issue_number,
                i.cover_date,
                i.description,
                i.image_url,
                v.name as series,
                v.start_year,
                v.count_of_issues,
                p.name as publisher
            FROM cv_issue i
            JOIN cv_volume v ON i.volume_id = v.id
            LEFT JOIN cv_publisher p ON v.publisher_id = p.id
            WHERE i.id = ?
        """, (issue_id,))

        row = cursor.fetchone()

        if not row:
            conn.close()
            return None

        # Get all covers for this issue
        cover_urls = self.get_all_covers(issue_id)
        conn.close()

        return CVMatch(
            issue_id=row[0],
            volume_id=row[1],
            title=row[2],
            issue_number=row[3],
            cover_date=row[4],
            description=row[5],
            image_url=row[6],
            series=row[7],
            start_year=row[8],
            issue_count=row[9],
            publisher=row[10],
            cover_url=cover_urls[0] if cover_urls else None,
            cover_urls=cover_urls,
            match_type="direct",
            match_score=0,
        )

    def get_all_covers(self, issue_id: int) -> list[str]:
        """Get all cover URLs for a specific issue (including variants)."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT cv_url FROM comic_covers WHERE cvid = ? AND cv_url IS NOT NULL
        """, (issue_id,))

        covers = [row[0] for row in cursor.fetchall()]
        conn.close()
        return covers

    def enrich_matches_with_covers(self, matches: list[CVMatch]) -> list[CVMatch]:
        """Add all cover URLs to each match."""
        conn = self._get_connection()
        cursor = conn.cursor()

        issue_ids = [m.issue_id for m in matches]
        if not issue_ids:
            return matches

        placeholders = ",".join("?" * len(issue_ids))
        cursor.execute(f"""
            SELECT cvid, cv_url FROM comic_covers
            WHERE cvid IN ({placeholders}) AND cv_url IS NOT NULL
        """, issue_ids)

        # Group covers by issue ID
        covers_by_issue: dict[int, list[str]] = {}
        for row in cursor.fetchall():
            cvid, url = row
            if cvid not in covers_by_issue:
                covers_by_issue[cvid] = []
            covers_by_issue[cvid].append(url)

        conn.close()

        # Enrich matches
        for match in matches:
            match.cover_urls = covers_by_issue.get(match.issue_id, [])
            # Set cover_url to first if not already set
            if not match.cover_url and match.cover_urls:
                match.cover_url = match.cover_urls[0]

        return matches

    @staticmethod
    def _hamming_distance(h1: int, h2: int) -> int:
        """Compute hamming distance between two hash integers."""
        return bin(h1 ^ h2).count("1")
