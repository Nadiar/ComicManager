"""
Celery tasks for long-running core operations.
"""

from celery import shared_task
from django.db import transaction
from django.utils import timezone
from .task_base import ProgressTask, request_cancel, is_cancelled, clear_cancel


# =============================================================================
# Write tasks
#
# All four flavors run the same loop with different querysets and force flags.
# WRITE_QUEUES holds the parameters; _process_write_queue runs the loop. The
# four shared_task wrappers are kept so existing Celery task names stay
# registered and external callers (.delay(), URL-bound views) keep working.
# =============================================================================

def _write_queue_qs(filter_mode):
    """Return a queryset of comic PKs eligible for the given write filter."""
    from .models import Comic
    from django.db.models import F

    if filter_mode == "all":
        return Comic.objects.filter(state=Comic.STATE_WRITTEN).values_list("pk", flat=True)
    if filter_mode == "stale":
        return (
            Comic.objects.filter(
                last_written__isnull=False,
                updated_at__gt=F("last_written"),
            )
            .values_list("pk", flat=True)
        )
    if filter_mode == "missing":
        return (
            Comic.objects.filter(
                state=Comic.STATE_WRITTEN,
                medium=Comic.MEDIUM_DIGITAL,
                last_written__isnull=True,
            )
            .order_by("series", "number")
            .values_list("pk", flat=True)
        )
    if filter_mode == "count_updated":
        return Comic.objects.filter(
            flags__count_updated=True,
            medium=Comic.MEDIUM_DIGITAL,
        ).values_list("pk", flat=True)
    raise ValueError(f"Unknown write filter_mode: {filter_mode}")


# Filter modes that need force=True on workflow.write because the comic may not
# strictly be in STATE_WRITTEN any more (stale rewrite) or because we want to
# bypass the gate (count_updated flag, missing-xml backfill).
_WRITE_FORCE_MODES = {"stale", "missing", "count_updated"}


def _process_write_queue(self, filter_mode):
    """Shared body for every write_*_task. Loops the queryset and calls
    workflow.write for each comic, with cancellation and progress reporting."""
    from apps.core import workflow
    from .task_base import batch_workflow_run

    force = filter_mode in _WRITE_FORCE_MODES
    return batch_workflow_run(
        self, _write_queue_qs(filter_mode),
        process=lambda c: workflow.write(c, force=force),
        count_label="written",
    )


@shared_task(bind=True, base=ProgressTask, name="core.write_all_comics", queue="write")
def write_all_comics_task(self):
    """Write ComicInfo.xml for every comic in 'written' state."""
    return _process_write_queue(self, "all")


@shared_task(bind=True, base=ProgressTask, name="core.write_stale_comics", queue="write")
def write_stale_comics_task(self):
    """Re-write comics whose DB rows changed since the last write (updated_at > last_written)."""
    return _process_write_queue(self, "stale")


@shared_task(bind=True, base=ProgressTask, name="core.write_missing_comics", queue="write")
def write_missing_comics_task(self):
    """Write ComicInfo.xml for digital STATE_WRITTEN comics that have never been written."""
    return _process_write_queue(self, "missing")


@shared_task(bind=True, base=ProgressTask, name="core.rewrite_updated_comics", queue="write")
def rewrite_updated_comics_task(self):
    """Rewrite ComicInfo.xml for digital comics carrying the count_updated flag."""
    return _process_write_queue(self, "count_updated")


# =============================================================================
# Scan / Import tasks
# =============================================================================

@shared_task(bind=True, base=ProgressTask, name="core.scan_untagged", queue="import")
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
        "flagged_missing": result["flagged_missing"],
        "unflagged_missing": result["unflagged_missing"],
        "errors": result.get("errors", []),
        "cancelled": False,
    }


