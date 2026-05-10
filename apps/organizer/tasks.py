"""
Celery tasks for Library Organizer operations.
"""

import logging
import os

from celery import shared_task
from apps.core.task_base import ProgressTask

logger = logging.getLogger(__name__)


@shared_task(bind=True, base=ProgressTask, name="organizer.audit_paths", queue="organize")
def audit_paths_task(self):
    """
    Scan all written/done digital comics.
    Compare file_path vs computed target path.
    Flag mismatches with needs_reorganize=True and store expected_path.
    """
    from apps.core.models import Comic

    from .services import preview_organization

    comic_ids = list(
        Comic.objects.filter(
            state__in=[Comic.STATE_WRITTEN, Comic.STATE_DONE],
            medium=Comic.MEDIUM_DIGITAL,
        )
        .exclude(file_path__isnull=True)
        .exclude(file_path="")
        .values_list("pk", flat=True)
    )
    total = len(comic_ids)

    if total == 0:
        return {"scanned": 0, "mismatched": 0, "matched": 0, "total": 0, "errors": []}

    mismatched = 0
    matched = 0
    errors = []

    # Send initial progress so the UI shows the total immediately
    self.update_state(
        state="PROGRESS",
        meta={"current": 0, "total": total, "mismatched": 0, "matched": 0, "errors": []},
    )

    for i, comic_id in enumerate(comic_ids):
        from apps.core.tasks import is_cancelled, clear_cancel
        if is_cancelled(self.request.id):
            clear_cancel(self.request.id)
            return {
                "scanned": i, "mismatched": mismatched, "matched": matched,
                "total": total, "errors": errors, "cancelled": True,
            }

        try:
            comic = Comic.objects.get(pk=comic_id)
        except Comic.DoesNotExist:
            continue

        try:
            preview = preview_organization(comic)
            old_path = comic.file_path
            new_path = preview["new_path"]

            if os.path.abspath(old_path) != os.path.abspath(new_path):
                comic.needs_reorganize = True
                comic.expected_path = new_path
                comic.save(update_fields=["needs_reorganize", "expected_path"])
                mismatched += 1
            else:
                if comic.needs_reorganize:
                    comic.needs_reorganize = False
                    comic.expected_path = None
                    comic.save(update_fields=["needs_reorganize", "expected_path"])
                matched += 1
        except Exception as e:
            errors.append(f"{comic.series} #{comic.number}: {str(e)}")

        self.update_state(
            state="PROGRESS",
            meta={
                "current": i + 1,
                "total": total,
                "mismatched": mismatched,
                "matched": matched,
                "errors": errors,
            },
        )

    return {
        "scanned": total,
        "mismatched": mismatched,
        "matched": matched,
        "total": total,
        "errors": errors,
        "cancelled": False,
    }


@shared_task(bind=True, base=ProgressTask, name="organizer.reorganize_all_flagged", queue="organize")
def reorganize_all_flagged_task(self):
    """
    Re-organize all comics flagged with needs_reorganize=True.
    Moves files to their correct locations.
    """
    from apps.core.models import Comic

    from .services import reorganize_comic

    comic_ids = list(
        Comic.objects.filter(
            needs_reorganize=True,
            medium=Comic.MEDIUM_DIGITAL,
        )
        .exclude(file_path__isnull=True)
        .exclude(file_path="")
        .values_list("pk", flat=True)
    )
    total = len(comic_ids)

    if total == 0:
        return {"moved": 0, "already_ok": 0, "total": 0, "errors": []}

    moved = 0
    already_ok = 0
    errors = []

    # Send initial progress so the UI shows the total immediately
    self.update_state(
        state="PROGRESS",
        meta={"current": 0, "total": total, "moved": 0, "errors": []},
    )

    for i, comic_id in enumerate(comic_ids):
        from apps.core.tasks import is_cancelled, clear_cancel
        if is_cancelled(self.request.id):
            clear_cancel(self.request.id)
            return {"moved": moved, "already_ok": already_ok, "total": total, "errors": errors, "cancelled": True}

        try:
            comic = Comic.objects.get(pk=comic_id)
        except Comic.DoesNotExist:
            continue

        try:
            result = reorganize_comic(comic)
        except (PermissionError, OSError) as e:
            err_msg = str(e)
            errors.append(f"{comic.series} #{comic.number}: {err_msg}")
            self.update_state(
                state="PROGRESS",
                meta={"current": i + 1, "total": total, "moved": moved, "errors": errors},
            )
            return {"moved": moved, "already_ok": already_ok, "total": total,
                    "errors": errors, "cancelled": False, "stopped_early": True}

        if result["success"]:
            if result.get("moved"):
                from apps.core.audit import log_batch_entry
                log_batch_entry(
                    "organize_all", comic, comic.state, comic.state,
                    {"path": [result["old_path"], result["new_path"]]},
                )
                moved += 1
            else:
                already_ok += 1
        else:
            errors.append(
                f"{comic.series} #{comic.number}: {result.get('error', 'Unknown')}"
            )

        self.update_state(
            state="PROGRESS",
            meta={
                "current": i + 1,
                "total": total,
                "moved": moved,
                "errors": errors,
            },
        )

    return {"moved": moved, "already_ok": already_ok, "total": total, "errors": errors, "cancelled": False}
