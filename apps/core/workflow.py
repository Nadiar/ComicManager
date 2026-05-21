"""
Canonical workflow actions for ComicManager.

Every entry point (detail page view, force-view, action bar, dashboard, smartlist,
bulk action, pipeline) MUST go through one of the six action functions here. Audit
logging happens exactly once per action invocation, inside the action function.

Contract for every action:
    1. Capture state_before = comic.state and snapshot relevant fields.
    2. Check the state gate. If gate fails and force=False, return
       ActionResult(skipped=True, ...) without writing to the audit log
       (matches the existing behavior where skipped invocations do not log).
    3. Do the work and save the comic.
    4. Call log_batch_entry(...) exactly once, with diff_fields output or a
       fallback marker like {"result": [None, "matched"]}.
    5. Return ActionResult(success=True, detail={...}).
    6. On exception: log {"error": [None, str(e)]} and either return
       ActionResult(success=False, error=...) or re-raise per action policy.

The `force` kwarg bypasses the STATE gate only. Validation gates (file existence,
.cbz extension, is_duplicate, validate_comic_for_write) stay enforced regardless
of `force`. This matches what the legacy force_* views do today.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ActionResult:
    """Standardized return type for all workflow actions."""

    action: str
    success: bool
    message: str
    state_before: str
    state_after: str
    skipped: bool = False
    detail: dict = field(default_factory=dict)
    changes: dict = field(default_factory=dict)
    error: Optional[str] = None

    def to_json(self) -> dict:
        """Build a JsonResponse-ready envelope. Spreads `detail` into the top level
        so views need no per-action JSON shaping. Keys starting with ``_`` or ending
        in ``_obj`` are excluded — those carry raw Python objects (e.g. scraper match)
        for in-process consumers like the pipeline."""
        out = {
            "success": self.success,
            "message": self.message,
            "state": self.state_after,
            "skipped": self.skipped,
        }
        for k, v in self.detail.items():
            if k.startswith("_") or k.endswith("_obj"):
                continue
            out[k] = v
        if self.error:
            out["error"] = self.error
        return out


def advance_state(comic, to_state: str, *, force: bool = False) -> ActionResult:
    """Move a comic from one workflow state to another and audit the transition.

    Use this when an orchestrator (e.g. pipeline, batch task) needs to push a
    comic between two action steps that don't share a transition. The action
    functions (tag, format, organize, write) handle their own internal advance;
    this is the seam between them.

    Without force, only forward transitions defined in `_FORWARD_TRANSITIONS`
    are allowed (no backwards-jumping). force=True bypasses the legality check
    but still emits the same audit entry.
    """
    from apps.core.audit import log_batch_entry
    from apps.core.models import Comic

    state_before = comic.state

    if state_before == to_state:
        return ActionResult(
            action="advance_state", success=True,
            message=f"Comic already in '{to_state}'",
            state_before=state_before, state_after=state_before,
            skipped=True,
        )

    if not force and to_state not in _FORWARD_TRANSITIONS.get(state_before, set()):
        return ActionResult(
            action="advance_state", success=False,
            message=f"Illegal state transition: '{state_before}' -> '{to_state}'",
            state_before=state_before, state_after=state_before,
            skipped=True,
        )

    comic.state = to_state
    comic.save(update_fields=["state", "updated_at"])
    log_batch_entry("state_advance", comic, state_before, to_state, {"state": [state_before, to_state]})

    return ActionResult(
        action="advance_state", success=True,
        message=f"State advanced: {state_before} -> {to_state}",
        state_before=state_before, state_after=to_state,
        changes={"state": [state_before, to_state]},
    )


# Permitted forward transitions when advance_state is called without force.
# Reverse moves and arbitrary jumps require force=True (used by reorganize-from-done
# and similar admin-initiated paths). Built lazily so the Comic model imports stay
# scoped per call.
def _build_forward_transitions():
    from apps.core.models import Comic
    return {
        Comic.STATE_NEW:          {Comic.STATE_IMPORTED},
        Comic.STATE_IMPORTED:     {Comic.STATE_SCRAPED, Comic.STATE_TAGGED, Comic.STATE_COUNTED},
        Comic.STATE_SCRAPED:      {Comic.STATE_COUNTED, Comic.STATE_TAGGED},
        Comic.STATE_COUNTED:      {Comic.STATE_TAGGED},
        Comic.STATE_TAGGED:       {Comic.STATE_FORMATTED},
        Comic.STATE_FORMATTED:    {Comic.STATE_DEDUPLICATED},
        Comic.STATE_DEDUPLICATED: {Comic.STATE_ORGANIZED},
        Comic.STATE_ORGANIZED:    {Comic.STATE_WRITTEN},
        Comic.STATE_WRITTEN:      {Comic.STATE_DONE},
        Comic.STATE_DONE:         set(),
    }


class _LazyTransitions:
    """Defer Comic import until first use (this module is imported during app load)."""
    def __init__(self):
        self._cache = None

    def get(self, key, default=None):
        if self._cache is None:
            self._cache = _build_forward_transitions()
        return self._cache.get(key, default)


_FORWARD_TRANSITIONS = _LazyTransitions()


def accept(comic, *, force=False) -> ActionResult:
    """Accept a STATE_NEW comic: copy proposed_* into confirmed fields, hash the
    cover if not already hashed, advance to STATE_IMPORTED.

    State gate: STATE_NEW. force=True bypasses (but accept on a non-NEW comic
    is a no-op since the proposed values are already confirmed).

    detail keys: series, number, volume, year, phash_set.
    """
    from apps.core.audit import log_batch_entry, snapshot_fields, diff_fields
    from apps.core.models import Comic
    from apps.scraper.hasher import extract_cover_hashes

    state_before = comic.state

    if not force and comic.state != Comic.STATE_NEW:
        return ActionResult(
            action="accept", success=False,
            message=f"Comic is not in 'new' state (current: {comic.state})",
            state_before=state_before, state_after=comic.state, skipped=True,
        )

    snap = snapshot_fields(comic, ["series", "number", "volume", "year", "phash", "state"])

    comic.series = comic.proposed_series
    comic.number = comic.proposed_number
    comic.volume = comic.proposed_volume
    comic.year = comic.proposed_year

    phash_set = False
    if comic.file_path and not comic.phash:
        hashes = extract_cover_hashes(comic.file_path)
        if hashes:
            comic.phash = hashes.phash_hex
            comic.ahash = hashes.ahash_hex
            phash_set = True

    if comic.state == Comic.STATE_NEW:
        comic.state = Comic.STATE_IMPORTED
    comic.save()

    changes = diff_fields(comic, snap)
    log_batch_entry("accept", comic, state_before, comic.state, changes or {"processed": [None, True]})

    return ActionResult(
        action="accept", success=True,
        message=f"Accepted: {comic.series} #{comic.number}",
        state_before=state_before, state_after=comic.state,
        detail={
            "series": comic.series,
            "number": comic.number,
            "volume": comic.volume,
            "year": comic.year,
            "phash_set": phash_set,
        },
        changes=changes,
    )


def scrape(
    comic,
    *,
    scraper=None,
    cv_issue_id=None,
    inducks_issuecode=None,
    inducks_storycode=None,
    insert_covers=True,
    force=False,
) -> ActionResult:
    """Scrape a comic against ComicVine or Inducks and apply the match.

    State gate: STATE_IMPORTED. A manual selection (cv_issue_id, inducks_issuecode,
    inducks_storycode) implies force=True.

    On success: detail["match"] holds a serialized match dict (series, number,
    title, publisher, year, issue_id, match_type, cover_url, cv_cover_url).
    detail["match_obj"] holds the raw match object for callers that need the
    underlying scraper return value.
    """
    from apps.core.audit import log_batch_entry, snapshot_fields, diff_fields
    from apps.core.models import Comic
    from apps.scraper.services import find_best_match, apply_cv_match, apply_inducks_match

    state_before = comic.state
    manual = cv_issue_id is not None or inducks_issuecode is not None or inducks_storycode is not None
    if manual:
        force = True

    if not force and comic.state != Comic.STATE_IMPORTED:
        return ActionResult(
            action="scrape",
            success=False,
            message=f"Comic is not in 'imported' state (current: {comic.state})",
            state_before=state_before,
            state_after=comic.state,
            skipped=True,
        )

    # Inducks branch
    if inducks_issuecode or inducks_storycode:
        from apps.scraper.inducks import InducksScraper

        ind_scraper = InducksScraper()
        try:
            if inducks_storycode and inducks_issuecode:
                match = ind_scraper.get_story_details(inducks_issuecode, inducks_storycode)
            elif inducks_storycode:
                match = ind_scraper.get_story_only(inducks_storycode)
            else:
                match = ind_scraper.get_issue_details(inducks_issuecode)
        except Exception as e:
            log_batch_entry("scrape_all", comic, state_before, comic.state, {"error": [None, str(e)]})
            return ActionResult(
                action="scrape", success=False,
                message=f"Inducks lookup failed: {e}",
                state_before=state_before, state_after=comic.state, error=str(e),
            )

        if not match:
            label = inducks_storycode or inducks_issuecode
            log_batch_entry("scrape_all", comic, state_before, comic.state, {"result": [None, "no_match"]})
            return ActionResult(
                action="scrape", success=False,
                message=f"Not found in Inducks: {label}",
                state_before=state_before, state_after=comic.state,
                detail={"matched": False},
            )

        snap = snapshot_fields(comic, ["series", "publisher"])
        try:
            apply_inducks_match(comic, match)
        except Exception as e:
            log_batch_entry("scrape_all", comic, state_before, comic.state, {"error": [None, str(e)]})
            return ActionResult(
                action="scrape", success=False,
                message=f"Error applying Inducks match: {e}",
                state_before=state_before, state_after=comic.state, error=str(e),
            )

        match_dict = {
            "series": match.series,
            "number": match.issue_number,
            "title": match.title,
            "publisher": match.publisher,
            "year": match.start_year,
            "issue_id": getattr(match, "issuecode", None),
            "match_type": "inducks",
            "cover_url": match.cover_url,
            "cv_cover_url": match.cover_url,
            "matched": True,
        }
        msg = f"Matched story: {match.title}" if not getattr(match, "issuecode", None) else f"Matched: {match.series} #{match.issue_number}"
        changes = diff_fields(comic, snap)
        log_batch_entry("scrape_all", comic, state_before, comic.state, changes or {"result": [None, "matched"]})
        return ActionResult(
            action="scrape", success=True, message=msg,
            state_before=state_before, state_after=comic.state,
            detail={"match": match_dict, "match_obj": match}, changes=changes,
        )

    # ComicVine branch
    if scraper is None:
        from apps.scraper.comicvine import ComicVineScraper
        scraper = ComicVineScraper()

    # Clear previous scrape error flags
    flags_dirty = False
    for key in ("scrape_no_match", "scrape_error", "scrape_error_detail"):
        if key in comic.flags:
            comic.flags.pop(key, None)
            flags_dirty = True
    if flags_dirty:
        comic.save(update_fields=["flags"])

    # Fetch the match
    match = None
    if cv_issue_id is not None:
        from apps.scraper.cv_sources import is_cv_db_available
        try:
            if is_cv_db_available():
                match = scraper.get_issue_details(int(cv_issue_id))
            if not match:
                match = scraper.get_issue_from_api(int(cv_issue_id))
        except Exception as e:
            log_batch_entry("scrape_all", comic, state_before, comic.state, {"error": [None, str(e)]})
            return ActionResult(
                action="scrape", success=False,
                message=f"Scrape error: {e}",
                state_before=state_before, state_after=comic.state, error=str(e),
                detail={"rate_limited": "rate" in str(e).lower() or "limit" in str(e).lower()},
            )
        if match:
            match.match_type = "manual"
    else:
        try:
            match = find_best_match(comic, scraper)
        except Exception as e:
            log_batch_entry("scrape_all", comic, state_before, comic.state, {"error": [None, str(e)]})
            return ActionResult(
                action="scrape", success=False,
                message=f"Scrape error: {e}",
                state_before=state_before, state_after=comic.state, error=str(e),
                detail={"rate_limited": "rate" in str(e).lower() or "limit" in str(e).lower()},
            )

    if not match:
        # Only set the no-match flag for auto matches; manual cv_issue_id failures
        # are a different UX state (the user tried to pick a specific issue).
        if not manual:
            comic.add_flag("scrape_no_match")
            comic.save(update_fields=["flags"])
        no_match_changes = {"result": [None, "no_match"]}
        detail_msg = comic.flags.get("scrape_error_detail")
        if detail_msg:
            no_match_changes["reason"] = [None, detail_msg]
        log_batch_entry("scrape_all", comic, state_before, comic.state, no_match_changes)
        return ActionResult(
            action="scrape", success=False,
            message="No match found in ComicVine database",
            state_before=state_before, state_after=comic.state,
            detail={"matched": False},
        )

    # Apply the match
    snap = snapshot_fields(comic, ["series", "publisher"])
    cv = comic.custom_values or {}
    before_cv_issue = cv.get("comicvine_issue")
    before_cv_volume = cv.get("comicvine_volume")

    try:
        apply_cv_match(comic, match, scraper, insert_covers=insert_covers)
    except Exception as e:
        log_batch_entry("scrape_all", comic, state_before, comic.state, {"error": [None, str(e)]})
        return ActionResult(
            action="scrape", success=False,
            message=f"Error applying match: {e}",
            state_before=state_before, state_after=comic.state, error=str(e),
        )

    changes = diff_fields(comic, snap)
    cv = comic.custom_values or {}
    if cv.get("comicvine_issue") != before_cv_issue:
        changes["cv_issue"] = [before_cv_issue, cv.get("comicvine_issue")]
    if cv.get("comicvine_volume") != before_cv_volume:
        changes["cv_volume"] = [before_cv_volume, cv.get("comicvine_volume")]

    log_batch_entry("scrape_all", comic, state_before, comic.state, changes or {"result": [None, "matched"]})

    match_dict = {
        "series": match.series,
        "number": match.issue_number,
        "title": match.title,
        "publisher": match.publisher,
        "year": match.start_year,
        "issue_id": match.issue_id,
        "match_type": getattr(match, "match_type", ""),
        "cover_url": match.cover_url,
        "cv_cover_url": match.cover_url,
        "matched": True,
    }
    return ActionResult(
        action="scrape", success=True,
        message=f"Matched: {match.series} #{match.issue_number}",
        state_before=state_before, state_after=comic.state,
        detail={"match": match_dict, "match_obj": match}, changes=changes,
    )


def tag(comic, *, force=False) -> ActionResult:
    """Apply DataManager tagging rules to a comic.

    State gate: COUNTED or TAGGED. force=True bypasses.

    On a non-TAGGED early-state comic the action also advances state to TAGGED
    (the action's intrinsic transition). For the TAGGED -> FORMATTED hop the
    pipeline calls workflow.advance_state explicitly, so each transition gets
    its own audit entry.

    detail keys: matched_rulesets, matched_count, changes, changes_count.
    """
    from apps.core.audit import log_batch_entry, snapshot_fields, diff_fields
    from apps.core.models import Comic
    from apps.tagging.engine import apply_datamanager_rules, is_publisher_known

    state_before = comic.state

    if not force and comic.state not in (Comic.STATE_COUNTED, Comic.STATE_TAGGED):
        return ActionResult(
            action="tag", success=False,
            message=f"Comic must be in 'counted' or 'tagged' state, but is '{comic.state}'",
            state_before=state_before, state_after=comic.state, skipped=True,
        )

    snap = snapshot_fields(comic, ["series_group", "main_character_or_team", "state", "format"])

    try:
        rule_result = apply_datamanager_rules(comic, save=False)
        comic.custom_values["DataManager_Processed"] = "Yes"

        if comic.publisher and comic.has_flag("unknown_publisher"):
            if is_publisher_known(comic.publisher):
                comic.remove_flag("unknown_publisher")

        if comic.state in (Comic.STATE_NEW, Comic.STATE_IMPORTED, Comic.STATE_SCRAPED, Comic.STATE_COUNTED):
            comic.state = Comic.STATE_TAGGED

        comic.save()
    except Exception as e:
        log_batch_entry("tag_all", comic, snap["state"], comic.state, {"error": [None, str(e)]})
        return ActionResult(
            action="tag", success=False,
            message=f"Tag failed: {e}",
            state_before=state_before, state_after=comic.state, error=str(e),
        )

    changes = diff_fields(comic, snap)
    log_batch_entry("tag_all", comic, snap["state"], comic.state, changes or {"processed": [None, True]})

    matched_count = rule_result.get("matched_count", len(rule_result.get("matched_rulesets", [])))
    changes_count = rule_result.get("changes_count", len(rule_result.get("changes", [])))
    if matched_count > 0:
        msg = f"Applied {matched_count} ruleset(s), made {changes_count} change(s)"
    else:
        msg = "No matching rulesets found"

    return ActionResult(
        action="tag", success=True, message=msg,
        state_before=state_before, state_after=comic.state,
        detail={
            "matched_rulesets": rule_result.get("matched_rulesets", []),
            "matched_count": matched_count,
            "changes": rule_result.get("changes", []),
            "changes_count": changes_count,
        },
        changes=changes,
    )


def format(  # noqa: A001
    comic, *, _one_shot_max=None, _limited_max=None, force=False
) -> ActionResult:
    """Detect and set the comic's format. State advances per detect_and_set_format
    (which also handles physical-comic short-circuiting to STATE_WRITTEN).

    State gate: STATE_TAGGED or STATE_FORMATTED. force=True bypasses.

    detail keys: old_format, new_format, detected_format, format_changed,
    patterns_checked, series, title, count, page_count.
    """
    import re
    from apps.core.audit import log_batch_entry, snapshot_fields, diff_fields
    from apps.core.models import Comic
    from apps.core.services import (
        detect_and_set_format, OMNIBUS_MIN_PAGES, TPB_MIN_PAGES, TPB_ISSUE_RANGE_RE,
    )

    state_before = comic.state

    if not force and comic.state not in (Comic.STATE_TAGGED, Comic.STATE_FORMATTED):
        return ActionResult(
            action="format", success=False,
            message=f"Comic is not in 'tagged' or 'formatted' state (current: {comic.state})",
            state_before=state_before, state_after=comic.state, skipped=True,
        )

    snap = snapshot_fields(comic, ["state", "format"])

    try:
        detect_result = detect_and_set_format(
            comic, _one_shot_max=_one_shot_max, _limited_max=_limited_max,
        )
    except Exception as e:
        log_batch_entry("format_all", comic, snap["state"], comic.state, {"error": [None, str(e)]})
        return ActionResult(
            action="format", success=False,
            message=f"Format detection failed: {e}",
            state_before=state_before, state_after=comic.state, error=str(e),
        )

    detected = detect_result["detected_format"]
    text = f"{comic.series or ''} {comic.title or ''}"
    summary = comic.summary or ""
    pages = comic.page_count or 0
    patterns_checked = [
        {"pattern": "Director's Cut (text)", "matched": detected == "Director's Cut"},
        {"pattern": "Black & White (text)", "matched": detected == "Black & White"},
        {"pattern": "Omnibus (keyword in title/summary)",
         "matched": detected == "Omnibus" and bool(re.search(r"\bOmnibus\b", text + " " + summary, re.IGNORECASE))},
        {"pattern": f"Omnibus (≥{OMNIBUS_MIN_PAGES} pages, no TPB signals)",
         "matched": detected == "Omnibus" and pages >= OMNIBUS_MIN_PAGES and not re.search(r"\bOmnibus\b", text + " " + summary, re.IGNORECASE)},
        {"pattern": "TPB (keyword)",
         "matched": detected == "TPB" and bool(re.search(r"\bTPB\b|\bTrade Paperback\b", text, re.IGNORECASE))},
        {"pattern": f"TPB (≥{TPB_MIN_PAGES} pages + issue range in summary)",
         "matched": detected == "TPB" and pages >= TPB_MIN_PAGES and bool(TPB_ISSUE_RANGE_RE.search(summary))},
        {"pattern": "Annual (keyword)", "matched": detected == "Annual"},
        {"pattern": "One-Shot (count=1)", "matched": detected == "One-Shot"},
        {"pattern": "Limited Series (count 2-15)", "matched": detected == "Limited Series"},
        {"pattern": "Main Series (count>15)", "matched": detected == "Main Series"},
    ]

    changes = diff_fields(comic, snap)
    log_batch_entry("format_all", comic, snap["state"], comic.state, changes or {"processed": [None, True]})

    return ActionResult(
        action="format", success=True,
        message=f"Format: {comic.format or 'None'}",
        state_before=state_before, state_after=comic.state,
        detail={
            "old_format": detect_result["old_format"],
            "new_format": detect_result["new_format"],
            "detected_format": detected,
            "format_changed": detect_result["format_changed"],
            "patterns_checked": patterns_checked,
            "series": comic.series,
            "title": comic.title,
            "count": comic.count,
            "page_count": pages,
        },
        changes=changes,
    )


def organize(comic, *, dry_run=False, force=False) -> ActionResult:
    """Move a comic file to its library location and advance state to STATE_WRITTEN.

    State gate: STATE_ORGANIZED. force=True bypasses both the state gate and the
    is_duplicate gate (matches legacy force_organize semantics). File-existence
    and physical-medium handling stay enforced.

    detail keys: profile, old_path, new_path, moved, dry_run.
    """
    from apps.core.audit import log_batch_entry
    from apps.core.models import Comic
    from apps.organizer.services import organize_comic as _organize_service

    state_before = comic.state

    if comic.medium == Comic.MEDIUM_DIGITAL and (not comic.file_path or not comic.is_digital):
        return ActionResult(
            action="organize", success=False,
            message="Cannot organize physical comics or comics without file path",
            state_before=state_before, state_after=comic.state,
        )

    try:
        result = _organize_service(comic, dry_run=dry_run, force=force)
    except (PermissionError, OSError) as e:
        log_batch_entry("organize_error", comic, state_before, comic.state, {"error": [None, str(e)]})
        return ActionResult(
            action="organize", success=False,
            message=f"Failed to move file: {e}",
            state_before=state_before, state_after=comic.state, error=str(e),
        )
    except Exception as e:
        log_batch_entry("organize_error", comic, state_before, comic.state, {"error": [None, str(e)]})
        return ActionResult(
            action="organize", success=False,
            message=str(e),
            state_before=state_before, state_after=comic.state, error=str(e),
        )

    if not result["success"]:
        # Service-level skip (state gate, duplicate gate). No audit entry, matching
        # the no-skip-log contract.
        return ActionResult(
            action="organize", success=False,
            message=result["message"],
            state_before=state_before, state_after=comic.state,
            skipped=("must be in 'move' state" in result["message"]),
            detail={
                "profile": result.get("profile"),
                "old_path": result.get("old_path"),
                "new_path": result.get("new_path"),
                "moved": False,
                "dry_run": dry_run,
            },
        )

    audit_changes = {}
    if result.get("moved"):
        audit_changes["path"] = [result.get("old_path"), result.get("new_path")]
    if comic.state != state_before:
        audit_changes["state"] = [state_before, comic.state]
    log_batch_entry("organize_all", comic, state_before, comic.state, audit_changes or {"processed": [None, True]})

    return ActionResult(
        action="organize", success=True,
        message=result["message"],
        state_before=state_before, state_after=comic.state,
        detail={
            "profile": result.get("profile"),
            "old_path": result.get("old_path"),
            "new_path": result.get("new_path"),
            "moved": result.get("moved", False),
            "dry_run": dry_run,
        },
        changes=audit_changes,
    )


def reorganize(comic, *, force=False) -> ActionResult:
    """Move an already-organized/written/done comic to its current correct path.

    Does NOT advance workflow state. Used by the path-audit page to fix path
    mismatches without rerunning the full pipeline.

    State gate: STATE_ORGANIZED, STATE_WRITTEN, or STATE_DONE.
    detail keys: profile, old_path, new_path, moved.
    """
    from apps.core.audit import log_batch_entry, AUDIT_ACTION_ORGANIZE, AUDIT_ACTION_ORGANIZE_ERROR
    from apps.core.models import Comic
    from apps.organizer.services import reorganize_comic as _reorganize_service

    state_before = comic.state

    if not force and comic.state not in (Comic.STATE_ORGANIZED, Comic.STATE_WRITTEN, Comic.STATE_DONE):
        return ActionResult(
            action="reorganize", success=False,
            message=f"Comic must be organized, written, or done (current: {comic.state})",
            state_before=state_before, state_after=comic.state, skipped=True,
        )

    try:
        result = _reorganize_service(comic)
    except (PermissionError, OSError) as e:
        log_batch_entry(AUDIT_ACTION_ORGANIZE_ERROR, comic, state_before, comic.state, {"error": [None, str(e)]})
        return ActionResult(
            action="reorganize", success=False,
            message=f"Failed to move file: {e}",
            state_before=state_before, state_after=comic.state, error=str(e),
        )
    except Exception as e:
        log_batch_entry(AUDIT_ACTION_ORGANIZE_ERROR, comic, state_before, comic.state, {"error": [None, str(e)]})
        return ActionResult(
            action="reorganize", success=False,
            message=str(e),
            state_before=state_before, state_after=comic.state, error=str(e),
        )

    if not result["success"]:
        return ActionResult(
            action="reorganize", success=False,
            message=result.get("error", "Reorganize failed"),
            state_before=state_before, state_after=comic.state,
        )

    if result.get("moved"):
        log_batch_entry(
            AUDIT_ACTION_ORGANIZE, comic, state_before, comic.state,
            {"path": [result.get("old_path"), result.get("new_path")]},
        )

    return ActionResult(
        action="reorganize", success=True,
        message="Comic moved successfully" if result.get("moved") else "Already in correct location",
        state_before=state_before, state_after=comic.state,
        detail={
            "profile": result.get("profile"),
            "old_path": result.get("old_path"),
            "new_path": result.get("new_path"),
            "moved": result.get("moved", False),
        },
    )


def write(comic, *, force=False) -> ActionResult:
    """Write ComicInfo.xml into the comic's CBZ archive and advance to STATE_DONE.

    State gate: STATE_WRITTEN. Validation gate (`validate_comic_for_write`) is
    always enforced. force=True bypasses the state gate but additionally enforces
    that the comic is digital with a .cbz file (matches the legacy force_write
    view). For non-force calls, physical or non-cbz comics are advanced through
    state without writing any file.
    """
    from apps.core.audit import log_batch_entry
    from apps.core.models import Comic
    from apps.core.utils import write_comicinfo_xml, validate_comic_for_write
    from django.db.models import F

    state_before = comic.state

    if not force and comic.state != Comic.STATE_WRITTEN:
        return ActionResult(
            action="write", success=False,
            message=f"Comic must be in 'write' state (current: {comic.state})",
            state_before=state_before, state_after=comic.state, skipped=True,
        )

    if force:
        if not comic.is_digital:
            return ActionResult(
                action="write", success=False,
                message="Cannot write to physical comics",
                state_before=state_before, state_after=comic.state,
            )
        if not comic.file_path or not comic.file_path.lower().endswith(".cbz"):
            return ActionResult(
                action="write", success=False,
                message="Comic has no CBZ file",
                state_before=state_before, state_after=comic.state,
            )

    if comic.is_digital:
        validation_errors = validate_comic_for_write(comic)
        if validation_errors:
            err_msg = f"Missing required fields: {', '.join(validation_errors)}"
            log_batch_entry("write_error", comic, state_before, comic.state, {"error": [None, err_msg]})
            return ActionResult(
                action="write", success=False, message=err_msg,
                state_before=state_before, state_after=comic.state, error=err_msg,
            )

    if comic.is_digital and comic.file_path and comic.file_path.lower().endswith(".cbz"):
        try:
            ok = write_comicinfo_xml(comic.file_path, comic)
        except Exception as e:
            log_batch_entry("write_error", comic, state_before, comic.state, {"error": [None, str(e)]})
            return ActionResult(
                action="write", success=False,
                message=f"Failed to write ComicInfo.xml: {e}",
                state_before=state_before, state_after=comic.state, error=str(e),
            )
        if not ok:
            err = "Failed to write ComicInfo.xml"
            log_batch_entry("write_error", comic, state_before, comic.state, {"error": [None, err]})
            return ActionResult(
                action="write", success=False, message=err,
                state_before=state_before, state_after=comic.state, error=err,
            )

    if comic.state != Comic.STATE_DONE:
        comic.state = Comic.STATE_DONE
    if comic.flags.get("count_updated"):
        comic.flags.pop("count_updated", None)
    comic.save()
    Comic.objects.filter(pk=comic.pk).update(last_written=F("updated_at"))

    log_batch_entry("write_all", comic, state_before, comic.state, {"comicinfo": ["pending", "written"]})

    return ActionResult(
        action="write", success=True,
        message="ComicInfo.xml written successfully",
        state_before=state_before, state_after=comic.state,
    )
