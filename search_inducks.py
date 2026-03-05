#!/usr/bin/env python3
"""
Search the local Inducks database for stories by title, language, and author.
Returns matching issues with credits, characters, and cover URLs.

Usage:
    python3 search_inducks.py --title "Son of the Sun" --language dk --author "Don Rosa"
    python3 search_inducks.py --title "Solens søn" --language dk
    python3 search_inducks.py --title "Son of the Sun" --author "Rosa"
"""

import argparse
import sqlite3
import sys
from urllib.parse import quote

DB_FILE = "./data/inducks.db"


def get_conn():
    conn = sqlite3.connect(f"file:{DB_FILE}?immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def search(title, language=None, author=None):
    conn = get_conn()

    # Build the story search query
    # Search both original story titles and localized entry titles
    conditions = []
    params = []

    story_title_match = "s.title LIKE ?"
    entry_title_match = "e.title LIKE ?"
    title_param = f"%{title}%"

    # Base query: find issues via entry -> storyversion -> story, with optional filters
    query = """
        SELECT DISTINCT
            i.issuecode,
            i.publicationcode,
            i.issuenumber,
            i.oldestdate,
            i.pages,
            pub.title AS publication,
            pub.countrycode,
            pub.languagecode,
            s.storycode,
            s.title AS story_title,
            e.title AS entry_title,
            e.position,
            sv.kind
        FROM inducks_entry e
        JOIN inducks_storyversion sv ON sv.storyversioncode = e.storyversioncode
        JOIN inducks_story s ON s.storycode = sv.storycode
        JOIN inducks_issue i ON i.issuecode = e.issuecode
        JOIN inducks_publication pub ON pub.publicationcode = i.publicationcode
    """

    where = []
    where.append(f"({story_title_match} OR {entry_title_match})")
    params.extend([title_param, title_param])

    if language:
        where.append("pub.countrycode = ?")
        params.append(language)

    if author:
        query += """
        JOIN inducks_storyjob sj ON sj.storyversioncode = sv.storyversioncode
        JOIN inducks_person p ON p.personcode = sj.personcode
        """
        where.append("p.fullname LIKE ?")
        params.append(f"%{author}%")

    query += " WHERE " + " AND ".join(where)
    query += " ORDER BY i.oldestdate, e.position"

    results = conn.execute(query, params).fetchall()

    if not results:
        print("No results found.")
        conn.close()
        return

    # Group by issuecode
    issues = {}
    for row in results:
        key = row["issuecode"]
        if key not in issues:
            issues[key] = {
                "issuecode": row["issuecode"],
                "publicationcode": row["publicationcode"],
                "issuenumber": row["issuenumber"],
                "date": row["oldestdate"],
                "pages": row["pages"],
                "publication": row["publication"],
                "country": row["countrycode"],
                "language": row["languagecode"],
                "stories": [],
            }
        issues[key]["stories"].append({
            "storycode": row["storycode"],
            "story_title": row["story_title"],
            "entry_title": row["entry_title"],
            "position": row["position"],
            "kind": row["kind"],
        })

    # Fetch credits and characters and covers for each issue
    # Only for the matched stories, not the entire issue
    role_map = {"w": "Writer", "p": "Plotter", "a": "Artist", "i": "Inker",
                "c": "Colorist", "l": "Letterer", "r": "Cover Artist"}

    for issue in issues.values():
        issuecode = issue["issuecode"]
        storycodes = list({s["storycode"] for s in issue["stories"]})
        placeholders_sc = ",".join(["?"] * len(storycodes))

        # Credits for matched stories only
        credits = conn.execute(f"""
            SELECT DISTINCT sj.plotwritartink AS role, p.fullname
            FROM inducks_storyversion sv
            JOIN inducks_storyjob sj ON sj.storyversioncode = sv.storyversioncode
            JOIN inducks_person p ON p.personcode = sj.personcode
            WHERE sv.storycode IN ({placeholders_sc})
              AND p.fullname != '?'
            ORDER BY sj.plotwritartink, p.fullname
        """, storycodes).fetchall()

        credit_groups = {}
        for c in credits:
            role = role_map.get(c["role"], c["role"])
            credit_groups.setdefault(role, set()).add(c["fullname"])
        issue["credits"] = {r: sorted(names) for r, names in credit_groups.items()}

        # Characters for matched stories only
        characters = conn.execute(f"""
            SELECT DISTINCT ch.charactername
            FROM inducks_storyversion sv
            JOIN inducks_appearance ap ON ap.storyversioncode = sv.storyversioncode
            JOIN inducks_character ch ON ch.charactercode = ap.charactercode
            WHERE sv.storycode IN ({placeholders_sc})
              AND ch.charactername != '--'
            ORDER BY ch.charactername
        """, storycodes).fetchall()
        issue["characters"] = [c["charactername"] for c in characters]

        # Cover URL (full resolution, first page of cover entry)
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
            issue["cover_url"] = f"https://inducks.org/hr.php?image={quote(raw_url, safe='')}"
        else:
            issue["cover_url"] = None

        # Publishers
        publishers = conn.execute("""
            SELECT DISTINCT pub.publishername
            FROM inducks_publishingjob pj
            JOIN inducks_publisher pub ON pub.publisherid = pj.publisherid
            WHERE pj.issuecode = ?
        """, [issuecode]).fetchall()
        issue["publishers"] = [p["publishername"] for p in publishers]

    conn.close()

    # Print results
    for issue in issues.values():
        print(f"{'=' * 80}")
        print(f"  {issue['publication']} #{issue['issuenumber']}")
        print(f"  Code: {issue['issuecode']}  |  Date: {issue['date']}  |  Pages: {issue['pages'] or '?'}")
        if issue["publishers"]:
            print(f"  Publisher: {', '.join(issue['publishers'])}")
        if issue["cover_url"]:
            print(f"  Cover: {issue['cover_url']}")
        print(f"  Inducks: https://inducks.org/issue.php?c={issue['issuecode']}")

        print()
        for story in issue["stories"]:
            kind_label = {"n": "Story", "c": "Cover", "a": "Article"}.get(story["kind"], story["kind"])
            title_display = story["entry_title"] or story["story_title"] or "(untitled)"
            print(f"    [{kind_label}] {title_display}  ({story['storycode']})")

        if issue["credits"]:
            print()
            for role, names in issue["credits"].items():
                print(f"    {role}: {', '.join(names)}")

        if issue["characters"]:
            print(f"\n    Characters: {', '.join(issue['characters'])}")
        print()

    print(f"{'=' * 80}")
    print(f"Found {len(issues)} issue(s)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search the local Inducks database")
    parser.add_argument("--title", "-t", required=True, help="Story title (partial match)")
    parser.add_argument("--language", "-l", help="Country code (e.g. dk, us, de, nl, fi)")
    parser.add_argument("--author", "-a", help="Author name (partial match)")
    args = parser.parse_args()

    search(args.title, args.language, args.author)
