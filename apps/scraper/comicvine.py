"""
ComicVine scraper.

Matches comics against the local ComicVine SQLite database using:
1. Cover image hash matching (phash/ahash with hamming distance)
2. Metadata matching (series name + issue number)
3. ComicVine API fallback when local DB has no match
"""

import json
import logging
import sqlite3
import time
import urllib.error
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)

CV_API_BASE = "https://comicvine.gamespot.com/api"


class ComicVineRateLimitError(Exception):
    """Raised when ComicVine API returns HTTP 420/429 (rate limited)."""
    pass


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

    # Credits extracted from JSON columns
    characters: Optional[str] = None  # Comma-separated character names
    writer: Optional[str] = None
    penciller: Optional[str] = None
    inker: Optional[str] = None
    colorist: Optional[str] = None
    letterer: Optional[str] = None
    cover_artist: Optional[str] = None
    editor: Optional[str] = None

    # Additional metadata
    web: Optional[str] = None  # ComicVine site_detail_url
    teams: Optional[str] = None  # Comma-separated team names
    locations: Optional[str] = None  # Comma-separated location names
    story_arcs: Optional[str] = None  # Comma-separated story arc names


def _parse_credits_json(person_credits_json) -> dict[str, list[str]]:
    """
    Parse person_credits and extract names by role.

    Accepts a JSON string (from local DB) or an already-parsed list (from API).

    Returns dict like:
    {
        "writer": ["Joshua Williamson"],
        "artist": ["Bruno Redondo", "Caio Filipe"],
        "colorist": ["Adriano Lucas"],
        "letterer": ["Ariana Maher"],
        "cover": ["Jamal Campbell", "Lee Bermejo"],
        "editor": ["Paul Kaminski"],
    }
    """
    if not person_credits_json:
        return {}

    if isinstance(person_credits_json, list):
        credits = person_credits_json
    else:
        try:
            credits = json.loads(person_credits_json)
        except json.JSONDecodeError:
            return {}

    roles: dict[str, list[str]] = {}
    for person in credits:
        name = person.get("name", "")
        role_str = person.get("role", "")
        if not name or not role_str:
            continue

        # Role can be comma-separated like "artist, cover" or "editor, assistant"
        for role in role_str.split(","):
            role = role.strip().lower()
            if role:
                if role not in roles:
                    roles[role] = []
                if name not in roles[role]:
                    roles[role].append(name)

    return roles


