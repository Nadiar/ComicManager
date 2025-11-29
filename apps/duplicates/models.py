"""
Duplicate Detection Models.

DuplicateGroup: Tracks a set of comics identified as potential duplicates.
DuplicateGroupMembership: Links comics to groups with resolution status.
DuplicateResolution: Audit log for resolution decisions.
"""

import uuid
from django.db import models


class DuplicateGroup(models.Model):
    """
    A group of comics identified as potential duplicates.

    Groups are created during detection and persist until resolved.
    Resolution marks which comic to keep and what to do with others.
    """

    STATUS_PENDING = "pending"
    STATUS_RESOLVED = "resolved"
    STATUS_INTENTIONAL = "intentional"  # User confirmed keeping all
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending Review"),
        (STATUS_RESOLVED, "Resolved"),
        (STATUS_INTENTIONAL, "Marked Intentional"),
    ]

    DETECTION_CV_ID = "cv_id"
    DETECTION_METADATA = "metadata"
    DETECTION_PHASH = "phash"
    DETECTION_FILENAME = "filename"
    DETECTION_CHOICES = [
        (DETECTION_CV_ID, "ComicVine ID Match"),
        (DETECTION_METADATA, "Series/Number/Volume Match"),
        (DETECTION_PHASH, "Cover Hash Similarity"),
        (DETECTION_FILENAME, "Filename Duplicate Pattern"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # How duplicates were detected
    detection_method = models.CharField(
        max_length=16,
        choices=DETECTION_CHOICES,
        db_index=True,
    )

    # For pHash matches, store the max distance in the group
    phash_max_distance = models.IntegerField(null=True, blank=True)

    # Common identifier (CV ID for cv_id method, series+number for metadata)
    match_key = models.CharField(max_length=512, db_index=True)

    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )

    # Reference to the "winner" after resolution
    kept_comic = models.ForeignKey(
        "core.Comic",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="won_duplicate_groups",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "detection_method"]),
        ]

    def __str__(self):
        return f"{self.get_detection_method_display()}: {self.match_key}"

    @property
    def comic_count(self):
        """Number of comics in this group."""
        return self.memberships.count()


class DuplicateGroupMembership(models.Model):
    """
    Links comics to duplicate groups.

    Tracks resolution status per comic in the group.
    """

    RESOLUTION_PENDING = "pending"
    RESOLUTION_KEPT = "kept"
    RESOLUTION_REQUEUED = "requeued"
    RESOLUTION_DELETED = "deleted"
    RESOLUTION_CHOICES = [
        (RESOLUTION_PENDING, "Pending"),
        (RESOLUTION_KEPT, "Kept"),
        (RESOLUTION_REQUEUED, "Re-queued"),
        (RESOLUTION_DELETED, "Deleted"),
    ]

    group = models.ForeignKey(
        DuplicateGroup,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    comic = models.ForeignKey(
        "core.Comic",
        on_delete=models.CASCADE,
        related_name="duplicate_memberships",
    )

    # For pHash groups, individual distance from the "anchor" comic
    phash_distance = models.IntegerField(null=True, blank=True)

    # Resolution status for this comic
    resolution = models.CharField(
        max_length=16,
        choices=RESOLUTION_CHOICES,
        default=RESOLUTION_PENDING,
    )

    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("group", "comic")]
        ordering = ["phash_distance", "added_at"]

    def __str__(self):
        return f"{self.comic} in {self.group}"


class DuplicateResolution(models.Model):
    """
    Audit log for duplicate resolution decisions.

    Records what action was taken, when, and by whom.
    """

    ACTION_KEEP = "keep"
    ACTION_REQUEUE = "requeue"
    ACTION_DELETE = "delete"
    ACTION_KEEP_ALL = "keep_all"
    ACTION_CHOICES = [
        (ACTION_KEEP, "Keep (mark as winner)"),
        (ACTION_REQUEUE, "Re-queue for re-scraping"),
        (ACTION_DELETE, "Delete file and record"),
        (ACTION_KEEP_ALL, "Keep All (intentional)"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    group = models.ForeignKey(
        DuplicateGroup,
        on_delete=models.SET_NULL,  # Keep audit even if group deleted
        null=True,
        related_name="resolutions",
    )

    # Snapshot of group info at resolution time
    detection_method = models.CharField(max_length=16)
    match_key = models.CharField(max_length=512)

    # Resolution details
    action = models.CharField(max_length=16, choices=ACTION_CHOICES)

    # The comic this action was applied to
    comic_id = models.UUIDField(null=True, blank=True)
    comic_str = models.CharField(max_length=512, null=True, blank=True)

    # Additional context
    reason = models.TextField(blank=True)

    resolved_at = models.DateTimeField(auto_now_add=True)
    resolved_by = models.CharField(max_length=256, blank=True, default="user")

    class Meta:
        ordering = ["-resolved_at"]

    def __str__(self):
        return f"{self.get_action_display()}: {self.comic_str} at {self.resolved_at}"
