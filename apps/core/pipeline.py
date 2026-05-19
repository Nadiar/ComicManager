"""
Workflow pipeline orchestrator.

Defines the canonical sequence of workflow actions for one comic:
    accept -> scrape -> tag(advance_to_formatted=True) -> format
    -> run_duplicate_detection -> organize(force=True) -> write(force=True)

The Celery wrapper in apps/dashboard/tasks.py:run_full_pipeline_task loops over
comic IDs, calls run_pipeline_for_comic for each, and reports progress through
the optional progress_cb callback.

Keeping the orchestrator out of apps/dashboard/tasks.py means apps/core never
has to import from apps/dashboard, and any future entry point (a sync UI button,
a management command) can call the same pipeline without involving Celery.
"""

from apps.core import workflow


def run_pipeline_for_comic(comic, *, scraper=None, progress_cb=None) -> dict:
    """Run the full workflow on a single comic. Returns one result dict shaped
    for the run_full_pipeline_task results modal.

    progress_cb(label) is called once per step; ignore the call if you don't
    need progress reporting.

    Per-step semantics:
      - accept: skipped silently if comic is not in STATE_NEW.
      - scrape: failure raises (caught and recorded as outcome=error).
      - tag/format/organize/write: each forced; failure raises.
      - dedupe: runs the global detection, then short-circuits with
        outcome=duplicate if comic.is_duplicate flips to True.
    """
    from apps.core.models import Comic
    from apps.duplicates.services import run_duplicate_detection

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
        result["error"] = (
            f"Skipped: pipeline only supports CBZ "
            f"(file is {comic.file_format or 'unknown'})"
        )
        return result

    def _step(label):
        if progress_cb:
            progress_cb(label)

    try:
        # Step 1: Accept (no-op if already past STATE_NEW)
        _step("Accepting")
        if comic.state == Comic.STATE_NEW:
            ar = workflow.accept(comic)
            if not ar.success:
                raise Exception(ar.error or ar.message)

        # Step 2: Scrape
        _step("Scraping")
        sr = workflow.scrape(comic, scraper=scraper, insert_covers=False, force=True)
        if not sr.success:
            result["scrape"] = {"matched": False}
            raise Exception(sr.error or sr.message)
        result["scrape"] = sr.detail["match"]

        # Step 3: Tag (also advances TAGGED -> FORMATTED)
        _step("Tagging")
        tr = workflow.tag(comic, advance_to_formatted=True, force=True)
        if not tr.success:
            raise Exception(tr.error or tr.message)
        td = tr.detail
        result["tag"] = {
            "matched_rulesets": td["matched_rulesets"],
            "matched_count": td["matched_count"],
            "changes": [
                {
                    "field": c.get("field", ""),
                    "action": c.get("action", ""),
                    "new_value": str(c.get("new_value", "")),
                }
                for c in td["changes"]
            ],
            "changes_count": td["changes_count"],
        }

        # Step 4: Format detection
        _step("Detecting format")
        fr = workflow.format(comic, force=True)
        if not fr.success:
            raise Exception(fr.error or fr.message)
        result["format"] = dict(fr.detail)

        # Step 5: Deduplicate (global pass; check this comic's outcome after)
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
            return result

        # Step 6: Organize
        _step("Moving file")
        old_path = comic.file_path
        org = workflow.organize(comic, force=True)
        if not org.success:
            raise Exception(org.error or org.message)
        result["organize"] = {
            "old_path": old_path,
            "new_path": comic.file_path,
            "moved": old_path != comic.file_path,
        }

        # Step 7: Write ComicInfo.xml
        _step("Writing ComicInfo.xml")
        wr = workflow.write(comic, force=True)
        if not wr.success:
            raise Exception(wr.error or wr.message)

    except Exception as e:
        result["outcome"] = "error"
        result["error"] = str(e)

    return result