def _convert_comic_to_cbz(comic):
    """Convert a single CBR/CB7 comic to CBZ.

    Repacks the archive into a hidden temp file next to the original (see
    archives.convert_archive_to_cbz), renames that to .cbz, updates the DB
    record, and only then deletes the original. An existing .cbz with the same
    name is a different file and is never adopted or overwritten. A .cbz that
    is really a RAR or 7-Zip archive (file_format cbr/cb7) is replaced in place.

    Returns a dict: {"success": bool, "error": str|None, "fatal": bool, "skipped": bool}.
      - skipped=True: the comic is not a CBR/CB7, so there is nothing to do.
      - fatal=True: a PermissionError or out-of-space error that should stop a batch.
    """
    import os
    import errno as _errno
    from pathlib import Path
    from .archives import convert_archive_to_cbz
    from .audit import log_batch_entry
    from .services import refresh_file_info

    if comic.file_format not in ("cbr", "cb7"):
        return {"success": False, "error": None, "fatal": False, "skipped": True}

    if not comic.file_path or not os.path.exists(comic.file_path):
        return {"success": False, "error": "Source file not found", "fatal": False, "skipped": False}

    original_path = Path(comic.file_path)
    new_path = original_path.with_suffix(".cbz")
    in_place = new_path == original_path

    if not in_place and new_path.exists():
        err_msg = f"A CBZ with the same name already exists: {new_path.name}"
        log_batch_entry("convert_cbr", comic, comic.state, comic.state,
                        {"error": [None, err_msg]})
        return {"success": False, "error": err_msg, "fatal": False, "skipped": False}

    try:
        convert_archive_to_cbz(original_path, new_path)

        old_path_str = comic.file_path
        comic.file_path = str(new_path)
        comic.file_format = "cbz"
        comic.flags.pop("needs_conversion", None)
        comic.flags.pop("corrupted_archive", None)
        try:
            comic.save()
        except Exception:
            # Keep the original as the source of truth if the DB update fails
            if not in_place:
                new_path.unlink()
            raise
        if not in_place:
            original_path.unlink()
        # Page count, size and cover hashes of the new archive
        refresh_file_info(comic)
        log_batch_entry("convert_cbr", comic, comic.state, comic.state,
                        {"path": [old_path_str, str(new_path)]})
        return {"success": True, "error": None, "fatal": False, "skipped": False}

    except Exception as e:
        err_msg = str(e)
        fatal = isinstance(e, PermissionError) or getattr(e, "errno", None) == _errno.ENOSPC
        log_batch_entry("convert_cbr", comic, comic.state, comic.state,
                        {"error": [None, err_msg]})
        return {"success": False, "error": err_msg, "fatal": fatal, "skipped": False}


@shared_task(bind=True, base=ProgressTask, name="core.convert_cbr", queue="import")
def convert_cbr_task(self, comic_id):
    """Convert a single CBR/CB7 file to CBZ, reporting progress for the task toast."""
    from .models import Comic

    self.update_state(
        state="PROGRESS",
        meta={"current": 0, "total": 1, "processed": 0, "errors": []},
    )

    try:
        comic = Comic.objects.get(pk=comic_id)
    except Comic.DoesNotExist:
        return {"converted": 0, "processed": 0, "total": 1,
                "errors": ["Comic not found"], "cancelled": False}

    result = _convert_comic_to_cbz(comic)
    errors = []
    converted = 1 if result["success"] else 0
    if result["skipped"]:
        errors.append(f"{comic.proposed_series} #{comic.proposed_number}: not a CBR/CB7 file")
    elif result["error"]:
        errors.append(f"{comic.proposed_series} #{comic.proposed_number}: {result['error']}")

    self.update_state(
        state="PROGRESS",
        meta={"current": 1, "total": 1, "processed": converted, "errors": errors},
    )
    return {"converted": converted, "processed": converted, "total": 1,
            "errors": errors, "cancelled": False}


@shared_task(bind=True, base=ProgressTask, name="core.convert_all_cbr", queue="import")
def convert_all_cbr_task(self):
    """
    Convert all CBR/CB7 files flagged for conversion to CBZ format.
    """
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
        if self.is_cancelled():
            self.clear_cancel()
            return {"converted": converted, "processed": converted, "total": total, "errors": errors, "cancelled": True}

        try:
            comic = Comic.objects.get(pk=comic_id)
        except Comic.DoesNotExist:
            continue

        result = _convert_comic_to_cbz(comic)
        if result["skipped"]:
            continue
        if result["success"]:
            converted += 1
        elif result["error"]:
            errors.append(f"{comic.proposed_series} #{comic.proposed_number}: {result['error']}")

        self.update_state(
            state="PROGRESS",
            meta={"current": i + 1, "total": total, "processed": converted, "errors": errors},
        )

        if result["fatal"]:
            return {"converted": converted, "processed": converted, "total": total,
                    "errors": errors, "cancelled": False, "stopped_early": True}

    return {"converted": converted, "processed": converted, "total": total, "errors": errors, "cancelled": False}


