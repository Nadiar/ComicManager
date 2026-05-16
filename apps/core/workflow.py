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
        so views need no per-action JSON shaping."""
        out = {
            "success": self.success,
            "message": self.message,
            "state": self.state_after,
            "skipped": self.skipped,
            **self.detail,
        }
        if self.error:
            out["error"] = self.error
        return out


def accept(comic, *, force=False) -> ActionResult:
    """Accept a STATE_NEW comic: copy proposed_* into confirmed fields, hash the
    cover, advance to STATE_IMPORTED. Not yet implemented."""
    raise NotImplementedError("workflow.accept not yet implemented")


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
    """Scrape a comic against ComicVine or Inducks and apply the match. Not yet implemented."""
    raise NotImplementedError("workflow.scrape not yet implemented")


def tag(comic, *, advance_to_formatted=False, force=False) -> ActionResult:
    """Apply DataManager tagging rules to a comic. When advance_to_formatted=True,
    the state advances TAGGED -> FORMATTED in the same call. Not yet implemented."""
    raise NotImplementedError("workflow.tag not yet implemented")


def format(  # noqa: A001  (shadowing builtin is intentional within this module)
    comic, *, _one_shot_max=None, _limited_max=None, force=False
) -> ActionResult:
    """Detect and set the comic's format, advancing state per detect_and_set_format. Not yet implemented."""
    raise NotImplementedError("workflow.format not yet implemented")


def organize(comic, *, dry_run=False, force=False) -> ActionResult:
    """Move the comic file to its library location and advance state. Not yet implemented."""
    raise NotImplementedError("workflow.organize not yet implemented")


def write(comic, *, force=False) -> ActionResult:
    """Write ComicInfo.xml into the comic's CBZ archive and advance to STATE_DONE. Not yet implemented."""
    raise NotImplementedError("workflow.write not yet implemented")
