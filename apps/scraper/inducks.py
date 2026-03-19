"""
Inducks scraper.

Searches the local Inducks SQLite database (built from ISV files) for
Disney comic metadata: publications, issues, story credits, characters,
and cover images.
"""

import logging
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

# Inducks role codes to ComicInfo field mapping
# p=plotter, w=writer, a=artist/penciller, i=inker, c=colorist, l=letterer, r=cover artist
ROLE_MAP = {
    "w": "writer",
    "p": "writer",      # plotter merged with writer
    "a": "penciller",
    "i": "inker",
    "c": "colorist",
    "l": "letterer",
    "r": "cover_artist",
}


@dataclass
class InducksMatch:
    """Result of an Inducks match, structured like CVMatch for UI compatibility."""
    issuecode: str
    publicationcode: str
    series: str               # publication title
    issue_number: str
    title: Optional[str]      # issue or lead story title
    cover_date: Optional[str] # oldestdate
    publisher: Optional[str]
    start_year: Optional[str]
    issue_count: Optional[int] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    cover_url: Optional[str] = None
    cover_urls: Optional[list[str]] = None
    match_type: str = "inducks"
    match_score: int = 0

    # Credits
    characters: Optional[str] = None
    writer: Optional[str] = None
    penciller: Optional[str] = None
    inker: Optional[str] = None
    colorist: Optional[str] = None
    letterer: Optional[str] = None
    cover_artist: Optional[str] = None
    editor: Optional[str] = None

    # Additional metadata
    web: Optional[str] = None
    teams: Optional[str] = None
    locations: Optional[str] = None
    story_arcs: Optional[str] = None

    # Inducks-specific
    pages: Optional[str] = None
    country: Optional[str] = None
    language: Optional[str] = None
    stories: Optional[list[dict]] = None  # [{"code": "D 94066", "title": "..."}]


def _get_inducks_db_path():
    from apps.core.models import get_setting
    from django.conf import settings as django_settings
    return get_setting(
        "inducks_db_path",
        getattr(django_settings, "INDUCKS_DB_PATH", "/cv_db/inducks.db"),
    )


def is_inducks_available() -> bool:
    """Return True if inducks.db exists and SQLite can open it."""
    db_path = _get_inducks_db_path()
    if not os.path.exists(db_path):
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)
        conn.execute("SELECT 1 FROM inducks_issue LIMIT 1")
        conn.close()
        return True
    except Exception:
        return False


