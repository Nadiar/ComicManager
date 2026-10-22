"""
Scraper service layer.

Contains the canonical matching and apply logic shared between:
- apps/core/tasks.py (batch scraping)
- apps/core/views.py (single-comic scrape modal)
- apps/scraper/views.py (dry-run preview)
"""

import re
import time

from apps.scraper.hasher import extract_cover_hashes

# 30s TTL cache so a batch scrape does not hit the Setting table
# twice per candidate. Settings changes take effect within 30 seconds.
_PUBLISHER_FILTER_TTL = 30
_publisher_filter_cache = {"expires": 0.0, "value": ((), ())}


def _publisher_filters():
    """Return (allow, block) as lowercase name tuples from settings."""
    now = time.monotonic()
    if now >= _publisher_filter_cache["expires"]:
        from apps.core.models import get_setting

        def split(raw):
            return tuple(p.strip().lower() for p in (raw or "").split(",") if p.strip())

        _publisher_filter_cache["value"] = (
            split(get_setting("scrape_publisher_allow", "")),
            split(get_setting("scrape_publisher_block", "")),
        )
        _publisher_filter_cache["expires"] = now + _PUBLISHER_FILTER_TTL
    return _publisher_filter_cache["value"]


def publisher_allowed(publisher):
    """
    Check a match's publisher against the auto-match allow/block lists.

    Both lists are substring matches on the lowercased publisher name, so
    "panini" blocks "Panini Comics", "Panini Verlag" and "Editorial Panini".
    An empty allow list allows everything. Matches with no publisher recorded
    pass both lists: plenty of ComicVine volumes have none, and dropping them
    would cost real matches to exclude a publisher that was never named.
    """
    allow, block = _publisher_filters()
    if not allow and not block:
        return True

    name = (publisher or "").strip().lower()
    if not name:
        return True
    if allow and not any(a in name for a in allow):
        return False
    return not any(b in name for b in block)


def filter_by_publisher(matches):
    """Drop matches whose publisher is excluded by the auto-match lists."""
    return [m for m in matches if publisher_allowed(m.publisher)]


def normalize_issue_number(num):
    """Normalize issue number for comparison."""
    if not num:
        return ""
    return str(num).lstrip("0").lower() or "0"


def _normalize_series(s):
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def series_match_quality(proposed, matched):
    """
    Return how closely two series names match.

    2 = exact match (normalized strings are identical)
    1 = partial match (substring or shared first word)
    0 = no match
    """
    p = _normalize_series(proposed)
    m = _normalize_series(matched)

    if p == m:
        return 2
    if p in m or m in p:
        return 1
    p_words = p.split()
    m_words = m.split()
    if p_words and m_words and p_words[0] == m_words[0]:
        return 1
    return 0


def series_matches(proposed, matched):
    """Check if two series names are similar enough to be the same series."""
    return series_match_quality(proposed, matched) > 0


def metadata_alignment_score(comic, match):
    """
    Score how well a CV match aligns with the comic's parsed metadata.

    Uses series/number/year with fallback to proposed_* fields so this
    works for both STATE_IMPORTED comics (may have ComicInfo data) and
    fresh imports (only proposed_* populated).

    Returns 0 if the match is disqualified, >0 for viable matches.
    Score breakdown:
      0 = disqualified (publisher excluded, wrong number, or series known on both sides but share no resemblance)
      1 = number only (no series to validate)
      2 = number + partial/substring series match
      3 = number + exact series match  OR  number + partial series + year
      4 = number + exact series + year
    Exact series matches intentionally outscore partial/substring matches so
    that collected editions sharing cover art with single issues (e.g. a TPB
    whose series name extends the original with a subtitle) do not beat the
    correct single-issue match on hash distance alone.
    """
    if not publisher_allowed(match.publisher):
        return 0

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
        quality = series_match_quality(cv_series, match.series)
        if quality > 0:
            # base: 2 for partial, 3 for exact
            score = 1 + quality
            if cv_year and match.start_year:
                try:
                    if abs(int(cv_year) - int(match.start_year)) <= 2:
                        score += 1
                except (ValueError, TypeError):
                    pass
        else:
            # Both series are known but share no resemblance — disqualify even if
            # the issue number matched, because #3 is far too common to rely on alone.
            return 0
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

    # Persist hashes immediately so they survive even when no match is found.
    # apply_cv_match does a full save later, but if scraping finds no match at
    # all, only flags is saved — the hashes computed here would be lost.
    hash_changed = comic.phash != hashes.phash_hex or comic.ahash != hashes.ahash_hex
    comic.phash = hashes.phash_hex
    comic.ahash = hashes.ahash_hex
    if hash_changed:
        comic.save(update_fields=["phash", "ahash"])

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


