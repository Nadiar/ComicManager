"""
Scraper views - web interface for testing and running the scraper.
"""

import io
from django.shortcuts import render
from django.http import StreamingHttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods

from apps.core.models import Comic
from apps.core.utils import natural_number_annotation
from apps.scraper.comicvine import ComicVineScraper, CVMatch
from apps.scraper.hasher import extract_cover_hashes
from apps.scraper.services import metadata_alignment_score as _metadata_alignment_score


def index(request):
    """Scraper dashboard - shows unscraped comics and scrape controls."""
    # Get comics that can be scraped (imported state)
    imported_comics = Comic.objects.filter(
        state=Comic.STATE_IMPORTED,
        medium=Comic.MEDIUM_DIGITAL,
    ).annotate(
        number_sort_key=natural_number_annotation()
    ).order_by("series", "number_sort_key", "number")

    # Count by state
    stats = {
        "imported": Comic.objects.filter(state=Comic.STATE_IMPORTED).count(),
        "scraped": Comic.objects.filter(state=Comic.STATE_SCRAPED).count(),
    }

    return render(request, "scraper/index.html", {
        "comics": imported_comics,
        "stats": stats,
    })


def scrape_dry_run(request):
    """
    Run scraper in dry-run mode and return results as HTML.
    Uses streaming response for real-time output.
    """
    limit = int(request.GET.get("limit", 2))
    max_distance = int(request.GET.get("max_distance", 10))

    def generate():
        yield '<div class="font-mono text-sm space-y-4">\n'
        yield '<div class="text-warning font-bold">DRY RUN - no changes will be made</div>\n'

        scraper = ComicVineScraper()

        # Get comics without flags (skip flagged comics like PDFs, needs_conversion, etc.)
        all_comics = Comic.objects.filter(
            state=Comic.STATE_IMPORTED,
            medium=Comic.MEDIUM_DIGITAL,
        ).annotate(
            number_sort_key=natural_number_annotation()
        ).order_by("series", "number_sort_key", "number")

        # Filter out comics with any flags
        comics = [c for c in all_comics if not c.has_flags][:limit]

        total = len(comics)
        skipped = all_comics.count() - len([c for c in all_comics if not c.has_flags])
        yield f'<div>Processing {total} comic(s)'
        if skipped > 0:
            yield f' <span class="text-base-content/50">(skipped {skipped} with flags)</span>'
        yield '</div>\n'
        yield '<hr class="border-base-300 my-2">\n'

        matched = 0
        failed = 0

        for comic in comics:
            yield f'<div class="bg-base-300 p-3 rounded-lg">\n'
            yield f'<div class="font-bold text-primary">{comic.proposed_series} #{comic.proposed_number}</div>\n'
            yield f'<div class="text-xs text-base-content/50 truncate">{comic.file_path}</div>\n'

            match = None

            # Try hash matching
            if comic.file_path:
                match, log = _try_hash_match_with_log(comic, scraper, max_distance)
                yield log

            # Fall back to metadata
            if not match:
                match, log = _try_metadata_match_with_log(comic, scraper)
                yield log

            if match:
                matched += 1
                yield f'<div class="mt-2 p-2 bg-success/20 rounded">\n'
                yield f'<div class="text-success font-bold">MATCH: {match.series} #{match.issue_number} ({match.start_year}) - {match.publisher}</div>\n'
                yield f'<div class="text-xs">CV Issue ID: {match.issue_id} | {match.match_type} (score: {match.match_score})</div>\n'
                yield '</div>\n'
            else:
                failed += 1
                yield '<div class="mt-2 p-2 bg-warning/20 rounded text-warning">NO MATCH FOUND</div>\n'

            yield '</div>\n'

        yield '<hr class="border-base-300 my-2">\n'
        yield f'<div class="font-bold">Results: <span class="text-success">{matched} matched</span>, <span class="text-warning">{failed} failed</span></div>\n'
        yield '</div>\n'

    return StreamingHttpResponse(generate(), content_type="text/html")


def _try_hash_match_with_log(comic, scraper, max_distance):
    """Try hash match and return (match, html_log)."""
    log = io.StringIO()
    log.write('<div class="mt-2 text-xs">\n')
    log.write('<div>Trying hash match...</div>\n')

    # Extract cover hashes
    hashes = extract_cover_hashes(comic.file_path)
    if not hashes:
        log.write('<div class="text-warning">Could not extract cover hashes</div>\n')
        log.write('</div>\n')
        return None, log.getvalue()

    log.write(f'<div class="text-base-content/60">phash: {hashes.phash_hex} | ahash: {hashes.ahash_hex}</div>\n')

    # Find matches
    matches = scraper.match_by_hash_fast(
        hashes.phash,
        hashes.ahash,
        max_distance=max_distance,
        limit=10,
    )

    if not matches:
        log.write('<div class="text-base-content/60">No hash matches found</div>\n')
        log.write('</div>\n')
        return None, log.getvalue()

    log.write(f'<div>Found {len(matches)} hash candidates:</div>\n')
    log.write('<ul class="ml-4">\n')

    # Cross-validate
    validated = []
    for match in matches:
        score = _metadata_alignment_score(comic, match)
        if score > 0:
            validated.append((match, score))
            log.write(
                f'<li class="text-success">+ {match.series} #{match.issue_number} '
                f'({match.start_year}) [align:{score}, hash:{match.match_score}]</li>\n'
            )
        else:
            log.write(
                f'<li class="text-error">- {match.series} #{match.issue_number} '
                f'({match.start_year}) [metadata mismatch]</li>\n'
            )

    log.write('</ul>\n')
    log.write('</div>\n')

    if validated:
        validated.sort(key=lambda x: (-x[1], x[0].match_score))
        best = validated[0][0]
        best.match_type = f"{best.match_type}+meta"
        return best, log.getvalue()

    log.write('<div class="text-warning">No hash matches passed metadata validation</div>\n')
    return None, log.getvalue()


def _try_metadata_match_with_log(comic, scraper):
    """Try metadata match and return (match, html_log)."""
    log = io.StringIO()
    log.write('<div class="mt-2 text-xs">\n')
    log.write('<div>Trying metadata match (fallback)...</div>\n')

    if not comic.proposed_series or not comic.proposed_number:
        log.write('<div class="text-warning">Missing series or number</div>\n')
        log.write('</div>\n')
        return None, log.getvalue()

    matches = scraper.match_by_metadata(
        series=comic.proposed_series,
        issue_number=comic.proposed_number,
        year=comic.proposed_year,
    )

    if matches:
        log.write(f'<div>Found {len(matches)} metadata matches:</div>\n')
        log.write('<ul class="ml-4">\n')
        for m in matches[:5]:
            log.write(
                f'<li>{m.series} #{m.issue_number} ({m.start_year}) - {m.publisher}</li>\n'
            )
        log.write('</ul>\n')
        log.write('</div>\n')
        return matches[0], log.getvalue()

    log.write('<div class="text-base-content/60">No metadata matches found</div>\n')
    log.write('</div>\n')
    return None, log.getvalue()