@shared_task(bind=True, base=ProgressTask, name="core.convert_all_zip", queue="import")
def convert_all_zip_task(self):
    """
    Rename all .zip files flagged with is_zip to .cbz in place.
    ZIP and CBZ are the same format — no extraction needed.
    """
    import os
    from pathlib import Path
    from .models import Comic

    comic_ids = list(
        Comic.objects.filter(flags__is_zip=True).values_list("pk", flat=True)
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
        if self.is_cancelled():
            self.clear_cancel()
            return {"converted": converted, "processed": converted, "total": total, "errors": errors, "cancelled": True}

        try:
            comic = Comic.objects.get(pk=comic_id)
        except Comic.DoesNotExist:
            continue

        if comic.file_format != "zip":
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
            original_path.rename(new_path)
            comic.file_path = str(new_path)
            comic.file_format = "cbz"
            comic.flags.pop("is_zip", None)
            comic.save()
            from .audit import log_batch_entry
            log_batch_entry("convert_zip", comic, comic.state, comic.state,
                            {"file": [str(original_path), str(new_path)]})
            converted += 1
        except (PermissionError, OSError) as e:
            import errno as _errno
            fatal = isinstance(e, PermissionError) or getattr(e, "errno", None) == _errno.ENOSPC
            errors.append(f"{comic.proposed_series} #{comic.proposed_number}: {str(e)}")
            self.update_state(
                state="PROGRESS",
                meta={"current": i + 1, "total": total, "processed": converted, "errors": errors},
            )
            if fatal:
                return {"converted": converted, "processed": converted, "total": total,
                        "errors": errors, "cancelled": False, "stopped_early": True}
        except Exception as e:
            errors.append(f"{comic.proposed_series} #{comic.proposed_number}: {str(e)}")

        self.update_state(
            state="PROGRESS",
            meta={"current": i + 1, "total": total, "processed": converted, "errors": errors},
        )

    return {"converted": converted, "processed": converted, "total": total, "errors": errors, "cancelled": False}


# =============================================================================
# Scrape task
# =============================================================================

@shared_task(bind=True, base=ProgressTask, name="core.scrape_all", queue="scrape")
def scrape_all_task(self):
    """Scrape every comic in 'imported' state.

    Falls back to the ComicVine API when the local comicvine.db is unavailable.
    Stops early if the API budget runs out (API-only mode).
    """
    from .models import Comic, get_setting
    from apps.core import workflow
    from apps.scraper.comicvine import ComicVineScraper
    from apps.scraper.cv_sources import is_cv_db_available, check_api_budget, get_api_calls_remaining

    from django.db.models import Q
    comic_ids = list(
        Comic.objects.filter(
            state=Comic.STATE_IMPORTED,
        ).filter(
            Q(flags__scrape_skipped__isnull=True) | Q(flags__scrape_skipped=False),
        ).exclude(
            custom_values__has_key="scrape_source",
            custom_values__scrape_source="inducks",
        ).values_list("pk", flat=True)
    )
    total = len(comic_ids)

    if total == 0:
        return {"matched": 0, "failed": 0, "total": 0, "errors": [], "cancelled": False}

    db_available = is_cv_db_available()
    batch_insert_covers = get_setting("batch_insert_covers", False)
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
        if self.is_cancelled():
            self.clear_cancel()
            return {
                "matched": matched, "failed": failed,
                "processed": matched + failed,
                "total": total, "errors": errors, "cancelled": True,
            }

        # Stop early if the API budget runs out (API-only mode)
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

        result = workflow.scrape(comic, scraper=scraper, insert_covers=batch_insert_covers)
        if result.success:
            matched += 1
        else:
            failed += 1
            errors.append(f"{comic.series} #{comic.number}: {result.message}")
            if not result.detail.get("matched") is False and result.error:
                # Apply or fetch error: capture detail flag
                comic.flags["scrape_error"] = True
                comic.flags["scrape_error_detail"] = result.error[:300]
                comic.flags.pop("scrape_no_match", None)
                comic.save(update_fields=["flags"])

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

        # Release DB connections every 50 comics to prevent memory growth
        if i % 50 == 0:
            from django.db import reset_queries, close_old_connections
            reset_queries()
            close_old_connections()

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

@shared_task(bind=True, base=ProgressTask, name="core.tag_all", queue="write")
def tag_all_task(self):
    """Apply DataManager rules to every comic in 'tagged' state and advance to 'formatted'."""
    from .models import Comic
    from apps.core import workflow
    from .task_base import batch_workflow_run

    def _tag_and_advance(comic):
        result = workflow.tag(comic, force=True)
        if result.success:
            workflow.advance_state(comic, Comic.STATE_FORMATTED)
        return result

    comic_ids = Comic.objects.filter(state=Comic.STATE_TAGGED).values_list("pk", flat=True)
    return batch_workflow_run(self, comic_ids, process=_tag_and_advance)


@shared_task(bind=True, base=ProgressTask, name="core.retag_flagged", queue="write")
def retag_flagged_task(self, flag_name):
    """Re-tag every comic carrying `flag_name`, regardless of state."""
    from .models import Comic
    from apps.core import workflow
    from .task_base import batch_workflow_run

    comic_ids = Comic.objects.filter(**{f"flags__{flag_name}": True}).values_list("pk", flat=True)
    return batch_workflow_run(
        self, comic_ids,
        process=lambda c: workflow.tag(c, force=True),
    )


@shared_task(bind=True, base=ProgressTask, name="core.format_all", queue="write")
def format_all_task(self):
    """Detect format for every comic in 'formatted' state."""
    from .models import Comic, get_setting
    from apps.core import workflow
    from .task_base import batch_workflow_run

    one_shot_max = get_setting("one_shot_max_count", 1)
    limited_max = get_setting("limited_series_max_count", 15)

    comic_ids = Comic.objects.filter(state=Comic.STATE_FORMATTED).values_list("pk", flat=True)
    return batch_workflow_run(
        self, comic_ids,
        process=lambda c: workflow.format(c, _one_shot_max=one_shot_max, _limited_max=limited_max, force=True),
    )


# =============================================================================
# Organize / Deduplicate tasks
# =============================================================================

@shared_task(bind=True, base=ProgressTask, name="core.organize_all", queue="organize")
def organize_all_task(self):
    """Organize every comic in 'organized' state into the library. Stops early
    on permission denied or out-of-disk-space errors."""
    import errno as _errno
    from .models import Comic
    from apps.core import workflow
    from .task_base import batch_workflow_run

    def _is_fatal(result):
        err = result.error or ""
        return "Permission" in err or f"errno {_errno.ENOSPC}" in err

    comic_ids = Comic.objects.filter(state=Comic.STATE_ORGANIZED).values_list("pk", flat=True)
    return batch_workflow_run(
        self, comic_ids,
        process=lambda c: workflow.organize(c),
        is_fatal=_is_fatal,
    )


@shared_task(bind=True, base=ProgressTask, name="core.deduplicate_all", queue="organize")
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
# Bulk action task (run any action on a filtered set of comics)
# =============================================================================

@shared_task(bind=True, base=ProgressTask, name="core.bulk_action", queue="write")
def bulk_action_task(self, comic_ids, action, flag_name=None):
    """
    Run a workflow action on an explicit list of comic IDs.

    Used by the bulk-action endpoint to run any action on the current
    filtered comic list without requiring a saved SmartList.

    Supported actions: scrape, tag, format, organize, write, force_write, accept_flag, au_reorganize
    """
    from .models import Comic, get_setting
    from apps.core import workflow

    def _run(action_fn, comic, **kwargs):
        result = action_fn(comic, **kwargs)
        if not result.success:
            raise Exception(result.error or result.message)

    batch_insert_covers = get_setting("batch_insert_covers", False)
    total = len(comic_ids)
    if total == 0:
        return {"success": True, "action": action, "processed": 0, "success_count": 0,
                "total": 0, "errors": [], "cancelled": False}

    processed = 0
    success_count = 0
    errors = []

    self.update_state(
        state="PROGRESS",
        meta={"current": 0, "total": total, "action": action, "success_count": 0, "errors": []},
    )

    # Pre-initialize scraper once for scrape action (avoids per-comic overhead)
    scraper = None
    if action == "scrape":
        from apps.scraper.comicvine import ComicVineScraper
        scraper = ComicVineScraper()

    for i, comic_id in enumerate(comic_ids):
        if self.is_cancelled():
            self.clear_cancel()
            return {"success": True, "action": action, "processed": processed,
                    "success_count": success_count, "total": total, "errors": errors,
                    "cancelled": True}

        try:
            comic = Comic.objects.get(pk=comic_id)
        except Comic.DoesNotExist:
            continue

        try:
            if action == "scrape":
                _run(workflow.scrape, comic, scraper=scraper, insert_covers=batch_insert_covers)
            elif action == "tag":
                _run(workflow.tag, comic, force=True)
            elif action == "format":
                _run(workflow.format, comic, force=True)
            elif action == "organize":
                _run(workflow.organize, comic, force=True)
            elif action == "write":
                _run(workflow.write, comic, force=True)
            elif action == "force_write":
                _run(workflow.write, comic, force=True)
            elif action == "au_reorganize":
                _run(workflow.tag, comic, force=True)
                _run(workflow.organize, comic, force=True)
                _run(workflow.write, comic, force=True)
            elif action == "accept_flag" and flag_name:
                comic.accept_flag(flag_name)
                comic.save(update_fields=["flags", "accepted_flags"])
            success_count += 1
        except (PermissionError, OSError) as e:
            import errno as _errno
            fatal = action in ("organize", "write", "force_write", "au_reorganize") and (
                isinstance(e, PermissionError) or getattr(e, "errno", None) == _errno.ENOSPC
            )
            err_msg = str(e)
            errors.append(f"{comic.series} #{comic.number}: {err_msg}")
            if action in ("organize", "write", "force_write", "au_reorganize"):
                from .audit import log_batch_entry
                log_batch_entry(f"{action}_error", comic, comic.state, comic.state,
                                {"error": [None, err_msg]})
            processed += 1
            self.update_state(
                state="PROGRESS",
                meta={"current": i + 1, "total": total, "action": action,
                      "success_count": success_count, "errors": errors},
            )
            if fatal:
                return {"success": True, "action": action, "processed": processed,
                        "success_count": success_count, "total": total, "errors": errors,
                        "cancelled": False, "stopped_early": True}
        except Exception as e:
            errors.append(f"{comic.series} #{comic.number}: {str(e)}")

        processed += 1
        self.update_state(
            state="PROGRESS",
            meta={"current": i + 1, "total": total, "action": action,
                  "success_count": success_count, "errors": errors},
        )

    return {"success": True, "action": action, "processed": processed,
            "success_count": success_count, "total": total, "errors": errors,
            "cancelled": False}


# =============================================================================
# Search alt covers task
# =============================================================================

@shared_task(bind=True, base=ProgressTask, name="core.search_alt_covers", queue="import")
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


@shared_task(bind=True, base=ProgressTask, name="core.audit_metadata", queue="scrape")
def audit_metadata_task(self):
    """
    Background task to audit metadata mismatches between local DB and ComicVine.
    Checks all comics with a ComicVine Volume ID.
    """
    import sqlite3
    from django.conf import settings
    from .models import Comic
    from apps.scraper.cv_sources import is_cv_db_available

    if not is_cv_db_available():
        return {"success": False, "error": "ComicVine database not available."}

    comics_qs = Comic.objects.exclude(
        custom_values__comicvine_volume__isnull=True
    ).exclude(
        custom_values__comicvine_volume=""
    )
    
    comic_ids = list(comics_qs.values_list("pk", flat=True))
    total = len(comic_ids)

    if total == 0:
        return {"success": True, "checked": 0, "flagged": 0, "cleared": 0, "total": 0}

    self.update_state(state="PROGRESS", meta={"current": 0, "total": total, "processed": 0, "errors": []})

    db_path = getattr(settings, "CV_DB_PATH", "/cv_db/comicvine.db")
    try:
        conn = sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)
        cursor = conn.cursor()
    except Exception as e:
        return {"success": False, "error": f"Failed to open CV database: {str(e)}"}

    def _clean(text):
        return "".join(filter(str.isalnum, str(text or ""))).lower()

    flagged = 0
    cleared = 0
    checked = 0
    errors = []

    for i, comic_id in enumerate(comic_ids):
        if is_cancelled(self.request.id):
            conn.close()
            clear_cancel(self.request.id)
            return {
                "success": True, "checked": checked, "flagged": flagged, 
                "cleared": cleared, "total": total, "cancelled": True
            }

        try:
            comic = Comic.objects.get(pk=comic_id)
            vid = comic.custom_values.get("comicvine_volume")
            if not vid:
                continue

            checked += 1
            cursor.execute("SELECT name FROM cv_volume WHERE id = ?", (int(vid),))
            row = cursor.fetchone()
            
            if row:
                cv_name = row[0]
                db_name = comic.series or ""

                # Fuzzy mismatch logic
                clean_cv = _clean(cv_name)
                clean_db = _clean(db_name)

                is_mismatch = clean_cv not in clean_db and clean_db not in clean_cv

                if is_mismatch:
                    if not comic.has_flag("metadata_mismatch"):
                        from .audit import log_batch_entry
                        log_batch_entry(
                            "audit_metadata",
                            comic,
                            comic.state,
                            comic.state,
                            {"metadata_mismatch": [f"Series: {db_name}", f"CV Volume: {cv_name}"]}
                        )
                        comic.add_flag("metadata_mismatch")
                        comic.save(update_fields=["flags"])
                        flagged += 1
                else:
                    if comic.has_flag("metadata_mismatch"):
                        comic.remove_flag("metadata_mismatch")
                        comic.save(update_fields=["flags"])
                        cleared += 1
                        
                        from .audit import log_batch_entry
                        log_batch_entry(
                            "audit_metadata", 
                            comic, 
                            comic.state, 
                            comic.state, 
                            {"metadata_mismatch": ["Flagged", "Cleared"]}
                        )
        except Exception as e:
            errors.append(f"Error checking comic {comic_id}: {str(e)}")

        if (i + 1) % 10 == 0 or (i + 1) == total:
            self.update_state(
                state="PROGRESS",
                meta={
                    "current": i + 1, 
                    "total": total, 
                    "processed": checked,
                    "flagged": flagged,
                    "cleared": cleared,
                    "errors": errors[:10] # Limit reported errors
                }
            )

    conn.close()
    return {
        "success": True,
        "checked": checked,
        "flagged": flagged,
        "cleared": cleared,
        "total": total,
        "errors": errors,
        "cancelled": False
    }


