"""
Workflow pipeline orchestrator.

Defines the canonical sequence of workflow actions for one comic:
    accept -> scrape -> tag -> advance_state(FORMATTED) -> format
    -> run_duplicate_detection -> organize -> write

Each action runs at its declared state gate. The single advance_state call
between tag and format covers the only seam where two consecutive actions do
not share a transition.

The Celery wrapper in apps/dashboard/tasks.py:run_full_pipeline_task loops over
comic IDs, calls run_pipeline_for_comic for each, and reports progress through
the optional progress_cb callback. Keeping the orchestrator in apps/core means
apps/core never has to import from apps/dashboard, and any future entry point
(a sync UI button, a management command) can call the same pipeline without
involving Celery.
"""

from apps.core import workflow
from apps.core.models import get_setting


def run_pipeline_for_comic(comic, *, scraper=None, progress_cb=None) -> dict:
    """Run the full workflow on a single comic. Returns one result dict shaped
    for the run_full_pipeline_task results modal.

    progress_cb(label) is called once per step; ignore the call if you don't
    need progress reporting.

    The pipeline relies on each action's natural state gate. Explicit
    workflow.advance_state hops cover the seams where one action's terminal
    state is not the next action's starting gate. No force flags are used:
    the orchestrator is the canonical path, so the gates are sized to fit it.

    Per-step semantics:
      - accept: silently skipped if the comic is already past STATE_NEW.
      - scrape: failure raises (caught and recorded as outcome=error).
      - tag/format/organize/write: each runs at its declared state gate.
      - dedupe: checks this comic against the library, then short-circuits
        with outcome=duplicate if comic.is_duplicate flips to True.
    """
    from apps.core.models import Comic
    from apps.duplicates.services import run_duplicate_detection_for_comics

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

    def _run(action_result, label):
        if not action_result.success:
            raise Exception(action_result.error or action_result.message)
        return action_result

    try:
        # Step 1: Accept (no-op if already past STATE_NEW)
        _step("Accepting")
        if comic.state == Comic.STATE_NEW:
            _run(workflow.accept(comic), "accept")

        # Step 2: Scrape — only auto-runs from STATE_IMPORTED (natural post-accept state).
        # For re-runs, caller should use the Scrape button first to pick a match manually;
        # any state past STATE_COUNTED is reset to STATE_TAGGED so downstream gates work.
        if comic.state == Comic.STATE_IMPORTED:
            _step("Scraping")
            insert_covers = get_setting("pipeline_insert_covers", False)
            sr = _run(workflow.scrape(comic, scraper=scraper, insert_covers=insert_covers), "scrape")
            result["scrape"] = sr.detail["match"]
        elif comic.state not in (Comic.STATE_COUNTED, Comic.STATE_TAGGED):
            comic.state = Comic.STATE_TAGGED
            comic.save(update_fields=["state"])

        # Count fallback: scrape fills count from the match, but a match without
        # an issue count (or a comic scraped some other way) leaves it null. The
        # phase-by-phase workflow has a "Populate Counts" step for this; mirror
        # it here so pipeline comics don't end up count-null. Single-volume
        # lookup, no global mismatch scan (that stays a separate maintenance op).
        vid = comic.custom_values.get("comicvine_volume")
        if comic.count is None and vid:
            from apps.scraper.cv_sources import fetch_cv_volume_counts
            count = fetch_cv_volume_counts([vid]).get(int(vid))
            if count is not None:
                comic.count = count
                comic.custom_values["comicvine_issue_count"] = str(count)
                comic.save(update_fields=["count", "custom_values"])

        # Step 3: Tag — gate is COUNTED/TAGGED, no advance needed
        _step("Tagging")
        tr = _run(workflow.tag(comic), "tag")
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

        # Bridge: TAGGED -> FORMATTED so format's gate is satisfied
        _run(workflow.advance_state(comic, Comic.STATE_FORMATTED), "advance")

        # Step 4: Format detection — FORMATTED -> DEDUPLICATED
        _step("Detecting format")
        fr = _run(workflow.format(comic), "format")
        result["format"] = dict(fr.detail)

        # Step 5: Deduplicate — check only this comic against the library.
        # The old code ran a full library-wide scan once per comic in the loop;
        # scoping it to this comic does the same work N times less and routes
        # through the same path as the "Deduplicate Selected" button.
        _step("Checking duplicates")
        run_duplicate_detection_for_comics([comic.pk])
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

        # Step 6: Organize — gate is ORGANIZED, run_duplicate_detection advances
        # non-duplicates DEDUPLICATED -> ORGANIZED
        _step("Moving file")
        old_path = comic.file_path
        _run(workflow.organize(comic), "organize")
        result["organize"] = {
            "old_path": old_path,
            "new_path": comic.file_path,
            "moved": old_path != comic.file_path,
        }

        # Step 7: Write ComicInfo.xml — gate is WRITTEN
        _step("Writing ComicInfo.xml")
        _run(workflow.write(comic), "write")

    except Exception as e:
        result["outcome"] = "error"
        result["error"] = str(e)

    return result
