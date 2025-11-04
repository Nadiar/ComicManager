"""
Celery tasks for long-running core operations.
"""

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


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
        return {"written": 0, "total": 0, "errors": []}

    written = 0
    errors = []

    for i, comic_id in enumerate(comic_ids):
        try:
            comic = Comic.objects.get(pk=comic_id)
        except Comic.DoesNotExist:
            continue

        if comic.is_digital and comic.file_path and comic.file_path.lower().endswith(".cbz"):
            success = write_comicinfo_xml(comic.file_path, comic)
            if not success:
                errors.append(f"{comic.series} #{comic.number}: Failed to write XML")
                self.update_state(
                    state="PROGRESS",
                    meta={"current": i + 1, "total": total, "written": written, "errors": errors},
                )
                continue

        comic.state = Comic.STATE_WRITTEN
        comic.last_written = timezone.now()
        if comic.flags.get("count_updated"):
            comic.flags.pop("count_updated", None)
        comic.save()
        written += 1

        self.update_state(
            state="PROGRESS",
            meta={"current": i + 1, "total": total, "written": written, "errors": errors},
        )

    return {"written": written, "total": total, "errors": errors}


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
        return {"written": 0, "total": 0, "errors": []}

    written = 0
    errors = []

    for i, comic_id in enumerate(comic_ids):
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

    return {"written": written, "total": total, "errors": errors}