# =============================================================================
# Populate counts task
# =============================================================================

@shared_task(bind=True, base=ProgressTask, name="core.populate_counts", queue="write")
def populate_counts_task(self):
    """
    Populate missing issue counts from CV SQLite DB, then detect count mismatches,
    as a cancellable background task with progress reporting.
    """
    from .models import Comic
    from apps.scraper.cv_sources import is_cv_db_available, fetch_cv_volume_counts

    if not is_cv_db_available():
        return {"success": False, "error": "ComicVine database not available."}

    # Phase 1: Populate missing counts
    comics = list(
        Comic.objects.filter(
            count__isnull=True,
        ).exclude(
            custom_values__comicvine_volume__isnull=True,
        ).exclude(
            custom_values__comicvine_volume="",
        ).exclude(
            custom_values__scrape_source="inducks",
        )
    )

    total = len(comics)
    self.update_state(
        state="PROGRESS",
        meta={"current": 0, "total": total, "phase": "populating", "populated": 0, "failed": 0},
    )

    if total == 0 and not Comic.objects.filter(count__isnull=False).exclude(
        custom_values__comicvine_volume__isnull=True,
    ).exclude(custom_values__comicvine_volume="").exists():
        return {
            "success": True, "populated": 0, "failed": 0,
            "mismatched_volumes": 0, "flagged": 0, "cleared": 0,
            "total": 0, "cancelled": False,
        }

    # Batch query CV DB for count_of_issues
    volume_ids = set()
    for c in comics:
        vid = c.custom_values.get("comicvine_volume")
        if vid:
            volume_ids.add(int(vid))

    volume_counts = fetch_cv_volume_counts(volume_ids)

    populated = 0
    failed = 0

    for i, comic in enumerate(comics):
        if self.is_cancelled():
            self.clear_cancel()
            return {
                "success": True, "populated": populated, "failed": failed,
                "mismatched_volumes": 0, "flagged": 0, "cleared": 0,
                "total": total, "cancelled": True,
            }

        vid = comic.custom_values.get("comicvine_volume")
        if not vid:
            continue

        count = volume_counts.get(int(vid))
        if count is not None:
            comic.count = count
            comic.custom_values["comicvine_issue_count"] = str(count)
            comic.remove_flag("missing_count")
            # Check if count-based format should be upgraded
            if comic.format in Comic.COUNT_BASED_FORMATS and not comic.format_ok:
                one_shot_max = 1
                limited_max = 15
                expected = (
                    "One-Shot" if count <= one_shot_max
                    else "Limited Series" if count <= limited_max
                    else "Main Series"
                )
                if comic.format != expected:
                    comic.needs_reformat = True
            comic.save()
            populated += 1
        else:
            if not comic.is_flag_accepted("missing_count"):
                comic.add_flag("missing_count")
            comic.save()
            failed += 1

        if (i + 1) % 10 == 0 or (i + 1) == total:
            self.update_state(
                state="PROGRESS",
                meta={
                    "current": i + 1, "total": total,
                    "phase": "populating", "populated": populated, "failed": failed,
                },
            )

    # Phase 2: Detect count mismatches
    self.update_state(
        state="PROGRESS",
        meta={
            "current": total, "total": total,
            "phase": "detecting mismatches", "populated": populated, "failed": failed,
        },
    )

    comics_with_volume = Comic.objects.filter(
        count__isnull=False,
    ).exclude(
        custom_values__comicvine_volume__isnull=True,
    ).exclude(
        custom_values__comicvine_volume="",
    ).exclude(
        custom_values__scrape_source="inducks",
    )

    volume_comics = {}
    for comic in comics_with_volume:
        vid = comic.custom_values.get("comicvine_volume")
        if not vid:
            continue
        if vid not in volume_comics:
            volume_comics[vid] = []
        volume_comics[vid].append(comic)

    flagged = 0
    cleared = 0
    mismatched_volumes = 0

    for vid, comics_in_vol in volume_comics.items():
        if self.is_cancelled():
            self.clear_cancel()
            return {
                "success": True, "populated": populated, "failed": failed,
                "mismatched_volumes": mismatched_volumes,
                "flagged": flagged, "cleared": cleared,
                "total": total, "cancelled": True,
            }

        counts = set(c.count for c in comics_in_vol)
        if len(counts) > 1:
            mismatched_volumes += 1
            for comic in comics_in_vol:
                if not comic.has_flag("count_mismatch") and not comic.is_flag_accepted("count_mismatch"):
                    comic.add_flag("count_mismatch")
                    comic.save()
                    flagged += 1
        else:
            for comic in comics_in_vol:
                if comic.has_flag("count_mismatch"):
                    comic.remove_flag("count_mismatch")
                    comic.save()
                    cleared += 1

    return {
        "success": True,
        "populated": populated,
        "failed": failed,
        "mismatched_volumes": mismatched_volumes,
        "flagged": flagged,
        "cleared": cleared,
        "total": total,
        "cancelled": False,
    }


