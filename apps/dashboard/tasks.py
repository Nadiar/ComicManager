"""
Celery tasks for Dashboard / Smart List operations.
"""

import logging

from celery import shared_task
from apps.core.task_base import ProgressTask

logger = logging.getLogger(__name__)


@shared_task(bind=True, base=ProgressTask, name="dashboard.smartlist_action", queue="write")
def run_smartlist_action_task(self, smart_list_id, action, comic_ids=None):
    """Run a workflow action on every comic in a Smart List, or on comic_ids if provided.

    `action` is one of 'tag', 'format', 'organize', 'write'. Comics whose
    state-gate prevents the action (returned as `result.skipped`) are silently
    counted as processed-but-not-success. Permission and out-of-disk errors on
    organize/write stop the loop early.
    """
    from apps.core.models import Comic  # noqa: F401  (used by batch_workflow_run import)
    from apps.core import workflow
    from apps.core.task_base import batch_workflow_run
    from apps.dashboard.models import SmartList
    from apps.dashboard.services import build_queryset

    smart_list = SmartList.objects.get(pk=smart_list_id)

    action_fns = {
        "tag":      lambda c: workflow.tag(c, force=True),
        "format":   lambda c: workflow.format(c, force=True),
        "organize": lambda c: workflow.organize(c, force=True),
        "write":    lambda c: workflow.write(c, force=True),
    }
    if action not in action_fns:
        return {"success": False, "action": action, "processed": 0, "total": 0,
                "errors": [f"Unsupported smartlist action: {action}"]}

    def _is_fatal(result):
        if action not in ("organize", "write"):
            return False
        err = result.error or ""
        return "Permission" in err or "errno 28" in err  # ENOSPC = 28

    if comic_ids is not None:
        qs = Comic.objects.filter(pk__in=comic_ids).values_list("pk", flat=True)
    else:
        if not smart_list.filters:
            return {
                "success": False, "action": action, "processed": 0, "total": 0,
                "errors": ["Smart list has no filters — refusing to run on entire library"],
            }
        qs = build_queryset(smart_list).values_list("pk", flat=True)

    base = batch_workflow_run(
        self, qs,
        process=action_fns[action],
        count_label="success_count",
        is_fatal=_is_fatal,
        extra_meta={"action": action},
    )

    return {
        "success": True,
        "action": action,
        "processed": base["total"],
        "success_count": base["success_count"],
        "total": base["total"],
        "errors": base["errors"],
        "cancelled": base.get("cancelled", False),
        **({"stopped_early": True} if base.get("stopped_early") else {}),
    }


@shared_task(bind=True, base=ProgressTask, name="dashboard.run_full_pipeline", queue="write")
def run_full_pipeline_task(self, comic_ids: list):
    """Celery wrapper around apps.core.pipeline.run_pipeline_for_comic.

    Handles cancellation, scraper init (one ComicVineScraper for the whole batch),
    progress reporting, and result aggregation. The per-comic logic lives in
    apps.core.pipeline so it stays testable in isolation and can be reused outside
    Celery.
    """
    from apps.core.models import Comic
    from apps.core.pipeline import run_pipeline_for_comic
    from apps.scraper.comicvine import ComicVineScraper

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

        def _push_step(label, _i=i, _title=title):
            self.update_state(
                state="PROGRESS",
                meta={"current": _i, "total": total, "processed": _i, "errors": errors,
                      "step": label, "comic": _title},
            )

        result = run_pipeline_for_comic(comic, scraper=scraper, progress_cb=_push_step)
        if result["outcome"] == "error" and result["error"]:
            errors.append(f"{title}: {result['error']}")
        elif result["outcome"] == "duplicate":
            errors.append(f"{title}: duplicate of {result['duplicate_of_title']}")

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
