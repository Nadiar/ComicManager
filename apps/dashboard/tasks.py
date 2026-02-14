"""
Celery tasks for Dashboard / Smart List operations.
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="dashboard.smartlist_action", queue="write")
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
        except Exception as e:
            errors.append(f"{comic.series} #{comic.number}: {str(e)}")

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
    }


def _run_tag(comic):
    """Apply DataManager tagging rules to a comic."""
    from apps.tagging.engine import apply_datamanager_rules

    apply_datamanager_rules(comic, save=False)
    comic.custom_values["DataManager_Processed"] = "Yes"

    from apps.core.models import Comic
    if comic.state in (Comic.STATE_NEW, Comic.STATE_IMPORTED, Comic.STATE_SCRAPED, Comic.STATE_COUNTED):
        comic.state = Comic.STATE_TAGGED

    comic.save()


def _run_format(comic):
    """Detect and set format for a comic."""
    from apps.core.services import detect_and_set_format
    detect_and_set_format(comic)


def _run_organize(comic):
    """Re-organize a comic to its correct library path, regardless of current state."""
    import os
    import shutil
    from apps.core.models import Comic
    from apps.organizer.services import preview_organization, LIBRARY_BASE

    if not comic.is_digital or not comic.file_path:
        return

    if not os.path.exists(comic.file_path):
        raise Exception(f"File not found: {comic.file_path}")

    preview = preview_organization(comic)
    old_path = comic.file_path
    new_path = preview["new_path"]

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

    # Advance state to organized from any earlier state
    if comic.state in (Comic.STATE_NEW, Comic.STATE_IMPORTED, Comic.STATE_SCRAPED,
                       Comic.STATE_COUNTED, Comic.STATE_TAGGED, Comic.STATE_FORMATTED,
                       Comic.STATE_DEDUPLICATED):
        comic.state = Comic.STATE_ORGANIZED

    comic.needs_reorganize = False
    comic.expected_path = None
    comic.save()


def _run_write(comic):
    """Write ComicInfo.xml to a comic's CBZ file."""
    from apps.core.models import Comic
    from apps.core.utils import write_comicinfo_xml
    from django.utils import timezone

    if not comic.is_digital or not comic.file_path:
        return

    if not comic.file_path.lower().endswith(".cbz"):
        return

    success = write_comicinfo_xml(comic.file_path, comic)
    if not success:
        raise Exception("Failed to write ComicInfo.xml")

    if comic.state != Comic.STATE_WRITTEN:
        comic.state = Comic.STATE_WRITTEN

    comic.last_written = timezone.now()

    if comic.flags.get("count_updated"):
        comic.flags.pop("count_updated", None)

    comic.save()