def _parse_entity_json(entity_json) -> list[str]:
    """
    Parse character_credits, team_credits, location_credits, or story_arc_credits.

    Accepts a JSON string (from local DB) or an already-parsed list (from API).
    Returns list of names.
    """
    if not entity_json:
        return []

    if isinstance(entity_json, list):
        entities = entity_json
    else:
        try:
            entities = json.loads(entity_json)
        except json.JSONDecodeError:
            return []

    return [e.get("name", "") for e in entities if e.get("name")]


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
        """Get full details for a specific issue by ID, including credits."""
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
                i.site_detail_url,
                i.character_credits,
                i.person_credits,
                i.team_credits,
                i.location_credits,
                i.story_arc_credits,
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

        # Parse credits JSON
        person_credits = _parse_credits_json(row[9])  # person_credits
        characters = _parse_entity_json(row[8])  # character_credits
        teams = _parse_entity_json(row[10])  # team_credits
        locations = _parse_entity_json(row[11])  # location_credits
        story_arcs = _parse_entity_json(row[12])  # story_arc_credits

        # Map roles to fields - artist can mean penciller and/or inker
        writers = person_credits.get("writer", [])
        artists = person_credits.get("artist", [])
        pencillers = person_credits.get("penciller", []) or artists
        inkers = person_credits.get("inker", []) or artists
        colorists = person_credits.get("colorist", [])
        letterers = person_credits.get("letterer", [])
        cover_artists = person_credits.get("cover", [])
        editors = person_credits.get("editor", [])

        return CVMatch(
            issue_id=row[0],
            volume_id=row[1],
            title=row[2],
            issue_number=row[3],
            cover_date=row[4],
            description=row[5],
            image_url=row[6],
            series=row[13],  # v.name
            start_year=row[14],  # v.start_year
            issue_count=row[15],  # v.count_of_issues
            publisher=row[16],  # p.name
            cover_url=cover_urls[0] if cover_urls else None,
            cover_urls=cover_urls,
            match_type="direct",
            match_score=0,
            # Credits
            characters=", ".join(characters) if characters else None,
            writer=", ".join(writers) if writers else None,
            penciller=", ".join(pencillers) if pencillers else None,
            inker=", ".join(inkers) if inkers else None,
            colorist=", ".join(colorists) if colorists else None,
            letterer=", ".join(letterers) if letterers else None,
            cover_artist=", ".join(cover_artists) if cover_artists else None,
            editor=", ".join(editors) if editors else None,
            # Additional metadata
            web=row[7],  # site_detail_url
            teams=", ".join(teams) if teams else None,
            locations=", ".join(locations) if locations else None,
            story_arcs=", ".join(story_arcs) if story_arcs else None,
        )

    def get_all_covers(self, issue_id: int, matched_url: str = None) -> list[str]:
        """
        Get all cover URLs for a specific issue (including variants).

        Args:
            issue_id: The ComicVine issue ID
            matched_url: If provided, this cover will be placed first in the list

        Returns:
            List of cover URLs, with matched_url first (if provided),
            then official covers (/0/4/), then others by id.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Order by: official covers first (/0/4/ path), then by id
        cursor.execute("""
            SELECT cv_url FROM comic_covers
            WHERE cvid = ? AND cv_url IS NOT NULL
            ORDER BY
                CASE WHEN cv_url LIKE '%/0/4/%' THEN 0 ELSE 1 END,
                id ASC
        """, (issue_id,))

        covers = [row[0] for row in cursor.fetchall()]
        conn.close()

        # If a matched URL was provided, move it to the front
        if matched_url and matched_url in covers:
            covers.remove(matched_url)
            covers.insert(0, matched_url)

        return covers

    def enrich_match_with_credits(self, match: CVMatch) -> CVMatch:
        """
        Enrich a match with credits, characters, and other detailed metadata.

        This is called after a match is selected to populate the full details
        that aren't fetched during the initial hash/metadata search.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                site_detail_url,
                character_credits,
                person_credits,
                team_credits,
                location_credits,
                story_arc_credits
            FROM cv_issue
            WHERE id = ?
        """, (match.issue_id,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return match

        # Parse credits JSON
        person_credits = _parse_credits_json(row[2])  # person_credits
        characters = _parse_entity_json(row[1])  # character_credits
        teams = _parse_entity_json(row[3])  # team_credits
        locations = _parse_entity_json(row[4])  # location_credits
        story_arcs = _parse_entity_json(row[5])  # story_arc_credits

        # Map roles to fields - artist can mean penciller and/or inker
        writers = person_credits.get("writer", [])
        artists = person_credits.get("artist", [])
        pencillers = person_credits.get("penciller", []) or artists
        inkers = person_credits.get("inker", []) or artists
        colorists = person_credits.get("colorist", [])
        letterers = person_credits.get("letterer", [])
        cover_artists = person_credits.get("cover", [])
        editors = person_credits.get("editor", [])

        # Update match with credits
        match.web = row[0]
        match.characters = ", ".join(characters) if characters else None
        match.writer = ", ".join(writers) if writers else None
        match.penciller = ", ".join(pencillers) if pencillers else None
        match.inker = ", ".join(inkers) if inkers else None
        match.colorist = ", ".join(colorists) if colorists else None
        match.letterer = ", ".join(letterers) if letterers else None
        match.cover_artist = ", ".join(cover_artists) if cover_artists else None
        match.editor = ", ".join(editors) if editors else None
        match.teams = ", ".join(teams) if teams else None
        match.locations = ", ".join(locations) if locations else None
        match.story_arcs = ", ".join(story_arcs) if story_arcs else None

        return match

    def enrich_matches_with_covers(self, matches: list[CVMatch]) -> list[CVMatch]:
        """
        Add all cover URLs to each match.

        For hash matches, the matched cover (already in cover_url) is placed first.
        For metadata matches, official covers (/0/4/) are prioritized.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        issue_ids = [m.issue_id for m in matches]
        if not issue_ids:
            return matches

        placeholders = ",".join("?" * len(issue_ids))
        # Order by: official covers first (/0/4/ path), then by id
        cursor.execute(f"""
            SELECT cvid, cv_url FROM comic_covers
            WHERE cvid IN ({placeholders}) AND cv_url IS NOT NULL
            ORDER BY
                CASE WHEN cv_url LIKE '%/0/4/%' THEN 0 ELSE 1 END,
                id ASC
        """, issue_ids)

        # Group covers by issue ID (preserving order from query)
        covers_by_issue: dict[int, list[str]] = {}
        for row in cursor.fetchall():
            cvid, url = row
            if cvid not in covers_by_issue:
                covers_by_issue[cvid] = []
            covers_by_issue[cvid].append(url)

        conn.close()

        # Enrich matches
        for match in matches:
            all_covers = covers_by_issue.get(match.issue_id, [])

            # If match already has a cover_url (from hash match), put it first
            if match.cover_url and match.cover_url in all_covers:
                all_covers.remove(match.cover_url)
                all_covers.insert(0, match.cover_url)
            elif not match.cover_url and all_covers:
                # No matched cover - use first from ordered list (official cover)
                match.cover_url = all_covers[0]

            match.cover_urls = all_covers

        return matches

    @staticmethod
    def _hamming_distance(h1: int, h2: int) -> int:
        """Compute hamming distance between two hash integers."""
        return bin(h1 ^ h2).count("1")

    # -------------------------------------------------------------------------
    # ComicVine API methods
    # -------------------------------------------------------------------------

    def _api_request(self, endpoint: str, params: dict = None) -> dict | None:
        """Make a request to the ComicVine API.

        Returns the parsed JSON response or None on error.
        """
        from apps.core.models import get_setting

        api_key = get_setting("cv_api_key", "").strip()
        if not api_key:
            return None

        base_params = {
            "api_key": api_key,
            "format": "json",
        }
        if params:
            base_params.update(params)

        # ComicVine requires a trailing slash on endpoints
        endpoint = endpoint.rstrip("/") + "/"
        url = f"{CV_API_BASE}/{endpoint}?{urllib.parse.urlencode(base_params)}"

        logger.debug("CV API request: %s", url.replace(api_key, "***"))

        # Rate limit: ComicVine enforces ~1 request/second
        now = time.monotonic()
        if hasattr(self, '_last_api_call'):
            elapsed = now - self._last_api_call
            if elapsed < 1.1:
                time.sleep(1.1 - elapsed)
        self._last_api_call = time.monotonic()

        req = urllib.request.Request(url, headers={
            "User-Agent": "ComicManager/1.0 (https://github.com/comicmanager)",
            "Accept": "application/json",
        })

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                if data.get("error") == "OK" and data.get("results") is not None:
                    return data
                logger.warning("CV API error: %s", data.get("error"))
                return None
        except urllib.error.HTTPError as e:
            if e.code in (420, 429):
                logger.warning("CV API rate limited (HTTP %d)", e.code)
                raise ComicVineRateLimitError(
                    "ComicVine API rate limit reached. Wait a minute before retrying."
                )
            logger.warning("CV API request failed: %s", e)
            return None
        except Exception as e:
            logger.warning("CV API request failed: %s", e)
            return None

    def _get_volume_info(self, volume_id: int) -> dict:
        """Fetch publisher and start_year for a volume from the API."""
        data = self._api_request(f"volume/4050-{volume_id}", {
            "field_list": "publisher,start_year,count_of_issues",
        })
        if not data:
            return {}
        result = data.get("results") if isinstance(data.get("results"), dict) else {}
        pub = result.get("publisher") or {}
        return {
            "publisher": pub.get("name"),
            "start_year": result.get("start_year"),
            "issue_count": result.get("count_of_issues"),
        }

    def search_api(self, query: str, limit: int = 10) -> list[CVMatch]:
        """Search the ComicVine API for issues matching a query string."""
        data = self._api_request("search", {
            "resources": "issue",
            "query": query,
            "limit": limit,
        })
        if not data:
            return []

        # Collect unique volume IDs to batch-fetch publisher/year
        volume_ids = set()
        for r in data["results"]:
            vol = r.get("volume") or {}
            if vol.get("id"):
                volume_ids.add(vol["id"])

        # Fetch volume info (publisher, start_year) for each unique volume
        volume_cache = {}
        for vid in volume_ids:
            volume_cache[vid] = self._get_volume_info(vid)

        matches = []
        for r in data["results"]:
            volume = r.get("volume") or {}
            image = r.get("image") or {}
            cover_url = image.get("medium_url") or image.get("small_url")
            cover_urls = []
            if image.get("original_url"):
                cover_urls.append(image["original_url"])
            if cover_url and cover_url not in cover_urls:
                cover_urls.insert(0, cover_url)

            # Get publisher/year from volume cache, fall back to cover_date year
            vol_info = volume_cache.get(volume.get("id"), {})
            cover_date = r.get("cover_date") or ""
            year = vol_info.get("start_year")
            if not year and len(cover_date) >= 4:
                year = cover_date[:4]

            matches.append(CVMatch(
                issue_id=r["id"],
                volume_id=volume.get("id", 0),
                series=volume.get("name", ""),
                issue_number=r.get("issue_number", ""),
                title=r.get("name"),
                cover_date=cover_date,
                publisher=vol_info.get("publisher"),
                start_year=year,
                issue_count=vol_info.get("issue_count"),
                description=r.get("description"),
                image_url=image.get("original_url"),
                cover_url=cover_url,
                cover_urls=cover_urls,
                match_type="api",
                match_score=0,
            ))

        return matches

    def get_issue_from_api(self, issue_id: int) -> Optional[CVMatch]:
        """Fetch full issue details from the ComicVine API, including credits."""
        data = self._api_request(f"issue/4000-{issue_id}", {
            "field_list": ",".join([
                "id", "volume", "name", "issue_number", "cover_date",
                "description", "image", "person_credits", "character_credits",
                "team_credits", "location_credits", "story_arc_credits",
                "site_detail_url",
            ]),
        })
        if not data:
            return None

        r = data["results"]
        volume = r.get("volume") or {}
        image = r.get("image") or {}
        volume_id = volume.get("id")

        # Fetch volume details for publisher, start_year, issue_count
        publisher = None
        start_year = None
        issue_count = None
        if volume_id:
            vol_data = self._api_request(f"volume/4050-{volume_id}", {
                "field_list": "id,name,start_year,count_of_issues,publisher",
            })
            if vol_data:
                vr = vol_data["results"]
                start_year = str(vr.get("start_year", "")) or None
                issue_count = vr.get("count_of_issues")
                pub = vr.get("publisher")
                if pub:
                    publisher = pub.get("name")

        # Parse credits (API returns lists directly, our parsers handle both)
        person_credits = _parse_credits_json(r.get("person_credits"))
        characters = _parse_entity_json(r.get("character_credits"))
        teams = _parse_entity_json(r.get("team_credits"))
        locations = _parse_entity_json(r.get("location_credits"))
        story_arcs = _parse_entity_json(r.get("story_arc_credits"))

        writers = person_credits.get("writer", [])
        artists = person_credits.get("artist", [])
        pencillers = person_credits.get("penciller", []) or artists
        inkers = person_credits.get("inker", []) or artists
        colorists = person_credits.get("colorist", [])
        letterers = person_credits.get("letterer", [])
        cover_artists = person_credits.get("cover", [])
        editors = person_credits.get("editor", [])

        cover_url = image.get("medium_url") or image.get("small_url")
        cover_urls = []
        if image.get("original_url"):
            cover_urls.append(image["original_url"])
        if cover_url and cover_url not in cover_urls:
            cover_urls.insert(0, cover_url)

        return CVMatch(
            issue_id=r["id"],
            volume_id=volume_id or 0,
            series=volume.get("name", ""),
            issue_number=r.get("issue_number", ""),
            title=r.get("name"),
            cover_date=r.get("cover_date"),
            publisher=publisher,
            start_year=start_year,
            issue_count=issue_count,
            description=r.get("description"),
            image_url=image.get("original_url"),
            cover_url=cover_url,
            cover_urls=cover_urls,
            match_type="api",
            match_score=0,
            characters=", ".join(characters) if characters else None,
            writer=", ".join(writers) if writers else None,
            penciller=", ".join(pencillers) if pencillers else None,
            inker=", ".join(inkers) if inkers else None,
            colorist=", ".join(colorists) if colorists else None,
            letterer=", ".join(letterers) if letterers else None,
            cover_artist=", ".join(cover_artists) if cover_artists else None,
            editor=", ".join(editors) if editors else None,
            web=r.get("site_detail_url"),
            teams=", ".join(teams) if teams else None,
            locations=", ".join(locations) if locations else None,
            story_arcs=", ".join(story_arcs) if story_arcs else None,
        )
