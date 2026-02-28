"""
Celery tasks for long-running core operations.
"""

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


# =============================================================================
# Cancel helpers (Redis-backed, cross-process)
# =============================================================================

def _cancel_client():
    """Return a Redis client for cancel flags (db=1, same host as broker)."""
    import redis as _redis
    from django.conf import settings
    url = getattr(settings, "CELERY_BROKER_URL", "redis://redis:6379/0")
    # Use db=1 for cancel flags to avoid collisions with the broker (db=0)
    base = url.rsplit("/", 1)[0]
    return _redis.from_url(f"{base}/1", decode_responses=True)


def request_cancel(task_id):
    """Signal a task to cancel cooperatively. Workers check this before each item."""
    _cancel_client().setex(f"cancel:{task_id}", 7200, "1")


def is_cancelled(task_id):
    """Return True if a cancel has been requested for this task."""
    return bool(_cancel_client().get(f"cancel:{task_id}"))


def clear_cancel(task_id):
    """Remove the cancel flag (called when task finishes or honours the request)."""
    _cancel_client().delete(f"cancel:{task_id}")


# =============================================================================
# Write tasks
# =============================================================================

@shared_task(bind=True, name="core.write_all_comics", queue="write")
def write_all_comics_task(self):
    """
    Write ComicInfo.xml for all comics in 'organized' state.
    Reports progress via self.update_state().
    """
    from .models import Comic
    from .utils import write_comicinfo_xml

    comic_ids = list(
        Comic.objects.filter(state=Comic.STATE_ORGANIZED)
        .values_list("pk", flat=True)
    )
    total = len(comic_ids)

    if total == 0:
        return {"written": 0, "total": 0, "errors": [], "cancelled": False}

    written = 0
    errors = []

    for i, comic_id in enumerate(comic_ids):
        if is_cancelled(self.request.id):
            clear_cancel(self.request.id)
            return {"written": written, "total": total, "errors": errors, "cancelled": True}

        try:
            comic = Comic.objects.get(pk=comic_id)
        except Comic.DoesNotExist:
            continue

        if comic.is_digital and comic.file_path and comic.file_path.lower().endswith(".cbz"):
            success = write_comicinfo_xml(comic.file_path, comic)
            if not success:
                errors.append(f"{comic.series} #{comic.number}: Failed to write XML")
                self.update_state(
                    state="PROGRESS",
                    meta={"current": i + 1, "total": total, "written": written, "errors": errors},
                )
                continue

        comic.state = Comic.STATE_WRITTEN
        comic.last_written = timezone.now()
        if comic.flags.get("count_updated"):
            comic.flags.pop("count_updated", None)
        comic.save()
        written += 1

        self.update_state(
            state="PROGRESS",
            meta={"current": i + 1, "total": total, "written": written, "errors": errors},
        )

    return {"written": written, "total": total, "errors": errors, "cancelled": False}


@shared_task(bind=True, name="core.rewrite_updated_comics", queue="write")
def rewrite_updated_comics_task(self):
    """
    Rewrite ComicInfo.xml for all comics with the count_updated flag.
    Reports progress via self.update_state().
    """
    from .models import Comic
    from .utils import write_comicinfo_xml

    comic_ids = list(
        Comic.objects.filter(
            flags__count_updated=True,
            medium=Comic.MEDIUM_DIGITAL,
        ).values_list("pk", flat=True)
    )
    total = len(comic_ids)

    if total == 0:
        return {"written": 0, "total": 0, "errors": [], "cancelled": False}

    written = 0
    errors = []

    for i, comic_id in enumerate(comic_ids):
        if is_cancelled(self.request.id):
            clear_cancel(self.request.id)
            return {"written": written, "total": total, "errors": errors, "cancelled": True}

        try:
            comic = Comic.objects.get(pk=comic_id)
        except Comic.DoesNotExist:
            continue

        if comic.file_path and comic.file_path.lower().endswith(".cbz"):
            success = write_comicinfo_xml(comic.file_path, comic)
            if not success:
                errors.append(f"{comic.series} #{comic.number}: Failed to write XML")
                self.update_state(
                    state="PROGRESS",
                    meta={"current": i + 1, "total": total, "written": written, "errors": errors},
                )
                continue

        comic.last_written = timezone.now()
        comic.flags.pop("count_updated", None)
        comic.save()
        written += 1

        self.update_state(
            state="PROGRESS",
            meta={"current": i + 1, "total": total, "written": written, "errors": errors},
        )

    return {"written": written, "total": total, "errors": errors, "cancelled": False}


# =============================================================================
# Scan / Import tasks
# =============================================================================