# Cover check for matches found by name (Layers 2 and 3): the comic's cover
# and the match's agree when their pHash and aHash distances add up to at
# most this. Measured in October 2026 on 1,485 random comics from a real
# library, against the right ComicVine issue and against 2,003 issues with
# the same number in other volumes of the same name: requiring both
# distances within 15 accepted 92.1% of the right issues and 30 wrong ones,
# a sum within 28 accepted 95.4% and 31 (often one hash is far off while the
# other is close, such as pHash 16 and aHash 5). Most wrong issues that pass
# are reprints with the same cover.
COVER_MATCH_MAX_SUM = 28

# Layer 2 takes a match its cover can't confirm only when its year is this
# close to the comic's (year_gap: cover year or volume start year).
METADATA_MAX_YEAR_GAP = 2


def covers_agree(pdist, adist):
    """Whether two covers are the same by their pHash and aHash distances."""
    return pdist + adist <= COVER_MATCH_MAX_SUM


def _comic_hashes(comic):
    """The comic's (pHash, aHash) as integers, or None."""
    try:
        return int(comic.phash, 16), int(comic.ahash, 16)
    except (TypeError, ValueError):
        return None


def local_cover_distance(scraper, hashes, issue_id):
    """
    The closest (pHash, aHash) distance between the comic's cover hashes and
    the issue's covers in comicvine.db, or None when it has none.
    """
    best = None
    for phash, ahash in scraper.cover_hashes(issue_id):
        distance = (bin(hashes[0] ^ phash).count("1"), bin(hashes[1] ^ ahash).count("1"))
        if best is None or sum(distance) < sum(best):
            best = distance
    return best


def try_metadata_match(comic, scraper):
    """
    Try to match a comic by series name and issue number in comicvine.db.

    Uses series/proposed_series and number/proposed_number with precedence
    given to the verified (non-proposed) fields. match_by_metadata gives the
    issues with that number in volumes with the series' name, closest year
    first, and excluded publishers are dropped. The first one whose cover
    agrees with the comic's (covers_agree, against the covers in
    comicvine.db) wins. Layer 1 has already compared covers, so the right
    issue often has another cover here (a variant, a different scan). Then
    the first one is taken when its year is within METADATA_MAX_YEAR_GAP of
    the comic's or, for a comic without a year, when only one volume has
    that number.

    Returns the best CVMatch or None; on None the reason is in
    flags["scrape_error_detail"].
    """
    from apps.scraper.comicvine import year_gap

    cv_series = comic.series or comic.proposed_series
    cv_number = comic.number or comic.proposed_number
    cv_year = comic.year or comic.proposed_year

    if not cv_series:
        return None

    matches = filter_by_publisher(scraper.match_by_metadata(
        series=cv_series,
        issue_number=cv_number or "",
        year=cv_year,
    ))
    if not matches:
        comic.flags["scrape_error_detail"] = (
            f'local comicvine.db: no volume named "{cv_series}" has #{cv_number or ""}'
        )
        return None

    hashes = _comic_hashes(comic)
    if hashes:
        for match in matches:
            distance = local_cover_distance(scraper, hashes, match.issue_id)
            if distance and covers_agree(*distance):
                return match

    best = matches[0]
    if cv_year:
        if year_gap(best, cv_year) <= METADATA_MAX_YEAR_GAP:
            return best
        found = (best.cover_date or "")[:4] or best.start_year
        reason = (
            f"the closest #{best.issue_number} is in {best.series} ({best.start_year}) from {found}, "
            f"the comic is from {cv_year}"
        )
    else:
        volumes = {m.volume_id for m in matches}
        if len(volumes) == 1:
            return best
        reason = f"{len(volumes)} volumes have #{best.issue_number} and the comic has no year"
    if hashes:
        reason += ", and none of their covers is close to the comic's"
    else:
        reason += ", and the comic has no cover to compare"
    comic.flags["scrape_error_detail"] = f"local comicvine.db: {reason}"[:300]
    return None


