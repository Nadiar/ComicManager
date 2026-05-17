"""
Celery tasks for Dashboard / Smart List operations.
"""

import logging

from celery import shared_task
from apps.core.task_base import ProgressTask

logger = logging.getLogger(__name__)


@shared_task(bind=True, base=ProgressTask, name="dashboard.smartlist_action", queue="write")
def run_smartlist_action_task(self, smart_list_id, action):
    """
    Run a workflow action on all comics in a Smart List.

    Args:
        smart_list_id: UUID of the SmartList
        action: One of 'tag', 'format', 'organize', 'write'
    """
    from apps.core.models import Comic
    from apps.dashboard.models import SmartList
    from apps.dashboard.services import build_queryset

    smart_list = SmartList.objects.get(pk=smart_list_id)

    # Safety: refuse to run on an unfiltered smart list (prevents accidental operations)
    if not smart_list.filters:
        return {"success": False, "action": action, "processed": 0, "total": 0,
                "errors": ["Smart list has no filters — refusing to run on entire library"]}

    qs = build_queryset(smart_list)
    comic_ids = list(qs.values_list("pk", flat=True))
    total = len(comic_ids)

    if total == 0:
        return {"success": True, "action": action, "processed": 0, "total": 0, "errors": []}

    processed = 0
    success_count = 0
    errors = []

    self.update_state(
        state="PROGRESS",
        meta={"current": 0, "total": total, "action": action, "success_count": 0, "errors": []},
    )

    for i, comic_id in enumerate(comic_ids):
        if self.is_cancelled():
            self.clear_cancel()
            return {
                "success": True, "action": action, "processed": processed,
                "success_count": success_count, "total": total, "errors": errors,
                "cancelled": True,
            }

        try:
            comic = Comic.objects.get(pk=comic_id)
        except Comic.DoesNotExist:
            continue

        try:
            if action == "tag":
                _run_tag(comic)
                success_count += 1
            elif action == "format":
                _run_format(comic)
                success_count += 1
            elif action == "organize":
                _run_organize(comic)
                success_count += 1
            elif action == "write":
                _run_write(comic)
                success_count += 1
        except (PermissionError, OSError) as e:
            import errno as _errno
            is_destructive = action in ("organize", "write")
            fatal = is_destructive and (
                isinstance(e, PermissionError) or getattr(e, "errno", None) == _errno.ENOSPC
            )
            errors.append(f"{comic.series} #{comic.number}: {str(e)}")
            if is_destructive:
                from apps.core.audit import log_batch_entry
                log_batch_entry(f"{action}_error", comic, comic.state, comic.state,
                                {"error": [None, str(e)]})
            processed += 1
            self.update_state(
                state="PROGRESS",
                meta={"current": i + 1, "total": total, "action": action,
                      "success_count": success_count, "errors": errors},
            )
            if fatal:
                return {
                    "success": True, "action": action, "processed": processed,
                    "success_count": success_count, "total": total, "errors": errors,
                    "cancelled": False, "stopped_early": True,
                }
        except Exception as e:
            errors.append(f"{comic.series} #{comic.number}: {str(e)}")
            if action in ("organize", "write"):
                from apps.core.audit import log_batch_entry
                log_batch_entry(f"{action}_error", comic, comic.state, comic.state,
                                {"error": [None, str(e)]})

        processed += 1
        self.update_state(
            state="PROGRESS",
            meta={
                "current": i + 1,
                "total": total,
                "action": action,
                "success_count": success_count,
                "errors": errors,
            },
        )

    return {
        "success": True,
        "action": action,
        "processed": processed,
        "success_count": success_count,
        "total": total,
        "errors": errors,
        "cancelled": False,
    }


def _run_tag(comic):
    """Apply DataManager tagging rules to a comic.

    Returns the dict from `apply_datamanager_rules` (matched_rulesets, matched_count,
    changes, changes_count) so callers can populate UI-result detail without
    re-running the rules.
    """
    from apps.tagging.engine import apply_datamanager_rules
    from apps.core.audit import log_batch_entry, snapshot_fields, diff_fields

    snap = snapshot_fields(comic, ["series_group", "main_character_or_team", "state"])

    try:
        tag_result = apply_datamanager_rules(comic, save=False)
        comic.custom_values["DataManager_Processed"] = "Yes"

        # Clear unknown_publisher if this publisher is now covered by a ruleset
        if comic.publisher and comic.has_flag("unknown_publisher"):
            from apps.tagging.engine import is_publisher_known
            if is_publisher_known(comic.publisher):
                comic.remove_flag("unknown_publisher")

        from apps.core.models import Comic
        if comic.state in (Comic.STATE_NEW, Comic.STATE_IMPORTED, Comic.STATE_SCRAPED, Comic.STATE_COUNTED):
            comic.state = Comic.STATE_TAGGED

        comic.save()
    except Exception as e:
        log_batch_entry("tag_all", comic, snap["state"], comic.state, {"error": [None, str(e)]})
        raise

    log_batch_entry("tag_all", comic, snap["state"], comic.state, diff_fields(comic, snap) or {"processed": [None, True]})
    return tag_result


