"""
Celery tasks for long-running core operations.
"""

from celery import shared_task
from django.utils import timezone


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
                from .audit import log_batch_entry
                log_batch_entry("write_error", comic, Comic.STATE_ORGANIZED, Comic.STATE_ORGANIZED,
                                {"error": [None, "Failed to write ComicInfo.xml"]})
                self.update_state(
                    state="PROGRESS",
                    meta={"current": i + 1, "total": total, "written": written, "errors": errors},
                )
                continue

        from django.db.models import F
        comic.state = Comic.STATE_WRITTEN
        if comic.flags.get("count_updated"):
            comic.flags.pop("count_updated", None)
        comic.save()
        # Sync last_written to updated_at so the comic is not immediately stale
        Comic.objects.filter(pk=comic.pk).update(last_written=F("updated_at"))
        written += 1

        from .audit import log_batch_entry
        log_batch_entry("write_all", comic, Comic.STATE_ORGANIZED, comic.state, {"comicinfo": ["pending", "written"]})

        self.update_state(
            state="PROGRESS",
            meta={"current": i + 1, "total": total, "written": written, "errors": errors},
        )

    return {"written": written, "total": total, "errors": errors, "cancelled": False}


@shared_task(bind=True, name="core.write_stale_comics", queue="write")
def write_stale_comics_task(self):
    """
    Write ComicInfo.xml for all comics in 'written' state where the DB has
    been updated since the last write (updated_at > last_written).
    Reports progress via self.update_state().
    """
    from .models import Comic
    from .utils import write_comicinfo_xml
    from django.db.models import F

    comic_ids = list(
        Comic.objects.filter(
            state=Comic.STATE_WRITTEN,
            last_written__isnull=False,
        ).filter(
            updated_at__gt=F("last_written")
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

        if comic.is_digital and comic.file_path and comic.file_path.lower().endswith(".cbz"):
            success = write_comicinfo_xml(comic.file_path, comic)
            if not success:
                errors.append(f"{comic.series} #{comic.number}: Failed to write XML")
                from .audit import log_batch_entry
                log_batch_entry("write_error", comic, Comic.STATE_WRITTEN, Comic.STATE_WRITTEN,
                                {"error": [None, "Failed to write ComicInfo.xml"]})
                self.update_state(
                    state="PROGRESS",
                    meta={"current": i + 1, "total": total, "written": written, "errors": errors},
                )
                continue

        comic.save()
        Comic.objects.filter(pk=comic.pk).update(last_written=F("updated_at"))
        written += 1

        from .audit import log_batch_entry
        log_batch_entry("write_all", comic, Comic.STATE_WRITTEN, comic.state, {"comicinfo": ["stale", "written"]})

        self.update_state(
            state="PROGRESS",
            meta={"current": i + 1, "total": total, "written": written, "errors": errors},
        )

    return {"written": written, "total": total, "errors": errors, "cancelled": False}


@shared_task(bind=True, name="core.write_missing_comics", queue="write")
def write_missing_comics_task(self):
    """
    Write ComicInfo.xml for digital comics in 'written' state that have never
    had ComicInfo.xml written (last_written is null).
    """
    from .models import Comic
    from .utils import write_comicinfo_xml
    from django.db.models import F

    comic_ids = list(
        Comic.objects.filter(
            state=Comic.STATE_WRITTEN,
            medium=Comic.MEDIUM_DIGITAL,
            last_written__isnull=True,
        ).order_by("series", "number").values_list("pk", flat=True)
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
                from .audit import log_batch_entry
                log_batch_entry("write_error", comic, Comic.STATE_WRITTEN, Comic.STATE_WRITTEN,
                                {"error": [None, "Failed to write ComicInfo.xml"]})
                self.update_state(
                    state="PROGRESS",
                    meta={"current": i + 1, "total": total, "written": written, "errors": errors},
                )
                continue

        comic.save()
        Comic.objects.filter(pk=comic.pk).update(last_written=F("updated_at"))
        written += 1

        from .audit import log_batch_entry
        log_batch_entry("write_all", comic, Comic.STATE_WRITTEN, comic.state, {"comicinfo": ["missing", "written"]})

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
        ).exclude(
            flags__scrape_skipped=True,
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
                apply_cv_match(comic, match, scraper, insert_covers=False)
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

        # Release DB connections and clear query log every 50 comics to
        # prevent memory accumulation in long-running Celery tasks.
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


@shared_task(bind=True, name="core.retag_flagged", queue="write")
def retag_flagged_task(self, flag_name):
    """
    Re-tag all comics that have a specific flag (e.g. unknown_publisher).
    Uses force-tag logic: applies rules regardless of current state.
    """
    from .models import Comic
    from apps.dashboard.tasks import _run_tag

    comic_ids = list(
        Comic.objects.filter(**{f"flags__{flag_name}": True})
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
            from .audit import log_batch_entry
            log_batch_entry("organize_error", comic, comic.state, comic.state,
                            {"error": [None, str(e)]})

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


@shared_task(bind=True, name="core.audit_metadata", queue="scrape")
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

@shared_task(bind=True, name="core.populate_counts", queue="write")
def populate_counts_task(self):
    """
    Populate missing issue counts from CV SQLite DB, then detect count mismatches.
    Wraps the synchronous _populate_missing_counts() and _detect_count_mismatches()
    helpers into a cancellable background task with progress reporting.
    """
    from .models import Comic
    from apps.scraper.cv_sources import is_cv_db_available
    import sqlite3
    from django.conf import settings

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

    db_path = getattr(settings, "CV_DB_PATH", "/cv_db/comicvine.db")
    volume_counts = {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)
        cursor = conn.cursor()
        volume_id_list = list(volume_ids)
        for i in range(0, len(volume_id_list), 500):
            chunk = volume_id_list[i:i + 500]
            placeholders = ",".join("?" * len(chunk))
            cursor.execute(
                f"SELECT id, count_of_issues FROM cv_volume WHERE id IN ({placeholders})",
                chunk,
            )
            for row in cursor.fetchall():
                if row[1] is not None:
                    volume_counts[row[0]] = row[1]
        conn.close()
    except Exception:
        return {"success": False, "error": "Failed to query ComicVine database."}

    populated = 0
    failed = 0

    for i, comic in enumerate(comics):
        if is_cancelled(self.request.id):
            clear_cancel(self.request.id)
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
        if is_cancelled(self.request.id):
            clear_cancel(self.request.id)
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