def find_best_match(comic, scraper, max_distance=None):
    """
    Find the best ComicVine match for a comic, automatically choosing the
    right strategy based on available data sources.

    Strategy (in order):
    1. Local DB available: hash match -> metadata match -> API fallback (if enabled)
    2. Local DB unavailable: API metadata match

    Returns the best CVMatch or None. Callers should not need to know which
    strategy was used — the match_type field on the result reflects it.
    """
    from apps.scraper.cv_sources import is_cv_db_available
    from apps.core.models import get_setting

    if max_distance is None:
        max_distance = get_setting("scrape_hash_threshold", 8)

    if is_cv_db_available():
        match = try_hash_match(comic, scraper, max_distance=max_distance)
        if not match:
            match = try_metadata_match(comic, scraper)
        if not match:
            if get_setting("scrape_api_fallback", False):
                match = try_api_metadata_match(comic, scraper)
            else:
                detail = comic.flags.get("scrape_error_detail") or "no match in the local comicvine.db"
                comic.flags["scrape_error_detail"] = (
                    f"{detail}; API fallback is off (Settings > Scraping)"
                )[:300]
        return match

    return try_api_metadata_match(comic, scraper)


# Volumes whose issues are looked up per comic, best ranked first. Each one
# costs an /issues call, so a comic that is not in the first volume costs more.
API_VOLUMES_TRIED = 3

# Volume search results ranked per comic. Still one /search call; ComicVine
# lists many regional reprints, so a new volume is often not in the first 10.
API_VOLUME_RESULTS = 30


def _as_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def rank_api_volumes(comic, volumes):
    """
    Order API volume results by how likely they hold the comic's issue.

    Volumes scoring 0 (series name too different, publisher excluded) are
    dropped. A volume that started more than a year after the comic's year
    cannot hold it and goes last. A volume with fewer issues than the comic's
    number goes after the ones with enough; it is kept, because volumes with
    legacy numbering (Amazing Spider-Man #800 in the 2015 volume) hold numbers
    far above their count. Within each group the highest score comes first,
    then the start year closest to the comic's year, so a relaunch with the
    same name does not win over the run the issue belongs to, and then
    ComicVine's own order.
    """
    cv_year = _as_int(comic.year or comic.proposed_year)
    digits = re.match(r"\d+", normalize_issue_number(comic.number or comic.proposed_number))
    number = int(digits.group()) if digits else None

    ranked = []
    for index, volume in enumerate(volumes):
        score = metadata_alignment_score(comic, volume)
        if score <= 0:
            continue
        start = _as_int(volume.start_year)
        count = _as_int(volume.issue_count)
        known = cv_year is not None and start is not None
        starts_after = known and start > cv_year + 1
        too_few = number is not None and count is not None and count < number
        distance = abs(cv_year - start) if known else 0
        ranked.append(((starts_after, too_few, -score, distance, index), volume))
    ranked.sort(key=lambda r: r[0])
    return [volume for _, volume in ranked]


