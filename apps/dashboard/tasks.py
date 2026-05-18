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
    from apps.core import workflow
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
                _ar = workflow.tag(comic, advance_to_formatted=True, force=True)
            elif action == "format":
                _ar = workflow.format(comic, force=True)
            elif action == "organize":
                _ar = workflow.organize(comic, force=True)
            elif action == "write":
                _ar = workflow.write(comic, force=True)
            else:
                continue
            if not _ar.success:
                raise Exception(_ar.error or _ar.message)
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


@shared_task(bind=True, base=ProgressTask, name="dashboard.run_full_pipeline", queue="write")
def run_full_pipeline_task(self, comic_ids: list):
    """
    Run the full import pipeline on a list of comics in STATE_NEW.

    Steps per comic, all delegated to apps.core.workflow.* functions:
      1. Accept (proposed values -> confirmed, STATE_NEW -> STATE_IMPORTED)
      2. Scrape (ComicVine local db or API)
      3. Tag (DataManager rules, advance to STATE_FORMATTED in one shot)
      4. Format detection
      5. Deduplicate (stops here if comic.is_duplicate is True)
      6. Organize (move file, advance to STATE_WRITTEN)
      7. Write ComicInfo.xml

    Captures per-step detail (scrape match, tag changes, format patterns, file paths)
    for display in the results modal.
    """
    from apps.core.models import Comic
    from apps.core import workflow
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
                accept_result = workflow.accept(comic)
                if not accept_result.success:
                    raise Exception(accept_result.error or accept_result.message)

            # Step 2: Scrape
            _step("Scraping")
            scrape_result = workflow.scrape(comic, scraper=scraper, insert_covers=False, force=True)
            if not scrape_result.success:
                result["scrape"] = {"matched": False}
                raise Exception(scrape_result.error or scrape_result.message)
            result["scrape"] = scrape_result.detail["match"]

            # Step 3: Tag (also advances TAGGED -> FORMATTED)
            _step("Tagging")
            tag_action = workflow.tag(comic, advance_to_formatted=True, force=True)
            if not tag_action.success:
                raise Exception(tag_action.error or tag_action.message)
            tag_result = tag_action.detail
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

            # Step 4: Format detection
            _step("Detecting format")
            format_action = workflow.format(comic, force=True)
            if not format_action.success:
                raise Exception(format_action.error or format_action.message)
            result["format"] = dict(format_action.detail)

            # Step 5: Deduplicate
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

            # Step 6: Organize
            _step("Moving file")
            old_path = comic.file_path
            org_action = workflow.organize(comic, force=True)
            if not org_action.success:
                raise Exception(org_action.error or org_action.message)
            result["organize"] = {
                "old_path": old_path,
                "new_path": comic.file_path,
                "moved": old_path != comic.file_path,
            }

            # Step 7: Write ComicInfo.xml
            _step("Writing ComicInfo.xml")
            write_action = workflow.write(comic, force=True)
            if not write_action.success:
                raise Exception(write_action.error or write_action.message)

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