@shared_task(bind=True, name="core.scan_untagged", queue="import")
def scan_untagged_task(self):
    """
    Scan the untagged folder for new comics and import them.
    Reports progress during the scan phase.
    """
    from .services import scan_untagged_folder

    self.update_state(
        state="PROGRESS",
        meta={"current": 0, "total": 0, "processed": 0, "errors": []},
    )

    result = scan_untagged_folder()

    return {
        "processed": result["imported"],
        "total": result["imported"] + result["skipped"],
        "imported": result["imported"],
        "skipped": result["skipped"],
        "cleaned": result["cleaned"],
        "errors": result.get("errors", []),
        "cancelled": False,
    }


@shared_task(bind=True, name="core.convert_all_cbr", queue="import")
def convert_all_cbr_task(self):
    """
    Convert all CBR/CB7 files flagged for conversion to CBZ format.
    """
    import os
    import tempfile
    import zipfile
    from pathlib import Path
    from .models import Comic

    comic_ids = list(
        Comic.objects.filter(flags__needs_conversion=True)
        .values_list("pk", flat=True)
    )
    total = len(comic_ids)

    if total == 0:
        return {"converted": 0, "total": 0, "errors": [], "cancelled": False}

    converted = 0
    errors = []

    self.update_state(
        state="PROGRESS",
        meta={"current": 0, "total": total, "processed": converted, "errors": errors},
    )

    for i, comic_id in enumerate(comic_ids):
        if is_cancelled(self.request.id):
            clear_cancel(self.request.id)
            return {"converted": converted, "processed": converted, "total": total, "errors": errors, "cancelled": True}

        try:
            comic = Comic.objects.get(pk=comic_id)
        except Comic.DoesNotExist:
            continue

        if comic.file_format not in ("cbr", "cb7"):
            continue

        if not comic.file_path or not os.path.exists(comic.file_path):
            errors.append(f"{comic.proposed_series} #{comic.proposed_number}: file not found")
            continue

        original_path = Path(comic.file_path)
        new_path = original_path.with_suffix(".cbz")

        if new_path.exists():
            errors.append(f"{comic.proposed_series} #{comic.proposed_number}: target already exists")
            continue

        try:
            import patoolib

            with tempfile.TemporaryDirectory() as temp_dir:
                patoolib.extract_archive(str(original_path), outdir=temp_dir, verbosity=-1)

                with zipfile.ZipFile(new_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for root, dirs, files in os.walk(temp_dir):
                        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__MACOSX"]
                        for file in sorted(files):
                            if file.startswith(".") or file == "Thumbs.db":
                                continue
                            file_path = Path(root) / file
                            arc_path = file_path.relative_to(temp_dir)
                            zf.write(file_path, arc_path)

            comic.file_path = str(new_path)
            comic.file_format = "cbz"
            if comic.flags and "needs_conversion" in comic.flags:
                del comic.flags["needs_conversion"]
                if not comic.flags:
                    comic.flags = {}
            comic.save()
            original_path.unlink()
            converted += 1

        except Exception as e:
            if new_path.exists():
                new_path.unlink()
            errors.append(f"{comic.proposed_series} #{comic.proposed_number}: {str(e)}")

        self.update_state(
            state="PROGRESS",
            meta={"current": i + 1, "total": total, "processed": converted, "errors": errors},
        )

    return {"converted": converted, "processed": converted, "total": total, "errors": errors, "cancelled": False}


# =============================================================================
# Scrape task
# =============================================================================

@shared_task(bind=True, name="core.scrape_all", queue="scrape")
def scrape_all_task(self):
    """
    Scrape all comics in 'imported' state against the ComicVine database.

    When the local comicvine.db is unavailable, falls back to the ComicVine API
    (API-only mode). The API budget is checked before each comic; if the 200/hour
    limit is reached the task stops early with a clear error message.
    """
    from .models import Comic
    from apps.scraper.comicvine import ComicVineScraper
    from apps.scraper.cv_sources import is_cv_db_available, check_api_budget, get_api_calls_remaining
    from apps.scraper.services import find_best_match, apply_cv_match

    comic_ids = list(
        Comic.objects.filter(
            state=Comic.STATE_IMPORTED,
            medium=Comic.MEDIUM_DIGITAL,
        ).values_list("pk", flat=True)
    )
    total = len(comic_ids)

    if total == 0:
        return {"matched": 0, "failed": 0, "total": 0, "errors": [], "cancelled": False}

    db_available = is_cv_db_available()
    matched = 0
    failed = 0
    errors = []
    budget_exhausted = False

    self.update_state(
        state="PROGRESS",
        meta={"current": 0, "total": total, "processed": 0, "errors": [],
              "api_mode": not db_available},
    )

    scraper = ComicVineScraper()

    for i, comic_id in enumerate(comic_ids):
        if is_cancelled(self.request.id):
            clear_cancel(self.request.id)
            return {
                "matched": matched, "failed": failed,
                "processed": matched + failed,
                "total": total, "errors": errors, "cancelled": True,
            }

        # In API-only mode, stop early if budget is exhausted
        if not db_available and not check_api_budget(required=3):
            remaining = get_api_calls_remaining()
            budget_exhausted = True
            errors.append(
                f"API budget exhausted ({remaining} calls left). "
                f"Processed {i}/{total} comics. Retry in up to an hour."
            )
            break

        try:
            comic = Comic.objects.get(pk=comic_id)
        except Comic.DoesNotExist:
            continue

        # Clear any previous scrape error flags before re-attempting
        _scrape_flag_keys = ("scrape_no_match", "scrape_error", "scrape_error_detail")
        if any(f in comic.flags for f in _scrape_flag_keys):
            for f in _scrape_flag_keys:
                comic.flags.pop(f, None)
            comic.save(update_fields=["flags"])

        try:
            match = find_best_match(comic, scraper)

            before_series = comic.series
            before_publisher = comic.publisher
            before_cv_issue = (comic.custom_values or {}).get("comicvine_issue")
            before_cv_volume = (comic.custom_values or {}).get("comicvine_volume")

            if match:
                apply_cv_match(comic, match, scraper)
                matched += 1

                from .audit import log_batch_entry
                changes = {}
                if comic.series != before_series:
                    changes["series"] = [before_series, comic.series]
                if comic.publisher != before_publisher:
                    changes["publisher"] = [before_publisher, comic.publisher]
                after_cv_issue = (comic.custom_values or {}).get("comicvine_issue")
                after_cv_volume = (comic.custom_values or {}).get("comicvine_volume")
                if after_cv_issue != before_cv_issue:
                    changes["cv_issue"] = [before_cv_issue, after_cv_issue]
                if after_cv_volume != before_cv_volume:
                    changes["cv_volume"] = [before_cv_volume, after_cv_volume]
                log_batch_entry("scrape_all", comic, Comic.STATE_IMPORTED, comic.state, changes)
            else:
                comic.add_flag("scrape_no_match")
                comic.save(update_fields=["flags"])
                failed += 1
                errors.append(f"{comic.series} #{comic.number}: no match found")

                from .audit import log_batch_entry
                log_batch_entry("scrape_all", comic, Comic.STATE_IMPORTED, comic.state,
                                {"result": [None, "no_match"]})
        except Exception as e:
            err_msg = str(e)
            comic.flags["scrape_error"] = True
            comic.flags["scrape_error_detail"] = err_msg[:300]
            comic.flags.pop("scrape_no_match", None)
            comic.save(update_fields=["flags"])
            failed += 1
            errors.append(f"{comic.series} #{comic.number}: {err_msg[:150]}")

            from .audit import log_batch_entry
            log_batch_entry("scrape_all", comic, Comic.STATE_IMPORTED, comic.state,
                            {"result": [None, "error"]})

        self.update_state(
            state="PROGRESS",
            meta={
                "current": i + 1,
                "total": total,
                "processed": matched + failed,
                "errors": errors,
                "api_mode": not db_available,
            },
        )

    return {
        "matched": matched,
        "failed": failed,
        "processed": matched + failed,
        "total": total,
        "errors": errors,
        "cancelled": False,
        "budget_exhausted": budget_exhausted,
        "api_mode": not db_available,
    }


# =============================================================================
# Tag / Format tasks
# =============================================================================

@shared_task(bind=True, name="core.tag_all", queue="write")
def tag_all_task(self):
    """
    Apply DataManager rules to all comics in 'counted' state.
    """
    from .models import Comic
    from apps.dashboard.tasks import _run_tag

    comic_ids = list(
        Comic.objects.filter(state=Comic.STATE_COUNTED)
        .values_list("pk", flat=True)
    )
    total = len(comic_ids)

    if total == 0:
        return {"processed": 0, "total": 0, "errors": [], "cancelled": False}

    processed = 0
    errors = []

    self.update_state(
        state="PROGRESS",
        meta={"current": 0, "total": total, "processed": 0, "errors": []},
    )

    for i, comic_id in enumerate(comic_ids):
        if is_cancelled(self.request.id):
            clear_cancel(self.request.id)
            return {"processed": processed, "total": total, "errors": errors, "cancelled": True}

        try:
            comic = Comic.objects.get(pk=comic_id)
        except Comic.DoesNotExist:
            continue

        try:
            _run_tag(comic)
            processed += 1
        except Exception as e:
            errors.append(f"{comic.series} #{comic.number}: {str(e)}")

        self.update_state(
            state="PROGRESS",
            meta={"current": i + 1, "total": total, "processed": processed, "errors": errors},
        )

    return {"processed": processed, "total": total, "errors": errors, "cancelled": False}


@shared_task(bind=True, name="core.format_all", queue="write")
def format_all_task(self):
    """
    Apply format detection to all comics in 'tagged' state.
    """
    from .models import Comic
    from apps.dashboard.tasks import _run_format

    comic_ids = list(
        Comic.objects.filter(state=Comic.STATE_TAGGED)
        .values_list("pk", flat=True)
    )
    total = len(comic_ids)

    if total == 0:
        return {"processed": 0, "total": 0, "errors": [], "cancelled": False}

    processed = 0
    errors = []

    self.update_state(
        state="PROGRESS",
        meta={"current": 0, "total": total, "processed": 0, "errors": []},
    )

    for i, comic_id in enumerate(comic_ids):
        if is_cancelled(self.request.id):
            clear_cancel(self.request.id)
            return {"processed": processed, "total": total, "errors": errors, "cancelled": True}

        try:
            comic = Comic.objects.get(pk=comic_id)
        except Comic.DoesNotExist:
            continue

        try:
            _run_format(comic)
            processed += 1
        except Exception as e:
            errors.append(f"{comic.series} #{comic.number}: {str(e)}")

        self.update_state(
            state="PROGRESS",
            meta={"current": i + 1, "total": total, "processed": processed, "errors": errors},
        )

    return {"processed": processed, "total": total, "errors": errors, "cancelled": False}


# =============================================================================
# Organize / Deduplicate tasks
# =============================================================================

@shared_task(bind=True, name="core.organize_all", queue="organize")
def organize_all_task(self):
    """
    Organize all comics in 'deduplicated' state into the library.
    """
    from .models import Comic
    from apps.dashboard.tasks import _run_organize

    comic_ids = list(
        Comic.objects.filter(state=Comic.STATE_DEDUPLICATED)
        .values_list("pk", flat=True)
    )
    total = len(comic_ids)

    if total == 0:
        return {"processed": 0, "total": 0, "errors": [], "cancelled": False}

    processed = 0
    errors = []

    self.update_state(
        state="PROGRESS",
        meta={"current": 0, "total": total, "processed": 0, "errors": []},
    )

    for i, comic_id in enumerate(comic_ids):
        if is_cancelled(self.request.id):
            clear_cancel(self.request.id)
            return {"processed": processed, "total": total, "errors": errors, "cancelled": True}

        try:
            comic = Comic.objects.get(pk=comic_id)
        except Comic.DoesNotExist:
            continue

        try:
            _run_organize(comic)
            processed += 1
        except Exception as e:
            errors.append(f"{comic.series} #{comic.number}: {str(e)}")

        self.update_state(
            state="PROGRESS",
            meta={"current": i + 1, "total": total, "processed": processed, "errors": errors},
        )

    return {"processed": processed, "total": total, "errors": errors, "cancelled": False}


@shared_task(bind=True, name="core.deduplicate_all", queue="organize")
def deduplicate_all_task(self):
    """
    Run duplicate detection on all comics in 'formatted' state.
    """
    self.update_state(
        state="PROGRESS",
        meta={"current": 0, "total": 0, "processed": 0, "errors": []},
    )

    from apps.duplicates.services import run_duplicate_detection
    result = run_duplicate_detection()

    return {
        "processed": result.get("advanced", 0),
        "total": result.get("total_comics", 0),
        "groups_created": result.get("groups_created", 0),
        "errors": [],
        "cancelled": False,
    }


# =============================================================================
# Search alt covers task
# =============================================================================

@shared_task(bind=True, name="core.search_alt_covers", queue="import")
def search_alt_covers_task(self, comic_pk, variant_urls):
    """
    Download and insert variant covers into a comic's CBZ file.
    """
    from .models import Comic
    from .cbz_utils import insert_variant_covers
    from .cover_cache import invalidate_comic_pages

    self.update_state(
        state="PROGRESS",
        meta={"current": 0, "total": len(variant_urls), "processed": 0, "errors": []},
    )

    try:
        comic = Comic.objects.get(pk=comic_pk)
    except Comic.DoesNotExist:
        return {"success": False, "error": "Comic not found", "inserted": 0}

    inserted = insert_variant_covers(comic.file_path, variant_urls)

    if inserted > 0:
        comic.custom_values["HasAltCovers"] = "Yes"
        comic.custom_values["AltCoverCount"] = inserted
        if comic.page_count:
            comic.page_count += inserted
        comic.save()
        invalidate_comic_pages(comic.pk)
        return {"success": True, "inserted": inserted, "processed": inserted, "total": len(variant_urls)}

    return {"success": False, "error": "No covers downloaded", "inserted": 0}