def try_api_metadata_match(comic, scraper):
    """
    Match a comic using the ComicVine API with few calls.

    1. /search?resources=volume finds up to API_VOLUME_RESULTS volumes by
       series name, with publisher, start year and issue count inline, so no
       /volume calls are needed.
    2. /issues?filter=volume:{id},issue_number:{num} looks the issue up in up
       to API_VOLUMES_TRIED volumes, best ranked first (rank_api_volumes).
    3. When none of them gave a match, /search?resources=issue with
       "series number", like the manual search. A result needs the same
       number and a close series name (score 3 or more).
    4. /issue/4000-{id} fetches full details and credits for the match.

    Every issue found has its cover checked against the comic's cover hash
    (_verify_cover_hash) before step 4. A comic found in the first volume
    costs 3 calls; at most it costs 1 + API_VOLUMES_TRIED + 2. When nothing
    matches, the reason is stored in flags["scrape_error_detail"].
    """
    import logging
    from apps.core.models import get_setting
    from apps.scraper.cv_sources import check_api_budget

    logger = logging.getLogger(__name__)
    cv_series = comic.series or comic.proposed_series
    cv_number = comic.number or comic.proposed_number

    def give_up(reason):
        comic.flags["scrape_error_detail"] = f"ComicVine API: {reason}"[:300]
        logger.info("API match gave up for comic %s: %s", comic.pk, reason)
        return None

    if not cv_series:
        return give_up("the comic has no series name to search for")

    out_of_budget = "the budget of 200 calls per hour is used up, try again later"

    if not get_setting("cv_api_key", "").strip():
        return give_up("no API key is set in Settings")

    if not check_api_budget(required=3):
        return give_up(out_of_budget)

    # Step 1: search volumes by series name
    volumes = scraper.search_volumes_api(cv_series, limit=API_VOLUME_RESULTS)
    if not volumes:
        return give_up(f'no volume found for "{cv_series}"')

    candidates = rank_api_volumes(comic, volumes)
    if not candidates:
        return give_up(
            f'none of the {len(volumes)} volumes found for "{cv_series}" has a similar name '
            f"and an allowed publisher"
        )
    if not cv_number:
        # No issue number to filter on: only a one-shot can be looked up, as #1
        if candidates[0].issue_count != 1:
            return give_up("the comic has no issue number and the best volume is not a one-shot")
        candidates = candidates[:1]
    number = cv_number or "1"

    not_found = []  # volumes without the issue
    rejected = []  # issues whose cover does not match
    unfetched = []  # issues whose details could not be fetched
    checked = set()

    def fetch(issue, label, match_type):
        """Check the issue's cover, then fetch its details. None when either fails."""
        checked.add(issue.issue_id)
        comic.flags.pop("scrape_error_detail", None)
        if not _verify_cover_hash(comic, issue):
            reason = comic.flags.pop("scrape_error_detail", None) or "cover hash mismatch"
            rejected.append(f"{label} ({reason})")
            logger.info("API match rejected by cover hash for comic %s (issue %s)", comic.pk, issue.issue_id)
            return None
        detailed = scraper.get_issue_from_api(issue.issue_id)
        if not detailed:
            unfetched.append(issue.issue_id)
            return None
        detailed.match_type = match_type
        return detailed

    # Step 2: find the issue in the best ranked volumes
    for volume in candidates[:API_VOLUMES_TRIED]:
        if not check_api_budget(required=2):
            return give_up(out_of_budget)
        label = f"{volume.series} ({volume.start_year})" if volume.start_year else volume.series
        issue = scraper.get_issue_by_volume_and_number(volume.volume_id, number)
        if not issue:
            not_found.append(label)
            continue
        detailed = fetch(issue, f"{label} #{issue.issue_number}", "api+volume+detail")
        if detailed:
            return detailed
        if unfetched:
            return give_up(f"could not fetch the details of issue 4000-{unfetched[0]}")

    # Step 3: search issues like the manual search does
    found = []
    if cv_number:
        if not check_api_budget(required=2):
            return give_up(out_of_budget)
        publishers = {v.volume_id: v.publisher for v in volumes}
        for match in scraper.search_api(f"{cv_series} {cv_number}", limit=10):
            if match.issue_id in checked:
                continue
            if not match.publisher:
                match.publisher = publishers.get(match.volume_id)
            score = metadata_alignment_score(comic, match)
            if score >= 3:
                found.append((match, score))
        found.sort(key=lambda f: -f[1])
        for match, _ in found[:API_VOLUMES_TRIED]:
            label = f"{match.series} #{match.issue_number}"
            detailed = fetch(match, label, "api+search+detail")
            if detailed:
                return detailed
            if unfetched:
                return give_up(f"could not fetch the details of issue 4000-{unfetched[0]}")

    reasons = []
    if not_found:
        reasons.append(f"#{number} is not in " + ", ".join(not_found))
    if rejected:
        reasons.append("the cover does not match " + "; ".join(rejected))
    if cv_number and not found:
        reasons.append(
            f'the issue search for "{cv_series} {cv_number}" found no other issue with that number '
            f"and a close series name"
        )
    return give_up("; ".join(reasons))


def _verify_cover_hash(comic, match):
    """
    Download the CV cover for `match` and compare it against the comic's stored phash/ahash.
    Returns True if hashes agree (or if verification cannot be performed).
    Returns False if the cover hash clearly disagrees, indicating a likely wrong match.
    Uses covers_agree, which is more lenient than the Layer 1 threshold since
    API covers may differ slightly from local scans (different crop or edition).
    """
    import io
    import imagehash
    from PIL import Image
    from apps.core.cover_cache import get_cv_cover

    if not match.cover_url:
        return True

    # If hashes aren't stored yet (e.g. API-only mode skipped Layer 1),
    # compute them now from the local file so we can still verify.
    if (not comic.phash or not comic.ahash) and comic.file_path:
        hashes = extract_cover_hashes(comic.file_path)
        if hashes:
            comic.phash = hashes.phash_hex
            comic.ahash = hashes.ahash_hex

    if not comic.phash or not comic.ahash:
        return True

    try:
        cover_bytes = get_cv_cover(match.issue_id, match.cover_url)
        if not cover_bytes:
            return True
        img = Image.open(io.BytesIO(cover_bytes)).convert("RGB")
        api_phash = imagehash.phash(img)
        api_ahash = imagehash.average_hash(img)
        local_phash = imagehash.hex_to_hash(comic.phash)
        local_ahash = imagehash.hex_to_hash(comic.ahash)
        pdist = api_phash - local_phash
        adist = api_ahash - local_ahash
        if covers_agree(pdist, adist):
            return True
        comic.flags["scrape_error_detail"] = (
            f"cover hash mismatch (phash dist {pdist}, ahash dist {adist})"
        )
        return False
    except Exception:
        return True


