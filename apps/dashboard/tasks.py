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
        from apps.core.tasks import is_cancelled, clear_cancel
        if is_cancelled(self.request.id):
            clear_cancel(self.request.id)
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
    """Apply DataManager tagging rules to a comic."""
    from apps.tagging.engine import apply_datamanager_rules
    from apps.core.audit import log_batch_entry

    before_series_group = comic.series_group
    before_main_char = comic.main_character_or_team

    apply_datamanager_rules(comic, save=False)
    comic.custom_values["DataManager_Processed"] = "Yes"

    # Clear unknown_publisher if this publisher is now covered by a ruleset
    if comic.publisher and comic.has_flag("unknown_publisher"):
        from apps.tagging.engine import is_publisher_known
        if is_publisher_known(comic.publisher):
            comic.remove_flag("unknown_publisher")

    from apps.core.models import Comic
    state_before = comic.state
    if comic.state in (Comic.STATE_NEW, Comic.STATE_IMPORTED, Comic.STATE_SCRAPED, Comic.STATE_COUNTED):
        comic.state = Comic.STATE_TAGGED

    comic.save()

    changes = {}
    if comic.series_group != before_series_group:
        changes["series_group"] = [before_series_group, comic.series_group]
    if comic.main_character_or_team != before_main_char:
        changes["main_character_or_team"] = [before_main_char, comic.main_character_or_team]
    if comic.state != state_before:
        changes["state"] = [state_before, comic.state]

    log_batch_entry("tag_all", comic, state_before, comic.state, changes)


def _run_format(comic):
    """Detect and set format for a comic."""
    from apps.core.services import detect_and_set_format
    from apps.core.audit import log_batch_entry

    state_before = comic.state
    result = detect_and_set_format(comic)

    changes = {}
    if result["format_changed"]:
        changes["format"] = [result["old_format"], result["new_format"]]
    if comic.state != state_before:
        changes["state"] = [state_before, comic.state]

    log_batch_entry("format_all", comic, state_before, comic.state, changes)


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

    comic.needs_reorganize = False
    comic.expected_path = None
    comic.save()

    changes = {}
    if old_path != comic.file_path:
        changes["path"] = [old_path, comic.file_path]
    log_batch_entry("organize_all", comic, state_before, comic.state, changes)


def _run_scrape(comic, scraper=None):
    """Scrape a comic against ComicVine or Inducks. Creates a scraper if not provided."""
    from apps.scraper.services import find_best_match, apply_cv_match
    from apps.scraper.comicvine import ComicVineScraper

    if scraper is None:
        scraper = ComicVineScraper()

    for key in ("scrape_no_match", "scrape_error", "scrape_error_detail"):
        comic.flags.pop(key, None)

    match = find_best_match(comic, scraper)
    if match:
        apply_cv_match(comic, match, scraper, insert_covers=False)
    else:
        comic.add_flag("scrape_no_match")
        comic.save(update_fields=["flags"])
        raise Exception(f"No match found for {comic.series} #{comic.number}")


def _run_force_write(comic):
    """Force-write ComicInfo.xml regardless of current state."""
    from apps.core.models import Comic
    from apps.core.utils import write_comicinfo_xml
    from django.db.models import F

    if not comic.is_digital or not comic.file_path:
        return
    if not comic.file_path.lower().endswith(".cbz"):
        return

    success = write_comicinfo_xml(comic.file_path, comic)
    if not success:
        raise Exception("Failed to write ComicInfo.xml")

    if comic.state != Comic.STATE_WRITTEN:
        comic.state = Comic.STATE_WRITTEN
    if comic.flags.get("count_updated"):
        comic.flags.pop("count_updated", None)
    comic.save()
    Comic.objects.filter(pk=comic.pk).update(last_written=F("updated_at"))