@shared_task(bind=True, base=ProgressTask, name="core.detect_format_upgrades", queue="write")
def detect_format_upgrades_task(self):
    """
    Scan all comics with a count-based format and flag those where the detected
    format differs from the current format. Reports progress via self.update_state().
    """
    from .models import Comic, get_setting
    from .services import detect_format

    # Pre-fetch settings once to avoid N*2 DB queries inside detect_format()
    one_shot_max = get_setting("one_shot_max_count", 1)
    limited_max = get_setting("limited_series_max_count", 15)

    qs = Comic.objects.filter(format__in=Comic.COUNT_BASED_FORMATS, format_ok=False)
    total = qs.count()

    self.update_state(
        state="PROGRESS",
        meta={"current": 0, "total": total, "flagged": 0, "cleared": 0},
    )

    flagged = 0
    cleared = 0
    to_update = []
    CHUNK = 500

    for i, comic in enumerate(qs.iterator(chunk_size=CHUNK)):
        if is_cancelled(self.request.id):
            if to_update:
                Comic.objects.bulk_update(to_update, ["needs_reformat"])
            clear_cancel(self.request.id)
            return {"flagged": flagged, "cleared": cleared, "total": total, "cancelled": True}

        expected = detect_format(comic, _one_shot_max=one_shot_max, _limited_max=limited_max)
        changed = False
        if expected and comic.format != expected:
            if not comic.needs_reformat:
                comic.needs_reformat = True
                flagged += 1
                changed = True
        else:
            if comic.needs_reformat:
                comic.needs_reformat = False
                cleared += 1
                changed = True

        if changed:
            to_update.append(comic)

        if len(to_update) >= CHUNK:
            Comic.objects.bulk_update(to_update, ["needs_reformat"])
            to_update = []

        if i % 100 == 0:
            self.update_state(
                state="PROGRESS",
                meta={"current": i + 1, "total": total, "flagged": flagged, "cleared": cleared},
            )

    if to_update:
        Comic.objects.bulk_update(to_update, ["needs_reformat"])

    return {"flagged": flagged, "cleared": cleared, "total": total, "cancelled": False}