def apply_cv_match(comic, match, scraper=None, insert_covers=True):
    """
    Apply ComicVine match data to a comic and advance its workflow state.

    Enriches the match with credits if needed, writes all metadata fields,
    optionally inserts variant covers into the CBZ, updates the state to
    STATE_COUNTED, and propagates the issue count to other comics in the volume.

    Args:
        insert_covers: If True, download and insert variant covers into the CBZ now.
                       If False, store the cover URLs in custom_values so the write
                       step can insert them later (avoids CBZ extraction during scraping).
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
    if match.story_arcs:
        comic.story_arc = match.story_arcs

    comic.custom_values["comicvine_issue"] = str(match.issue_id)
    comic.custom_values["comicvine_volume"] = str(match.volume_id)
    if match.issue_count:
        comic.custom_values["comicvine_issue_count"] = str(match.issue_count)
    comic.custom_values["scrape_source"] = match.match_type
    comic.custom_values["scrape_score"] = str(match.match_score)

    # Handle variant covers for digital CBZ comics that haven't had covers inserted yet
    if (comic.is_digital and comic.file_path and comic.file_path.lower().endswith(".cbz")
            and match.cover_urls and comic.custom_values.get("HasAltCovers") != "Yes"):
        unique_urls = []
        seen_urls = set()
        for url in match.cover_urls:
            if url and url not in seen_urls:
                unique_urls.append(url)
                seen_urls.add(url)

        if unique_urls:
            if insert_covers:
                inserted = insert_variant_covers(comic.file_path, unique_urls)
                if inserted > 0:
                    comic.custom_values["HasAltCovers"] = "Yes"
                    comic.custom_values["AltCoverCount"] = inserted
                    if comic.page_count:
                        comic.page_count += inserted
                    from apps.core.cover_cache import invalidate_comic_pages
                    invalidate_comic_pages(comic.pk)
            else:
                # Defer insertion to write time
                comic.custom_values["pending_alt_cover_urls"] = unique_urls

    comic.remove_flag("scrape_no_match")
    comic.remove_flag("scrape_error")
    comic.remove_flag("scrape_error_detail")
    comic.remove_flag("metadata_mismatch")
    comic.remove_flag("scrape_skipped")

    # Flag comics from publishers not covered by any tagging ruleset
    if comic.publisher:
        from apps.tagging.engine import is_publisher_known
        if is_publisher_known(comic.publisher):
            comic.remove_flag("unknown_publisher")
        else:
            comic.add_flag("unknown_publisher")

    # For physical comics store all cover URLs so the detail page can show them
    if comic.is_physical:
        if match.cover_urls:
            comic.custom_values["physical_cover_urls"] = [u for u in match.cover_urls if u][:20]
        if match.cover_url:
            comic.custom_values["physical_main_cover_url"] = match.cover_url

    comic.state = Comic.STATE_TAGGED
    comic.save()

    # For physical comics, cache the CV cover image (no CBZ to insert into)
    if comic.is_physical and match.cover_url:
        from apps.core.cover_cache import cache_physical_cover
        cache_physical_cover(comic.pk, match.cover_url)

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
    else:
        # Story-only: treat as a one-shot — use story title as series name
        if match.title:
            comic.series = match.title

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
    comic.remove_flag("scrape_skipped")

    # Flag comics from publishers not covered by any tagging ruleset
    if comic.publisher:
        from apps.tagging.engine import is_publisher_known
        if is_publisher_known(comic.publisher):
            comic.remove_flag("unknown_publisher")
        else:
            comic.add_flag("unknown_publisher")

    # Inducks comics skip the count stage and go directly to tagging
    comic.state = Comic.STATE_TAGGED
    comic.save()

    # For physical comics, cache the Inducks cover image (no CBZ to insert into)
    if comic.is_physical and getattr(match, "cover_url", None):
        from apps.core.cover_cache import get_inducks_cover, invalidate_comic_cover, COVER_CACHE_DIR, _ensure_cache_dir
        cover_data = get_inducks_cover(match.issuecode or "unknown", match.cover_url)
        if cover_data:
            invalidate_comic_cover(comic.pk)
            _ensure_cache_dir()
            (COVER_CACHE_DIR / f"{comic.pk}.jpg").write_bytes(cover_data)


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