def _run_write(comic):
    """Write ComicInfo.xml to a comic's CBZ file."""
    from apps.core.models import Comic
    from apps.core.utils import write_comicinfo_xml
    from apps.core.audit import log_batch_entry
    from django.utils import timezone

    if not comic.is_digital or not comic.file_path:
        return

    if not comic.file_path.lower().endswith(".cbz"):
        return

    state_before = comic.state
    success = write_comicinfo_xml(comic.file_path, comic)
    if not success:
        raise Exception("Failed to write ComicInfo.xml")

    from django.db.models import F
    if comic.state != Comic.STATE_WRITTEN:
        comic.state = Comic.STATE_WRITTEN

    if comic.flags.get("count_updated"):
        comic.flags.pop("count_updated", None)

    comic.save()
    # Sync last_written to updated_at so the comic is not immediately stale
    Comic.objects.filter(pk=comic.pk).update(last_written=F("updated_at"))
    log_batch_entry("write_all", comic, state_before, comic.state, {"comicinfo": ["pending", "written"]})


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
    from apps.core.services import detect_format, OMNIBUS_MIN_PAGES, TPB_MIN_PAGES, TPB_ISSUE_RANGE_RE
    from apps.scraper.comicvine import ComicVineScraper
    from apps.scraper.services import find_best_match, apply_cv_match
    from apps.tagging.engine import apply_datamanager_rules, is_publisher_known
    from apps.duplicates.services import run_duplicate_detection

    total = len(comic_ids)
    results = []
    errors = []

    self.update_state(
        state="PROGRESS",
        meta={"current": 0, "total": total, "processed": 0, "errors": []},
    )

    scraper = ComicVineScraper()

    for i, comic_id in enumerate(comic_ids):
        from apps.core.tasks import is_cancelled, clear_cancel
        if is_cancelled(self.request.id):
            clear_cancel(self.request.id)
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

            # Step 2: Scrape — inline to capture match detail
            _step("Scraping")
            for key in ("scrape_no_match", "scrape_error", "scrape_error_detail"):
                comic.flags.pop(key, None)

            match = find_best_match(comic, scraper)
            if match:
                apply_cv_match(comic, match, scraper, insert_covers=False)
                result["scrape"] = {
                    "matched": True,
                    "match_type": getattr(match, "match_type", ""),
                    "series": match.series,
                    "number": match.issue_number,
                    "title": match.title,
                    "publisher": match.publisher,
                    "issue_id": match.issue_id,
                    "cv_cover_url": getattr(match, "cover_url", None),
                }
            else:
                comic.add_flag("scrape_no_match")
                comic.save(update_fields=["flags"])
                result["scrape"] = {"matched": False}
                raise Exception(f"No CV match found for {comic.series} #{comic.number}")

            # Step 3: Tag — inline to capture rule changes
            _step("Tagging")
            before_series_group = comic.series_group
            before_main_char = comic.main_character_or_team

            tag_result = apply_datamanager_rules(comic, save=False)
            comic.custom_values["DataManager_Processed"] = "Yes"

            if comic.publisher and comic.has_flag("unknown_publisher"):
                if is_publisher_known(comic.publisher):
                    comic.remove_flag("unknown_publisher")

            state_before_tag = comic.state
            if comic.state in (
                Comic.STATE_NEW, Comic.STATE_IMPORTED,
                Comic.STATE_SCRAPED, Comic.STATE_COUNTED,
            ):
                comic.state = Comic.STATE_TAGGED

            comic.save()

            audit_changes = {}
            if comic.series_group != before_series_group:
                audit_changes["series_group"] = [before_series_group, comic.series_group]
            if comic.main_character_or_team != before_main_char:
                audit_changes["main_character_or_team"] = [before_main_char, comic.main_character_or_team]
            if comic.state != state_before_tag:
                audit_changes["state"] = [state_before_tag, comic.state]
            log_batch_entry("run_pipeline", comic, state_before_tag, comic.state, audit_changes)

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

            # Step 5: Format detection — capture detail, then run _run_format
            _step("Detecting format")
            old_format = comic.format
            detected_format = detect_format(comic)
            _text = f"{comic.series or ''} {comic.title or ''}"
            _summary = comic.summary or ""
            _pages = comic.page_count or 0

            _run_format(comic)

            result["format"] = {
                "old_format": old_format,
                "new_format": comic.format,
                "detected_format": detected_format,
                "format_changed": old_format != comic.format,
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