def _run_format(comic, _one_shot_max=None, _limited_max=None):
    """Detect and set format for a comic.

    Returns the dict from `detect_and_set_format` (old_format, new_format,
    detected_format, format_changed) so callers can populate UI-result detail
    without re-running detection.
    """
    from apps.core.services import detect_and_set_format
    from apps.core.audit import log_batch_entry, snapshot_fields, diff_fields

    snap = snapshot_fields(comic, ["state", "format"])

    try:
        format_result = detect_and_set_format(comic, _one_shot_max=_one_shot_max, _limited_max=_limited_max)
    except Exception as e:
        log_batch_entry("format_all", comic, snap["state"], comic.state, {"error": [None, str(e)]})
        raise

    log_batch_entry("format_all", comic, snap["state"], comic.state, diff_fields(comic, snap) or {"processed": [None, True]})
    return format_result


def _run_organize(comic):
    """Re-organize a comic to its correct library path, regardless of current state."""
    import os
    import shutil
    from apps.core.models import Comic
    from apps.organizer.services import preview_organization, LIBRARY_BASE
    from apps.core.audit import log_batch_entry

    if not comic.is_digital or not comic.file_path:
        return

    if not os.path.exists(comic.file_path):
        raise Exception(f"File not found: {comic.file_path}")

    preview = preview_organization(comic)
    old_path = comic.file_path
    new_path = preview["new_path"]
    state_before = comic.state

    if os.path.abspath(old_path) != os.path.abspath(new_path):
        os.makedirs(os.path.dirname(new_path), exist_ok=True)
        if os.path.exists(new_path):
            raise Exception(f"Destination already exists: {new_path}")
        shutil.move(old_path, new_path)

        # Clean up empty source directories
        try:
            old_dir = os.path.dirname(old_path)
            while old_dir and old_dir != LIBRARY_BASE:
                if os.path.isdir(old_dir) and not os.listdir(old_dir):
                    os.rmdir(old_dir)
                    old_dir = os.path.dirname(old_dir)
                else:
                    break
        except OSError:
            pass

        comic.file_path = new_path
        comic.last_organized_path = new_path

    # Advance state to written from any earlier state
    if comic.state in (Comic.STATE_NEW, Comic.STATE_IMPORTED, Comic.STATE_SCRAPED,
                       Comic.STATE_COUNTED, Comic.STATE_TAGGED, Comic.STATE_FORMATTED,
                       Comic.STATE_DEDUPLICATED, Comic.STATE_ORGANIZED):
        comic.state = Comic.STATE_WRITTEN

    try:
        comic.needs_reorganize = False
        comic.expected_path = None
        comic.save()
    except Exception as e:
        log_batch_entry("organize_all", comic, state_before, comic.state, {"error": [None, str(e)]})
        raise

    changes = {}
    if old_path != comic.file_path:
        changes["path"] = [old_path, comic.file_path]
    log_batch_entry("organize_all", comic, state_before, comic.state, changes or {"processed": [None, True]})


def _run_scrape(comic, scraper=None):
    """Deprecated: use apps.core.workflow.scrape directly.

    Kept as a shim for the brief window between Phase 1 commits. Returns the
    raw match object (or raises) for callers that still rely on the old contract.
    """
    from apps.core import workflow

    result = workflow.scrape(comic, scraper=scraper, insert_covers=False, force=True)
    if not result.success:
        raise Exception(result.error or result.message)
    return result.detail.get("match_obj")



def _run_write(comic):
    """Deprecated: use apps.core.workflow.write directly. Kept as a shim while
    callers are migrated. Raises on failure for back-compat with task callers."""
    from apps.core import workflow

    if not comic.is_digital or not comic.file_path:
        return
    if not comic.file_path.lower().endswith(".cbz"):
        return

    result = workflow.write(comic, force=True)
    if not result.success:
        raise Exception(result.error or result.message)