class InducksScraper:
    """Query the local Inducks SQLite database."""

    def __init__(self, db_path=None):
        self._db_path = db_path or _get_inducks_db_path()
        self._conn = None

    def _get_conn(self):
        if self._conn is None:
            self._conn = sqlite3.connect(
                f"file:{self._db_path}?immutable=1", uri=True
            )
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def search(self, query, country=None, limit=10):
        """
        Search for issues by publication title, story title, or entry title.

        Accepts queries like:
          "Anders And"              -> find publications matching that name
          "Anders And 42"           -> find publication + issue number
          "The Universal Solvent"   -> find by story title
        """
        conn = self._get_conn()
        query = query.strip()
        if not query:
            return []

        # Try to split query into series name + issue number
        parts = query.rsplit(None, 1)
        series_query = query
        issue_number = None

        if len(parts) == 2:
            candidate = parts[1]
            if candidate[0].isdigit():
                series_query = parts[0]
                issue_number = candidate

        like_param = f"%{series_query}%"
        like_full = f"%{query}%"

        # Search 1: by publication title (+ optional issue number)
        pub_params = [like_param]
        pub_where = ["pub.title LIKE ?"]
        if country:
            pub_where.append("pub.countrycode = ?")
            pub_params.append(country)
        if issue_number:
            pub_where.append("i.issuenumber LIKE ?")
            pub_params.append(f"%{issue_number}%")

        pub_sql = f"""
            SELECT DISTINCT
                i.issuecode, i.publicationcode, i.issuenumber,
                i.title AS issue_title, i.oldestdate, i.pages,
                pub.title AS publication_title,
                pub.countrycode, pub.languagecode
            FROM inducks_issue i
            JOIN inducks_publication pub ON pub.publicationcode = i.publicationcode
            WHERE {' AND '.join(pub_where)}
        """

        # Search 2: by story title or entry title
        story_params = [like_full, like_full]
        story_where = ["(s.title LIKE ? OR e.title LIKE ?)"]
        if country:
            story_where.append("pub.countrycode = ?")
            story_params.append(country)

        story_sql = f"""
            SELECT DISTINCT
                i.issuecode, i.publicationcode, i.issuenumber,
                i.title AS issue_title, i.oldestdate, i.pages,
                pub.title AS publication_title,
                pub.countrycode, pub.languagecode
            FROM inducks_entry e
            JOIN inducks_storyversion sv ON sv.storyversioncode = e.storyversioncode
            JOIN inducks_story s ON s.storycode = sv.storycode
            JOIN inducks_issue i ON i.issuecode = e.issuecode
            JOIN inducks_publication pub ON pub.publicationcode = i.publicationcode
            WHERE {' AND '.join(story_where)}
        """

        combined_sql = f"""
            SELECT * FROM (
                {pub_sql}
                UNION
                {story_sql}
            )
            ORDER BY oldestdate DESC
            LIMIT ?
        """

        rows = conn.execute(
            combined_sql, pub_params + story_params + [limit]
        ).fetchall()

        results = []
        for row in rows:
            year = None
            if row["oldestdate"] and row["oldestdate"][0].isdigit():
                try:
                    year = str(row["oldestdate"].split("-")[0])
                except (IndexError, ValueError):
                    pass

            cover_url = self._get_cover_url(conn, row["issuecode"])
            stories = self._get_stories(conn, row["issuecode"])

            match = InducksMatch(
                issuecode=row["issuecode"],
                publicationcode=row["publicationcode"],
                series=row["publication_title"] or row["publicationcode"],
                issue_number=row["issuenumber"],
                title=row["issue_title"] or None,
                cover_date=row["oldestdate"] or None,
                start_year=year,
                publisher=None,
                cover_url=cover_url,
                pages=row["pages"] or None,
                country=row["countrycode"],
                language=row["languagecode"],
                web=f"https://inducks.org/issue.php?c={quote(row['issuecode'], safe='')}",
                stories=stories,
            )
            results.append(match)

        return results

    def search_by_storycode(self, storycode, country=None, limit=10):
        """Search for issues containing a specific story code."""
        conn = self._get_conn()
        storycode = storycode.strip().replace(" ", "")
        if not storycode:
            return []

        # Normalize spaces in both the search term and DB values so "D92380" matches "D 92380"
        params = [f"%{storycode}%"]
        where = ["REPLACE(s.storycode, ' ', '') LIKE ?"]

        if country:
            where.append("pub.countrycode = ?")
            params.append(country)

        sql = f"""
            SELECT DISTINCT
                i.issuecode, i.publicationcode, i.issuenumber,
                i.title AS issue_title, i.oldestdate, i.pages,
                pub.title AS publication_title,
                pub.countrycode, pub.languagecode
            FROM inducks_entry e
            JOIN inducks_storyversion sv ON sv.storyversioncode = e.storyversioncode
            JOIN inducks_story s ON s.storycode = sv.storycode
            JOIN inducks_issue i ON i.issuecode = e.issuecode
            JOIN inducks_publication pub ON pub.publicationcode = i.publicationcode
            WHERE {' AND '.join(where)}
            ORDER BY i.oldestdate DESC
            LIMIT ?
        """

        rows = conn.execute(sql, params + [limit]).fetchall()

        results = []
        for row in rows:
            year = None
            if row["oldestdate"] and row["oldestdate"][0].isdigit():
                try:
                    year = str(row["oldestdate"].split("-")[0])
                except (IndexError, ValueError):
                    pass

            cover_url = self._get_cover_url(conn, row["issuecode"])
            stories = self._get_stories(conn, row["issuecode"])

            match = InducksMatch(
                issuecode=row["issuecode"],
                publicationcode=row["publicationcode"],
                series=row["publication_title"] or row["publicationcode"],
                issue_number=row["issuenumber"],
                title=row["issue_title"] or None,
                cover_date=row["oldestdate"] or None,
                start_year=year,
                publisher=None,
                cover_url=cover_url,
                pages=row["pages"] or None,
                country=row["countrycode"],
                language=row["languagecode"],
                web=f"https://inducks.org/issue.php?c={quote(row['issuecode'], safe='')}",
                stories=stories,
            )
            results.append(match)

        return results

    def get_issue_details(self, issuecode):
        """
        Get full metadata for a specific issue code.

        Returns an InducksMatch with credits, characters, publisher, cover URL,
        and a story summary.
        """
        conn = self._get_conn()

        # Basic issue info
        issue = conn.execute("""
            SELECT
                i.issuecode, i.publicationcode, i.issuenumber,
                i.title AS issue_title, i.oldestdate, i.pages,
                pub.title AS publication_title,
                pub.countrycode, pub.languagecode
            FROM inducks_issue i
            JOIN inducks_publication pub ON pub.publicationcode = i.publicationcode
            WHERE i.issuecode = ?
        """, [issuecode]).fetchone()

        if not issue:
            return None

        # Parse date
        year = month = day = None
        if issue["oldestdate"] and issue["oldestdate"][0].isdigit():
            date_parts = issue["oldestdate"].split("-")
            try:
                year = date_parts[0]
                if len(date_parts) > 1 and date_parts[1].isdigit():
                    month = date_parts[1]
                if len(date_parts) > 2 and date_parts[2].isdigit():
                    day = date_parts[2]
            except (IndexError, ValueError):
                pass

        # Cover date in CV format (YYYY-MM-DD)
        cover_date = issue["oldestdate"] if issue["oldestdate"] else None

        # Publisher
        publishers = conn.execute("""
            SELECT DISTINCT pub.publishername
            FROM inducks_publishingjob pj
            JOIN inducks_publisher pub ON pub.publisherid = pj.publisherid
            WHERE pj.issuecode = ?
        """, [issuecode]).fetchall()
        publisher = ", ".join(p["publishername"] for p in publishers) if publishers else None

        # Get all entries (stories) for this issue
        entries = conn.execute("""
            SELECT e.entrycode, e.storyversioncode, e.title AS entry_title,
                   e.position, sv.storycode, sv.kind, s.title AS story_title
            FROM inducks_entry e
            JOIN inducks_storyversion sv ON sv.storyversioncode = e.storyversioncode
            JOIN inducks_story s ON s.storycode = sv.storycode
            WHERE e.issuecode = ?
            ORDER BY e.position
        """, [issuecode]).fetchall()

        # Build title from first story entry (skip covers)
        title = issue["issue_title"]
        if not title:
            for entry in entries:
                if entry["kind"] == "n":  # story (not cover/article)
                    title = entry["entry_title"] or entry["story_title"]
                    break
            if not title and entries:
                title = entries[0]["entry_title"] or entries[0]["story_title"]

        # Collect all storyversion codes for credit/character lookups
        sv_codes = list({e["storyversioncode"] for e in entries if e["storyversioncode"]})

        # Credits
        credits = {}
        if sv_codes:
            placeholders = ",".join(["?"] * len(sv_codes))
            credit_rows = conn.execute(f"""
                SELECT DISTINCT sj.plotwritartink AS role, p.fullname
                FROM inducks_storyjob sj
                JOIN inducks_person p ON p.personcode = sj.personcode
                WHERE sj.storyversioncode IN ({placeholders})
                  AND p.fullname != '?'
                  AND p.fullname != '(no one)'
            """, sv_codes).fetchall()

            for row in credit_rows:
                field_name = ROLE_MAP.get(row["role"])
                if field_name:
                    credits.setdefault(field_name, set()).add(row["fullname"])

        # Characters
        characters = []
        if sv_codes:
            placeholders = ",".join(["?"] * len(sv_codes))
            char_rows = conn.execute(f"""
                SELECT DISTINCT ch.charactername
                FROM inducks_appearance ap
                JOIN inducks_character ch ON ch.charactercode = ap.charactercode
                WHERE ap.storyversioncode IN ({placeholders})
                  AND ch.charactername != '--'
                ORDER BY ch.charactername
            """, sv_codes).fetchall()
            characters = [c["charactername"] for c in char_rows]

        # Build story summary
        summary_lines = []
        for entry in entries:
            if entry["kind"] not in ("n", "c"):
                continue
            kind_label = "Story" if entry["kind"] == "n" else "Cover"
            entry_title = entry["entry_title"] or entry["story_title"] or "(untitled)"
            summary_lines.append(f"[{kind_label}] {entry_title} ({entry['storycode']})")
        description = "\n".join(summary_lines) if summary_lines else None

        # Cover URL
        cover_url = self._get_cover_url(conn, issuecode)

        match = InducksMatch(
            issuecode=issuecode,
            publicationcode=issue["publicationcode"],
            series=issue["publication_title"] or issue["publicationcode"],
            issue_number=issue["issuenumber"],
            title=title,
            cover_date=cover_date,
            publisher=publisher,
            start_year=year,
            description=description,
            cover_url=cover_url,
            web=f"https://inducks.org/issue.php?c={quote(issuecode, safe='')}",
            pages=issue["pages"] or None,
            country=issue["countrycode"],
            language=issue["languagecode"],
            characters=", ".join(characters) if characters else None,
            writer=", ".join(sorted(credits.get("writer", []))) or None,
            penciller=", ".join(sorted(credits.get("penciller", []))) or None,
            inker=", ".join(sorted(credits.get("inker", []))) or None,
            colorist=", ".join(sorted(credits.get("colorist", []))) or None,
            letterer=", ".join(sorted(credits.get("letterer", []))) or None,
            cover_artist=", ".join(sorted(credits.get("cover_artist", []))) or None,
        )

        return match

    def get_story_only(self, storycode):
        """
        Get metadata for a story without tying it to any specific issue.

        Returns credits, characters, and title from the story's original
        version. No series/issue/publication info is set.
        """
        conn = self._get_conn()

        story = conn.execute("""
            SELECT s.storycode, s.title, s.firstpublicationdate,
                   s.originalstoryversioncode, s.storyparts
            FROM inducks_story s
            WHERE s.storycode = ?
        """, [storycode]).fetchone()

        if not story:
            return None

        title = story["title"] or None

        # Parse first publication date for year
        year = None
        cover_date = story["firstpublicationdate"] or None
        if cover_date and cover_date[0].isdigit():
            try:
                year = cover_date.split("-")[0]
            except (IndexError, ValueError):
                pass

        # Get all storyversion codes for this story (for credits/characters)
        sv_rows = conn.execute("""
            SELECT storyversioncode
            FROM inducks_storyversion
            WHERE storycode = ?
        """, [storycode]).fetchall()
        sv_codes = [r["storyversioncode"] for r in sv_rows]

        # Prefer original version for credits, fall back to all versions
        original_sv = story["originalstoryversioncode"]
        credit_sv = [original_sv] if original_sv else sv_codes

        credits = {}
        if credit_sv:
            placeholders = ",".join(["?"] * len(credit_sv))
            credit_rows = conn.execute(f"""
                SELECT DISTINCT sj.plotwritartink AS role, p.fullname
                FROM inducks_storyjob sj
                JOIN inducks_person p ON p.personcode = sj.personcode
                WHERE sj.storyversioncode IN ({placeholders})
                  AND p.fullname != '?'
                  AND p.fullname != '(no one)'
            """, credit_sv).fetchall()

            for row in credit_rows:
                field_name = ROLE_MAP.get(row["role"])
                if field_name:
                    credits.setdefault(field_name, set()).add(row["fullname"])

        # Characters from original version
        characters = []
        if credit_sv:
            placeholders = ",".join(["?"] * len(credit_sv))
            char_rows = conn.execute(f"""
                SELECT DISTINCT ch.charactername
                FROM inducks_appearance ap
                JOIN inducks_character ch ON ch.charactercode = ap.charactercode
                WHERE ap.storyversioncode IN ({placeholders})
                  AND ch.charactername != '--'
                ORDER BY ch.charactername
            """, credit_sv).fetchall()
            characters = [c["charactername"] for c in char_rows]

        pages_str = f"{story['storyparts']} parts" if story["storyparts"] and story["storyparts"] > 1 else None

        match = InducksMatch(
            issuecode="",
            publicationcode="",
            series="",
            issue_number="",
            title=title,
            cover_date=cover_date,
            publisher=None,
            start_year=year,
            description=f"[Story] {title or '(untitled)'} ({storycode})",
            web=f"https://inducks.org/story.php?c={quote(storycode, safe='')}",
            pages=pages_str,
            country=None,
            language=None,
            characters=", ".join(characters) if characters else None,
            writer=", ".join(sorted(credits.get("writer", []))) or None,
            penciller=", ".join(sorted(credits.get("penciller", []))) or None,
            inker=", ".join(sorted(credits.get("inker", []))) or None,
            colorist=", ".join(sorted(credits.get("colorist", []))) or None,
            letterer=", ".join(sorted(credits.get("letterer", []))) or None,
            cover_artist=", ".join(sorted(credits.get("cover_artist", []))) or None,
            stories=[{"code": storycode, "title": title or ""}],
        )

        return match

    def get_story_details(self, issuecode, storycode):
        """
        Get metadata for a specific story within an issue.

        Like get_issue_details but scoped to a single story: title, credits,
        and characters come only from the target storycode.
        """
        conn = self._get_conn()

        # Basic issue info (still need the issue for series/number/date/publisher)
        issue = conn.execute("""
            SELECT
                i.issuecode, i.publicationcode, i.issuenumber,
                i.title AS issue_title, i.oldestdate, i.pages,
                pub.title AS publication_title,
                pub.countrycode, pub.languagecode
            FROM inducks_issue i
            JOIN inducks_publication pub ON pub.publicationcode = i.publicationcode
            WHERE i.issuecode = ?
        """, [issuecode]).fetchone()

        if not issue:
            return None

        # Parse date
        year = None
        cover_date = issue["oldestdate"] if issue["oldestdate"] else None
        if issue["oldestdate"] and issue["oldestdate"][0].isdigit():
            try:
                year = issue["oldestdate"].split("-")[0]
            except (IndexError, ValueError):
                pass

        # Publisher
        publishers = conn.execute("""
            SELECT DISTINCT pub.publishername
            FROM inducks_publishingjob pj
            JOIN inducks_publisher pub ON pub.publisherid = pj.publisherid
            WHERE pj.issuecode = ?
        """, [issuecode]).fetchall()
        publisher = ", ".join(p["publishername"] for p in publishers) if publishers else None

        # Get entries for the target story only
        entries = conn.execute("""
            SELECT e.entrycode, e.storyversioncode, e.title AS entry_title,
                   e.position, sv.storycode, sv.kind, s.title AS story_title
            FROM inducks_entry e
            JOIN inducks_storyversion sv ON sv.storyversioncode = e.storyversioncode
            JOIN inducks_story s ON s.storycode = sv.storycode
            WHERE e.issuecode = ?
              AND s.storycode = ?
            ORDER BY e.position
        """, [issuecode, storycode]).fetchall()

        if not entries:
            return None

        # Title from the matched story
        title = entries[0]["entry_title"] or entries[0]["story_title"] or None

        # Credits scoped to this story's storyversioncodes
        sv_codes = list({e["storyversioncode"] for e in entries if e["storyversioncode"]})
        credits = {}
        if sv_codes:
            placeholders = ",".join(["?"] * len(sv_codes))
            credit_rows = conn.execute(f"""
                SELECT DISTINCT sj.plotwritartink AS role, p.fullname
                FROM inducks_storyjob sj
                JOIN inducks_person p ON p.personcode = sj.personcode
                WHERE sj.storyversioncode IN ({placeholders})
                  AND p.fullname != '?'
                  AND p.fullname != '(no one)'
            """, sv_codes).fetchall()

            for row in credit_rows:
                field_name = ROLE_MAP.get(row["role"])
                if field_name:
                    credits.setdefault(field_name, set()).add(row["fullname"])

        # Characters scoped to this story
        characters = []
        if sv_codes:
            placeholders = ",".join(["?"] * len(sv_codes))
            char_rows = conn.execute(f"""
                SELECT DISTINCT ch.charactername
                FROM inducks_appearance ap
                JOIN inducks_character ch ON ch.charactercode = ap.charactercode
                WHERE ap.storyversioncode IN ({placeholders})
                  AND ch.charactername != '--'
                ORDER BY ch.charactername
            """, sv_codes).fetchall()
            characters = [c["charactername"] for c in char_rows]

        description = f"[Story] {title or '(untitled)'} ({storycode})"

        match = InducksMatch(
            issuecode=issuecode,
            publicationcode=issue["publicationcode"],
            series=issue["publication_title"] or issue["publicationcode"],
            issue_number=issue["issuenumber"],
            title=title,
            cover_date=cover_date,
            publisher=publisher,
            start_year=year,
            description=description,
            web=f"https://inducks.org/story.php?c={quote(storycode, safe='')}",
            pages=issue["pages"] or None,
            country=issue["countrycode"],
            language=issue["languagecode"],
            characters=", ".join(characters) if characters else None,
            writer=", ".join(sorted(credits.get("writer", []))) or None,
            penciller=", ".join(sorted(credits.get("penciller", []))) or None,
            inker=", ".join(sorted(credits.get("inker", []))) or None,
            colorist=", ".join(sorted(credits.get("colorist", []))) or None,
            letterer=", ".join(sorted(credits.get("letterer", []))) or None,
            cover_artist=", ".join(sorted(credits.get("cover_artist", []))) or None,
            stories=[{"code": storycode, "title": title or ""}],
        )

        return match

    def _get_stories(self, conn, issuecode):
        """Get story codes and titles for an issue (actual stories only)."""
        rows = conn.execute("""
            SELECT DISTINCT s.storycode, s.title AS story_title, e.title AS entry_title
            FROM inducks_entry e
            JOIN inducks_storyversion sv ON sv.storyversioncode = e.storyversioncode
            JOIN inducks_story s ON s.storycode = sv.storycode
            WHERE e.issuecode = ?
              AND s.storycode != ''
              AND sv.kind IN ('n', 'g')
            ORDER BY e.position
        """, [issuecode]).fetchall()
        return [
            {"code": r["storycode"], "title": r["entry_title"] or r["story_title"] or ""}
            for r in rows
        ]

    def _get_cover_url(self, conn, issuecode):
        """Build the inducks.org cover viewer URL for an issue."""
        cover = conn.execute("""
            SELECT s.urlbase || eu.url AS cover_url
            FROM inducks_entry e
            JOIN inducks_entryurl eu ON eu.entrycode = e.entrycode
            JOIN inducks_site s ON s.sitecode = eu.sitecode
            WHERE e.issuecode = ?
              AND e.position = 'a'
              AND eu.pagenumber = 1
              AND s.images = 'Y'
              AND s.sitecode NOT LIKE 'thumbnails%'
            LIMIT 1
        """, [issuecode]).fetchone()

        if cover:
            raw_url = cover["cover_url"]
            return f"https://inducks.org/hr.php?image={quote(raw_url, safe='')}"
        return None
