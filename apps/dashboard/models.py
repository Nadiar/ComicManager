import uuid
from django.db import models


class SmartList(models.Model):
    """
    A saved, named query with filters on the Comic model.

    Filters are stored as a list of dicts:
        [{"field": "series", "lookup": "icontains", "value": "Batgirls"}, ...]

    Supported lookups: exact, iexact, icontains, contains, gt, gte, lt, lte, isnull
    Supported fields: any Comic model field in the ALLOWED_FIELDS whitelist,
    plus JSONField nested lookups (custom_values__*, flags__*).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=256)
    description = models.TextField(blank=True, default="")

    # Filter criteria: [{field, lookup, value}, ...]
    filters = models.JSONField(default=list, blank=True)

    # Optional CV volume for missing-issues comparison
    comicvine_volume_id = models.IntegerField(
        null=True,
        blank=True,
        help_text="ComicVine volume ID for missing issues comparison",
    )
    comicvine_volume_name = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="Cached volume name from CV DB for display",
    )

    # Display options
    sort_field = models.CharField(max_length=64, default="series")
    sort_direction = models.CharField(
        max_length=4,
        default="asc",
        choices=[("asc", "Ascending"), ("desc", "Descending")],
    )
    icon = models.CharField(max_length=32, blank=True, default="")
    show_on_dashboard = models.BooleanField(default=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def filter_count(self):
        return len(self.filters) if self.filters else 0

    @property
    def has_cv_volume(self):
        return self.comicvine_volume_id is not None