@shared_task(bind=True, base=ProgressTask, name="dashboard.run_full_pipeline", queue="write")
def run_full_pipeline_task(self, comic_ids: list):
    """
    Run the full import pipeline on a list of comics in STATE_NEW.

    Steps per comic:
      1. Accept (proposed values -> confirmed, STATE_NEW -> STATE_IMPORTED)
      2. Scrape (ComicVine local db or API)
      3. Tag (DataManager rules, STATE_TAGGED)
      4. Advance STATE_TAGGED -> STATE_FORMATTED (mirrors tag_all_task logic)
      5. Format detection (STATE_FORMATTED -> STATE_DEDUPLICATED)
      6. Deduplicate — stops here if comic.is_duplicate is True
      7. Organize (move file, -> STATE_WRITTEN)
      8. Write ComicInfo.xml

    Captures per-step detail (scrape match, tag changes, format patterns, file paths)
    for display in the results modal.
    """
    import re
    from apps.core.models import Comic
    from apps.core.audit import log_batch_entry
    from apps.core.services import OMNIBUS_MIN_PAGES, TPB_MIN_PAGES, TPB_ISSUE_RANGE_RE
    from apps.scraper.comicvine import ComicVineScraper
    from apps.duplicates.services import run_duplicate_detection

    total = len(comic_ids)
    results = []
    errors = []

    self.update_state(
        state="PROGRESS",
        meta={"current": 0, "total": total, "processed": 0, "errors": [], "label": "Running pipeline"},
    )

    scraper = ComicVineScraper()

    for i, comic_id in enumerate(comic_ids):
        if self.is_cancelled():
            self.clear_cancel()
            return {
                "total": total, "processed": i, "results": results,
                "errors": errors, "cancelled": True,
                "success_count": sum(1 for r in results if r["outcome"] == "success"),
                "duplicate_count": sum(1 for r in results if r["outcome"] == "duplicate"),
                "error_count": sum(1 for r in results if r["outcome"] == "error"),
            }

        try:
            comic = Comic.objects.get(pk=comic_id)
        except Comic.DoesNotExist:
            results.append({
                "pk": str(comic_id), "title": "Unknown",
                "outcome": "error", "stopped_at": "load",
                "error": "Comic not found",
                "duplicate_of_pk": None, "duplicate_of_title": None,
                "scrape": None, "tag": None, "format": None, "organize": None,
            })
            errors.append(f"Comic {comic_id}: not found")
            self.update_state(
                state="PROGRESS",
                meta={"current": i + 1, "total": total, "processed": i + 1, "errors": errors},
            )
            continue

        title = (
            f"{comic.proposed_series or comic.series or '?'} "
            f"#{comic.proposed_number or comic.number or '?'}"
        )
        result = {
            "pk": str(comic.pk), "title": title, "outcome": "success",
            "stopped_at": None, "error": None,
            "duplicate_of_pk": None, "duplicate_of_title": None,
            "scrape": None, "tag": None, "format": None, "organize": None,
        }

        if comic.file_format != "cbz":
            result["outcome"] = "error"
            result["error"] = f"Skipped: pipeline only supports CBZ (file is {comic.file_format or 'unknown'})"
            errors.append(f"{title}: not a CBZ file")
            results.append(result)
            self.update_state(
                state="PROGRESS",
                meta={"current": i + 1, "total": total, "processed": i + 1, "errors": errors},
            )
            continue

        def _step(label):
            self.update_state(
                state="PROGRESS",
                meta={"current": i, "total": total, "processed": i, "errors": errors,
                      "step": label, "comic": title},
            )

        try:
            # Step 1: Accept
            _step("Accepting")
            if comic.state == Comic.STATE_NEW:
                comic.series = comic.proposed_series
                comic.number = comic.proposed_number
                comic.volume = comic.proposed_volume
                comic.year = comic.proposed_year
                if comic.file_path and not comic.phash:
                    from apps.scraper.hasher import extract_cover_hashes
                    hashes = extract_cover_hashes(comic.file_path)
                    if hashes:
                        comic.phash = hashes.phash_hex
                        comic.ahash = hashes.ahash_hex
                comic.state = Comic.STATE_IMPORTED
                comic.save()

            # Step 2: Scrape
            _step("Scraping")
            from apps.core import workflow
            scrape_result = workflow.scrape(comic, scraper=scraper, insert_covers=False, force=True)
            if not scrape_result.success:
                result["scrape"] = {"matched": False}
                raise Exception(scrape_result.error or scrape_result.message)
            result["scrape"] = scrape_result.detail["match"]

            # Step 3: Tag
            _step("Tagging")
            tag_result = _run_tag(comic)
            result["tag"] = {
                "matched_rulesets": tag_result["matched_rulesets"],
                "matched_count": tag_result["matched_count"],
                "changes": [
                    {
                        "field": c.get("field", ""),
                        "action": c.get("action", ""),
                        "new_value": str(c.get("new_value", "")),
                    }
                    for c in tag_result["changes"]
                ],
                "changes_count": tag_result["changes_count"],
            }

            # Step 4: Advance TAGGED -> FORMATTED (mirrors tag_all_task inline logic)
            comic.refresh_from_db(fields=["state"])
            if comic.state == Comic.STATE_TAGGED:
                comic.state = Comic.STATE_FORMATTED
                comic.save(update_fields=["state", "updated_at"])
                log_batch_entry(
                    "run_pipeline", comic, Comic.STATE_TAGGED, Comic.STATE_FORMATTED, {}
                )

            # Step 5: Format detection
            _step("Detecting format")
            _text = f"{comic.series or ''} {comic.title or ''}"
            _summary = comic.summary or ""
            _pages = comic.page_count or 0

            format_result = _run_format(comic)
            detected_format = format_result["detected_format"]

            result["format"] = {
                "old_format": format_result["old_format"],
                "new_format": format_result["new_format"],
                "detected_format": detected_format,
                "format_changed": format_result["format_changed"],
                "series": comic.series,
                "title": comic.title,
                "count": comic.count,
                "page_count": _pages,
                "patterns_checked": [
                    {"pattern": "Director's Cut (text)",
                     "matched": detected_format == "Director's Cut"},
                    {"pattern": "Black & White (text)",
                     "matched": detected_format == "Black & White"},
                    {"pattern": "Omnibus (keyword in title/summary)",
                     "matched": detected_format == "Omnibus" and bool(
                         re.search(r"\bOmnibus\b", _text + " " + _summary, re.IGNORECASE))},
                    {"pattern": f"Omnibus (≥{OMNIBUS_MIN_PAGES} pages, no TPB signals)",
                     "matched": detected_format == "Omnibus" and _pages >= OMNIBUS_MIN_PAGES and not
                         re.search(r"\bOmnibus\b", _text + " " + _summary, re.IGNORECASE)},
                    {"pattern": "TPB (keyword)",
                     "matched": detected_format == "TPB" and bool(
                         re.search(r"\bTPB\b|\bTrade Paperback\b", _text, re.IGNORECASE))},
                    {"pattern": f"TPB (≥{TPB_MIN_PAGES} pages + issue range in summary)",
                     "matched": detected_format == "TPB" and _pages >= TPB_MIN_PAGES and bool(
                         TPB_ISSUE_RANGE_RE.search(_summary))},
                    {"pattern": "Annual (keyword)",
                     "matched": detected_format == "Annual"},
                    {"pattern": "One-Shot (count=1)",
                     "matched": detected_format == "One-Shot"},
                    {"pattern": "Limited Series (count 2-15)",
                     "matched": detected_format == "Limited Series"},
                    {"pattern": "Main Series (count>15)",
                     "matched": detected_format == "Main Series"},
                ],
            }

            # Step 6: Deduplicate
            _step("Checking duplicates")
            run_duplicate_detection()
            comic.refresh_from_db()

            if comic.is_duplicate:
                dup = comic.duplicate_of
                result["outcome"] = "duplicate"
                result["stopped_at"] = "deduplicate"
                result["duplicate_of_pk"] = str(dup.pk) if dup else None
                result["duplicate_of_title"] = (
                    f"{dup.series} #{dup.number}" if dup else "Unknown"
                )
                results.append(result)
                errors.append(f"{title}: duplicate of {result['duplicate_of_title']}")
                self.update_state(
                    state="PROGRESS",
                    meta={"current": i + 1, "total": total, "processed": i + 1, "errors": errors},
                )
                continue

            # Step 7: Organize — capture old path before moving
            _step("Moving file")
            old_path = comic.file_path
            _run_organize(comic)
            comic.refresh_from_db(fields=["file_path"])
            result["organize"] = {
                "old_path": old_path,
                "new_path": comic.file_path,
                "moved": old_path != comic.file_path,
            }

            # Step 8: Write ComicInfo.xml
            _step("Writing ComicInfo.xml")
            _run_write(comic)

        except Exception as e:
            result["outcome"] = "error"
            result["error"] = str(e)
            errors.append(f"{title}: {str(e)}")

        results.append(result)
        self.update_state(
            state="PROGRESS",
            meta={"current": i + 1, "total": total, "processed": i + 1, "errors": errors},
        )

    return {
        "total": total,
        "processed": len(results),
        "success_count": sum(1 for r in results if r["outcome"] == "success"),
        "duplicate_count": sum(1 for r in results if r["outcome"] == "duplicate"),
        "error_count": sum(1 for r in results if r["outcome"] == "error"),
        "results": results,
        "errors": errors,
        "cancelled": False,
    }
