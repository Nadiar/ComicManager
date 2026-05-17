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
        if self.is_cancelled():
            self.clear_cancel()
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


@shared_task(bind=True, base=ProgressTask, name="organizer.scan_au_paths", queue="organize")
def scan_au_paths_task(self):
    """
    Detect two groups of organized AU comics that need to be moved:

    Group 1 — no MCT yet: comics still in the generic Alternate Universe folder with no
    main_character_or_team. Check whether any enabled tagging ruleset now matches and sets
    one. If so, apply the full ruleset and flag.

    Group 2 — stranded: comics where MCT is already set (e.g. by a previous scan) but
    needs_reorganize is still False and the file is still in the AU folder. Re-apply all
    rules (so any new rule actions like Tags Remove take effect) then check the path.
    """
    from django.db.models import Q

    from apps.core.models import Comic
    from apps.tagging.engine import apply_datamanager_rules, evaluate_ruleset
    from apps.tagging.models import DataManagerRuleset

    from .services import preview_organization

    # Pre-filter to rulesets that set MainCharacterOrTeam to a non-empty value.
    candidate_rulesets = [
        rs for rs in DataManagerRuleset.objects.filter(is_enabled=True).order_by("priority")
        if any(
            action.get("field") == "MainCharacterOrTeam"
            and action.get("modifier") == "SetValue"
            and action.get("value", "").strip()
            for action in (rs.actions or [])
        )
    ]

    base_filter = dict(
        state__in=[Comic.STATE_ORGANIZED, Comic.STATE_WRITTEN, Comic.STATE_DONE],
        medium=Comic.MEDIUM_DIGITAL,
        file_path__icontains="alternate universe",
    )

    # Group 1: no MCT set yet
    group1_ids = list(
        Comic.objects.filter(
            Q(main_character_or_team__isnull=True) | Q(main_character_or_team=""),
            **base_filter,
        )
        .exclude(file_path__isnull=True).exclude(file_path="")
        .values_list("pk", flat=True)
    ) if candidate_rulesets else []

    # Group 2: MCT already set but not flagged. Stranded from a previous scan
    group2_ids = list(
        Comic.objects.filter(
            needs_reorganize=False,
            **base_filter,
        )
        .exclude(main_character_or_team__isnull=True)
        .exclude(main_character_or_team="")
        .exclude(file_path__isnull=True).exclude(file_path="")
        .values_list("pk", flat=True)
    )

    all_ids = list(dict.fromkeys(group1_ids + group2_ids))  # deduplicate, preserve order
    total = len(all_ids)

    if total == 0:
        return {"scanned": 0, "flagged": 0, "skipped": 0, "total": 0, "errors": []}

    flagged = 0
    skipped = 0
    errors = []

    self.update_state(
        state="PROGRESS",
        meta={"current": 0, "total": total, "flagged": 0, "skipped": 0, "errors": []},
    )

    for i, comic_id in enumerate(all_ids):
        if self.is_cancelled():
            self.clear_cancel()
            return {
                "scanned": i, "flagged": flagged, "skipped": skipped,
                "total": total, "errors": errors, "cancelled": True,
            }

        try:
            comic = Comic.objects.get(pk=comic_id)
        except Comic.DoesNotExist:
            continue

        try:
            in_group1 = not (comic.main_character_or_team or "").strip()

            if in_group1:
                # Group 1: only bother if a candidate ruleset matches
                if not any(evaluate_ruleset(comic, rs) for rs in candidate_rulesets):
                    skipped += 1
                    continue
                apply_datamanager_rules(comic, save=True)
            else:
                # Group 2 (stranded): re-apply all rules so any new/changed rule actions
                # (e.g. Tags Remove Alternate Universes from the Cleanup rule) take effect
                # before we recompute the expected path.
                apply_datamanager_rules(comic, save=True)

            comic.refresh_from_db()

            if not (comic.main_character_or_team or "").strip():
                skipped += 1
                continue

            # Compute expected path with current metadata (tags may have changed above)
            preview = preview_organization(comic)
            new_path = preview["new_path"]

            if os.path.abspath(comic.file_path) != os.path.abspath(new_path):
                Comic.objects.filter(pk=comic.pk).update(
                    needs_reorganize=True,
                    expected_path=new_path,
                )
                flagged += 1
            else:
                skipped += 1

        except Exception as e:
            errors.append(f"{comic.series} #{comic.number}: {str(e)}")

        self.update_state(
            state="PROGRESS",
            meta={
                "current": i + 1,
                "total": total,
                "flagged": flagged,
                "skipped": skipped,
                "errors": errors,
            },
        )

    return {
        "scanned": total,
        "flagged": flagged,
        "skipped": skipped,
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
        if self.is_cancelled():
            self.clear_cancel()
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


@shared_task(bind=True, base=ProgressTask, name="organizer.reorganize_au_flagged", queue="organize")
def reorganize_au_flagged_task(self):
    """
    Run the full tag → organize → write pipeline for AU comics flagged by the AU scan.
    Targets comics that are needs_reorganize=True, have main_character_or_team set, and
    are still sitting in the generic Alternate Universe folder.
    """
    from apps.core.models import Comic
    from apps.core import workflow

    comic_ids = list(
        Comic.objects.filter(
            needs_reorganize=True,
            medium=Comic.MEDIUM_DIGITAL,
            file_path__icontains="alternate universe",
        )
        .exclude(file_path__isnull=True).exclude(file_path="")
        .exclude(main_character_or_team__isnull=True).exclude(main_character_or_team="")
        .values_list("pk", flat=True)
    )
    total = len(comic_ids)

    if total == 0:
        return {"moved": 0, "total": 0, "errors": []}

    moved = 0
    errors = []

    self.update_state(
        state="PROGRESS",
        meta={"current": 0, "total": total, "moved": 0, "errors": []},
    )

    for i, comic_id in enumerate(comic_ids):
        if self.is_cancelled():
            self.clear_cancel()
            return {"moved": moved, "total": total, "errors": errors, "cancelled": True}

        try:
            comic = Comic.objects.get(pk=comic_id)
        except Comic.DoesNotExist:
            continue

        old_path = comic.file_path
        try:
            tag_res = workflow.tag(comic, force=True)
            if not tag_res.success:
                raise Exception(tag_res.error or tag_res.message)
            org_res = workflow.organize(comic, force=True)
            if not org_res.success:
                raise Exception(org_res.error or org_res.message)
            write_res = workflow.write(comic, force=True)
            if not write_res.success:
                raise Exception(write_res.error or write_res.message)
            moved += 1
        except (PermissionError, OSError) as e:
            errors.append(f"{comic.series} #{comic.number}: {str(e)}")
            self.update_state(
                state="PROGRESS",
                meta={"current": i + 1, "total": total, "moved": moved, "errors": errors},
            )
            return {"moved": moved, "total": total, "errors": errors, "cancelled": False, "stopped_early": True}
        except Exception as e:
            errors.append(f"{comic.series} #{comic.number}: {str(e)}")

        self.update_state(
            state="PROGRESS",
            meta={"current": i + 1, "total": total, "moved": moved, "errors": errors},
        )

    return {"moved": moved, "total": total, "errors": errors, "cancelled": False}
