"""
Scraper service layer.

Contains the canonical matching and apply logic shared between:
- apps/core/tasks.py (batch scraping)
- apps/core/views.py (single-comic scrape modal)
- apps/scraper/views.py (dry-run preview)
"""

import re

from apps.scraper.hasher import extract_cover_hashes


def normalize_issue_number(num):
    """Normalize issue number for comparison."""
    if not num:
        return ""
    return str(num).lstrip("0").lower() or "0"


def series_matches(proposed, matched):
    """Check if two series names are similar enough to be the same series."""
    def normalize(s):
        s = s.lower()
        s = re.sub(r"[^\w\s]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    proposed_norm = normalize(proposed)
    matched_norm = normalize(matched)

    if proposed_norm == matched_norm:
        return True
    if proposed_norm in matched_norm or matched_norm in proposed_norm:
        return True

    proposed_words = proposed_norm.split()
    matched_words = matched_norm.split()
    if proposed_words and matched_words and proposed_words[0] == matched_words[0]:
        return True

    return False


def metadata_alignment_score(comic, match):
    """
    Score how well a CV match aligns with the comic's parsed metadata.

    Uses series/number/year with fallback to proposed_* fields so this
    works for both STATE_IMPORTED comics (may have ComicInfo data) and
    fresh imports (only proposed_* populated).

    Returns 0 if the match is disqualified, >0 for viable matches
    (higher is better: 1=number only, 2=number+series, 3=number+series+year).
    """
    cv_series = comic.series or comic.proposed_series
    cv_number = comic.number or comic.proposed_number
    cv_year = comic.year or comic.proposed_year

    if not cv_series and not cv_number:
        return 1  # No metadata to validate against - tentative

    score = 0

    proposed_num = normalize_issue_number(cv_number)
    match_num = normalize_issue_number(match.issue_number)

    if proposed_num and match_num:
        if proposed_num != match_num:
            return 0
        score = 1

    if cv_series and match.series:
        if series_matches(cv_series, match.series):
            score = 2
            if cv_year and match.start_year:
                try:
                    if abs(int(cv_year) - int(match.start_year)) <= 2:
                        score = 3
                except (ValueError, TypeError):
                    pass
    elif not cv_series and score == 0:
        score = 1

    return score


def try_hash_match(comic, scraper, max_distance=10):
    """
    Try to match a comic by cover image hash with metadata cross-validation.

    Returns the best CVMatch or None.
    """
    if not comic.file_path:
        return None

    hashes = extract_cover_hashes(comic.file_path)
    if not hashes:
        return None

    # Store hashes on comic for future deduplication use
    comic.phash = hashes.phash_hex
    comic.ahash = hashes.ahash_hex

    matches = scraper.match_by_hash_fast(
        hashes.phash,
        hashes.ahash,
        max_distance=max_distance,
        limit=10,
    )

    if not matches:
        return None

    # Cross-validate against parsed metadata
    validated = []
    for match in matches:
        score = metadata_alignment_score(comic, match)
        if score > 0:
            validated.append((match, score))

    if validated:
        validated.sort(key=lambda x: (-x[1], x[0].match_score))
        best = validated[0][0]
        best.match_type = f"{best.match_type}+meta"
        return best

    return None


def try_metadata_match(comic, scraper):
    """
    Try to match a comic by series name and issue number.

    Uses series/proposed_series and number/proposed_number with precedence
    given to the verified (non-proposed) fields.

    Returns the best CVMatch or None.
    """
    cv_series = comic.series or comic.proposed_series
    cv_number = comic.number or comic.proposed_number
    cv_year = comic.year or comic.proposed_year

    if not cv_series or not cv_number:
        return None

    matches = scraper.match_by_metadata(
        series=cv_series,
        issue_number=cv_number,
        year=cv_year,
    )

    return matches[0] if matches else None


def find_best_match(comic, scraper, max_distance=10):
    """
    Find the best ComicVine match for a comic, automatically choosing the
    right strategy based on available data sources.

    Strategy (in order):
    1. Local DB available: hash match -> metadata match
    2. Local DB unavailable: API metadata match

    Returns the best CVMatch or None. Callers should not need to know which
    strategy was used — the match_type field on the result reflects it.
    """
    from apps.scraper.cv_sources import is_cv_db_available

    if is_cv_db_available():
        match = try_hash_match(comic, scraper, max_distance=max_distance)
        if not match:
            match = try_metadata_match(comic, scraper)
        return match

    return try_api_metadata_match(comic, scraper)


def try_api_metadata_match(comic, scraper):
    """
    Match a comic using the ComicVine API search endpoint.

    Used when the local comicvine.db is unavailable (API-only mode).
    Checks the rolling API budget before making any calls and returns None
    immediately if the budget is exhausted.

    Typical API calls per comic:
    - search_api(query, limit=5): 1 call + up to 5 volume-info calls
    - get_issue_from_api(issue_id): 1 call + 1 volume call for credits

    Returns the best CVMatch (with full credits) or None.
    """
    from apps.scraper.cv_sources import check_api_budget

    cv_series = comic.series or comic.proposed_series
    cv_number = comic.number or comic.proposed_number

    if not cv_series or not cv_number:
        return None

    if not check_api_budget(required=3):
        import logging
        logging.getLogger(__name__).warning(
            "CV API budget exhausted — skipping comic %s", comic.pk
        )
        return None

    query = f"{cv_series} #{cv_number}"
    candidates = scraper.search_api(query, limit=5)

    if not candidates:
        return None

    # Score each candidate and take the best
    scored = []
    for match in candidates:
        score = metadata_alignment_score(comic, match)
        if score > 0:
            scored.append((match, score))

    if not scored:
        return None

    scored.sort(key=lambda x: -x[1])
    best = scored[0][0]

    # Fetch full credits for the chosen match
    if not check_api_budget(required=2):
        # Budget too low for the detail call — return shallow match
        best.match_type = f"api+search"
        return best

    detailed = scraper.get_issue_from_api(best.issue_id)
    if detailed:
        detailed.match_type = "api+detail"
        return detailed

    best.match_type = "api+search"
    return best


def apply_cv_match(comic, match, scraper=None):
    """
    Apply ComicVine match data to a comic and advance its workflow state.

    Enriches the match with credits if needed, writes all metadata fields,
    inserts variant covers into the CBZ, updates the state to STATE_COUNTED,
    and propagates the issue count to other comics in the same volume.
    """
    from apps.core.models import Comic
    from apps.core.utils import html_to_text
    from apps.core.cbz_utils import insert_variant_covers

    # Enrich with credits if not already present
    if scraper and not match.characters and not match.writer:
        scraper.enrich_match_with_credits(match)

    comic.series = match.series
    comic.number = match.issue_number
    comic.title = match.title
    comic.publisher = match.publisher
    comic.count = match.issue_count
    if match.issue_count:
        comic.remove_flag("missing_count")
    else:
        comic.add_flag("missing_count")

    if match.start_year:
        try:
            comic.volume = int(match.start_year)
        except ValueError:
            pass

    if match.cover_date:
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

    if not comic.notes and match.issue_id:
        comic.notes = f"Scraped metadata from ComicVine [CVDB{match.issue_id}]."

    if match.characters:
        comic.characters = match.characters
    if match.writer:
        comic.writer = match.writer
    if match.penciller:
        comic.penciller = match.penciller
    if match.inker:
        comic.inker = match.inker
    if match.colorist:
        comic.colorist = match.colorist
    if match.letterer:
        comic.letterer = match.letterer
    if match.cover_artist:
        comic.cover_artist = match.cover_artist
    if match.editor:
        comic.editor = match.editor

    if match.web:
        comic.web = match.web

    if match.teams:
        comic.teams = match.teams
    if match.locations:
        comic.locations = match.locations

    comic.custom_values["comicvine_issue"] = str(match.issue_id)
    comic.custom_values["comicvine_volume"] = str(match.volume_id)
    if match.issue_count:
        comic.custom_values["comicvine_issue_count"] = str(match.issue_count)
    comic.custom_values["scrape_source"] = match.match_type
    comic.custom_values["scrape_score"] = str(match.match_score)

    # Insert variant covers into the CBZ if available
    if (comic.is_digital and comic.file_path and comic.file_path.lower().endswith(".cbz")
            and match.cover_urls and comic.custom_values.get("HasAltCovers") != "Yes"):
        variants = []
        seen_urls = set()
        for url in match.cover_urls:
            if url and url not in seen_urls:
                variants.append(url)
                seen_urls.add(url)
        if variants:
            inserted = insert_variant_covers(comic.file_path, variants)
            if inserted > 0:
                comic.custom_values["HasAltCovers"] = "Yes"
                comic.custom_values["AltCoverCount"] = inserted
                if comic.page_count:
                    comic.page_count += inserted
                from apps.core.cover_cache import invalidate_comic_pages
                invalidate_comic_pages(comic.pk)

    comic.remove_flag("scrape_no_match")
    comic.remove_flag("scrape_error")
    comic.remove_flag("scrape_error_detail")
    comic.remove_flag("metadata_mismatch")

    # Flag comics from publishers not covered by any tagging ruleset
    if comic.publisher:
        from apps.tagging.engine import is_publisher_known
        if is_publisher_known(comic.publisher):
            comic.remove_flag("unknown_publisher")
        else:
            comic.add_flag("unknown_publisher")

    comic.state = Comic.STATE_COUNTED
    comic.save()

    if match.issue_count and match.volume_id:
        _update_volume_issue_count(str(match.volume_id), match.issue_count, exclude_pk=comic.pk)


def apply_inducks_match(comic, match):
    """
    Apply Inducks match data to a comic and advance its workflow state.

    Similar to apply_cv_match but uses Inducks-specific fields and does not
    insert variant covers or propagate issue counts.
    """
    from apps.core.models import Comic

    story_only = not match.issuecode

    # Issue-level fields: only set when matching a full issue or issue+story
    if not story_only:
        comic.series = match.series
        comic.number = match.issue_number
        if match.publisher:
            comic.publisher = match.publisher

    if match.title:
        comic.title = match.title

    # Inducks doesn't track issue counts; remove the flag so it doesn't
    # show up in the CV-specific count review queue
    comic.remove_flag("missing_count")

    if match.start_year:
        try:
            comic.volume = int(match.start_year)
        except ValueError:
            pass

    if match.cover_date and match.cover_date[0].isdigit():
        try:
            parts = match.cover_date.split("-")
            comic.year = int(parts[0])
            if len(parts) > 1 and parts[1].isdigit():
                comic.month = int(parts[1])
            if len(parts) > 2 and parts[2].isdigit():
                comic.day = int(parts[2])
        except (ValueError, IndexError):
            pass

    if match.description:
        comic.summary = match.description

    # Build notes
    storycode = match.stories[0]["code"] if match.stories and len(match.stories) == 1 else None
    if story_only and storycode:
        comic.notes = f"Scraped metadata from I.N.D.U.C.K.S. story {storycode}"
    elif storycode:
        comic.notes = f"Scraped metadata from I.N.D.U.C.K.S. [{match.issuecode}] story {storycode}"
    else:
        comic.notes = f"Scraped metadata from I.N.D.U.C.K.S. [{match.issuecode}]"

    if match.characters:
        comic.characters = match.characters
    if match.writer:
        comic.writer = match.writer
    if match.penciller:
        comic.penciller = match.penciller
    if match.inker:
        comic.inker = match.inker
    if match.colorist:
        comic.colorist = match.colorist
    if match.letterer:
        comic.letterer = match.letterer
    if match.cover_artist:
        comic.cover_artist = match.cover_artist

    if match.web:
        comic.web = match.web

    comic.custom_values["scrape_source"] = "inducks"
    if match.issuecode:
        comic.custom_values["inducks_issuecode"] = match.issuecode
        comic.custom_values["inducks_publicationcode"] = match.publicationcode
    if storycode:
        comic.custom_values["inducks_storycode"] = storycode

    comic.remove_flag("scrape_no_match")
    comic.remove_flag("scrape_error")
    comic.remove_flag("scrape_error_detail")
    comic.remove_flag("metadata_mismatch")

    # Flag comics from publishers not covered by any tagging ruleset
    if comic.publisher:
        from apps.tagging.engine import is_publisher_known
        if is_publisher_known(comic.publisher):
            comic.remove_flag("unknown_publisher")
        else:
            comic.add_flag("unknown_publisher")

    comic.state = Comic.STATE_COUNTED
    comic.save()


def _update_volume_issue_count(volume_id: str, new_count: int, exclude_pk=None):
    """
    Propagate an updated issue count to all other comics in the same CV volume.

    Comics with count-based formats (One-Shot, Limited Series, Main Series) are
    flagged for reformatting if the new count would change their format category.
    """
    from apps.core.models import Comic, get_setting

    one_shot_max = get_setting("one_shot_max_count", 1)
    limited_max = get_setting("limited_series_max_count", 15)

    def _get_count_format(count):
        if count <= one_shot_max:
            return "One-Shot"
        elif count <= limited_max:
            return "Limited Series"
        return "Main Series"

    comics_in_volume = Comic.objects.filter(custom_values__comicvine_volume=volume_id)
    if exclude_pk:
        comics_in_volume = comics_in_volume.exclude(pk=exclude_pk)

    for comic in comics_in_volume:
        if comic.count != new_count:
            comic.count = new_count
            comic.custom_values["comicvine_issue_count"] = str(new_count)
            comic.flags["count_updated"] = True
            if comic.format in Comic.COUNT_BASED_FORMATS and not getattr(comic, "format_ok", False):
                if comic.format != _get_count_format(new_count):
                    comic.needs_reformat = True
            comic.save()
