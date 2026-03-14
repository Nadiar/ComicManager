import uuid
from django.db import models


class Comic(models.Model):

    MEDIUM_DIGITAL  = "digital"
    MEDIUM_PHYSICAL = "physical"
    MEDIUM_CHOICES  = [
        (MEDIUM_DIGITAL,  "Digital"),
        (MEDIUM_PHYSICAL, "Physical"),
    ]

    STATE_NEW           = "new"
    STATE_IMPORTED      = "scrape"
    STATE_SCRAPED       = "scraped"       # unused legacy value
    STATE_COUNTED       = "count"
    STATE_TAGGED        = "tagging"
    STATE_FORMATTED     = "formats"
    STATE_DEDUPLICATED  = "deduplicate"
    STATE_ORGANIZED     = "move"
    STATE_WRITTEN       = "write"
    STATE_CHOICES = [
        (STATE_NEW,          "New"),
        (STATE_IMPORTED,     "Scrape"),
        (STATE_COUNTED,      "Add Count"),
        (STATE_TAGGED,       "Tagging"),
        (STATE_FORMATTED,    "Add Formats"),
        (STATE_DEDUPLICATED, "Deduplicate"),
        (STATE_ORGANIZED,    "Move Files"),
        (STATE_WRITTEN,      "Write to CBZ"),
    ]

    # Identity
    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    medium  = models.CharField(max_length=16, choices=MEDIUM_CHOICES, default=MEDIUM_DIGITAL)

    # File (digital only — null for physical)
    # PostgreSQL UNIQUE ignores NULLs so multiple physical records don't conflict
    file_path   = models.CharField(max_length=1024, null=True, blank=True, unique=True)
    file_format = models.CharField(max_length=10, null=True, blank=True)  # cbz cbr pdf
    file_size   = models.BigIntegerField(null=True, blank=True)
    page_count  = models.IntegerField(null=True, blank=True)
    phash       = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    ahash       = models.CharField(max_length=64, null=True, blank=True)

    # Proposed values parsed from filename on import (not yet confirmed)
    proposed_series = models.CharField(max_length=512, null=True, blank=True)
    proposed_number = models.CharField(max_length=32,  null=True, blank=True)
    proposed_volume = models.IntegerField(null=True, blank=True)
    proposed_year   = models.IntegerField(null=True, blank=True)

    # Core metadata
    series    = models.CharField(max_length=512, null=True, blank=True)
    title     = models.CharField(max_length=512, null=True, blank=True)
    number    = models.CharField(max_length=32,  null=True, blank=True)
    count     = models.IntegerField(null=True, blank=True)
    volume    = models.IntegerField(null=True, blank=True)
    year      = models.IntegerField(null=True, blank=True)
    month     = models.IntegerField(null=True, blank=True)
    day       = models.IntegerField(null=True, blank=True)
    publisher = models.CharField(max_length=256, null=True, blank=True)
    summary   = models.TextField(null=True, blank=True)
    genre     = models.CharField(max_length=256, null=True, blank=True)
    web       = models.URLField(max_length=512, null=True, blank=True)
    characters = models.TextField(null=True, blank=True)  # comma-separated
    teams      = models.TextField(null=True, blank=True)  # comma-separated
    locations  = models.TextField(null=True, blank=True)  # comma-separated
    tags       = models.TextField(null=True, blank=True)  # comma-separated
    scan_information = models.CharField(max_length=512, null=True, blank=True)

    # Credits (comma-separated names)
    writer       = models.TextField(null=True, blank=True)
    penciller    = models.TextField(null=True, blank=True)
    inker        = models.TextField(null=True, blank=True)
    colorist     = models.TextField(null=True, blank=True)
    letterer     = models.TextField(null=True, blank=True)
    cover_artist = models.TextField(null=True, blank=True)
    editor       = models.TextField(null=True, blank=True)

    notes = models.TextField(null=True, blank=True)

    # Physical comic storage location (e.g. "Box 3, Shelf A", "Longbox 7")
    storage_location = models.CharField(max_length=255, null=True, blank=True, default="")

    # Format
    format          = models.CharField(max_length=64, null=True, blank=True)
    original_format = models.CharField(max_length=64, null=True, blank=True)
    series_group    = models.CharField(max_length=256, null=True, blank=True)
    main_character_or_team = models.CharField(max_length=256, null=True, blank=True)

    # Custom values from ComicInfo.xml - stores arbitrary key/value pairs
    # e.g. {"comicvine_issue": "898184", "comicvine_volume": "140426", "First Series": "Earth Cities"}
    custom_values = models.JSONField(default=dict, blank=True)

    # Flags for review queue - stores issue flags that need user attention
    # e.g. {"corrupted_archive": true, "low_page_count": true, "is_pdf": true, "no_series": true}
    flags = models.JSONField(default=dict, blank=True)

    # Accepted (suppressed) flags — detection will not re-set these
    # e.g. {"format_mismatch_in_volume": true} means this comic's mismatch is acknowledged
    accepted_flags = models.JSONField(default=dict, blank=True)

    # Duplicates
    is_duplicate = models.BooleanField(default=False, db_index=True)
    duplicate_of = models.ForeignKey(
        "self",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="duplicates",
    )
    duplicate_group = models.ForeignKey(
        "duplicates.DuplicateGroup",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="member_comics",
    )

    # Re-format tracking (when count changes for count-based formats)
    needs_reformat = models.BooleanField(default=False, db_index=True)

    # Manually confirmed format — auto-detection will not overwrite this comic's format
    # and count changes will not set needs_reformat=True
    format_ok = models.BooleanField(default=False)

    # Count-based format types that can change when issue count changes
    COUNT_BASED_FORMATS = frozenset({"One-Shot", "Limited Series", "Main Series"})

    # Library Organizer
    last_organized_path = models.CharField(max_length=1024, null=True, blank=True)
    needs_reorganize = models.BooleanField(default=False, db_index=True)
    expected_path = models.CharField(max_length=1024, null=True, blank=True)

    # Write to file
    last_written = models.DateTimeField(null=True, blank=True)

    # Workflow state
    state = models.CharField(
        max_length=32, choices=STATE_CHOICES, default=STATE_NEW, db_index=True
    )

    imported_at = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["series", "number", "volume"]),
            models.Index(fields=["state", "medium"]),
            models.Index(fields=["publisher", "series"]),
        ]

    def __str__(self):
        parts = [self.series or "Unknown Series"]
        if self.number:
            parts.append(f"#{self.number}")
        if self.year:
            parts.append(f"({self.year})")
        return " ".join(parts)

    @property
    def is_digital(self):
        return self.medium == self.MEDIUM_DIGITAL

    @property
    def is_physical(self):
        return self.medium == self.MEDIUM_PHYSICAL

    @property
    def has_flags(self):
        return bool(self.flags)

    @property
    def flag_list(self):
        """Return list of active flag names."""
        return [k for k, v in self.flags.items() if v]

    def add_flag(self, flag_name: str):
        """Add a flag to this comic."""
        self.flags[flag_name] = True

    def remove_flag(self, flag_name: str):
        """Remove a flag from this comic."""
        self.flags.pop(flag_name, None)

    def has_flag(self, flag_name: str) -> bool:
        """Check if comic has a specific flag."""
        return self.flags.get(flag_name, False)

    def accept_flag(self, flag_name: str):
        """Permanently suppress a flag for this comic. Clears the active flag too."""
        self.accepted_flags[flag_name] = True
        self.flags.pop(flag_name, None)

    def unaccept_flag(self, flag_name: str):
        """Remove the suppression for a flag so detection can re-set it."""
        self.accepted_flags.pop(flag_name, None)

    def is_flag_accepted(self, flag_name: str) -> bool:
        """Check if a flag is permanently suppressed for this comic."""
        return bool(self.accepted_flags.get(flag_name, False))


class Setting(models.Model):
    """
    All user-configurable settings stored in Postgres.
    The .env only holds what Docker needs to boot (DB URL, secret key, UID/GID).
    Everything else lives here and is editable via the Settings UI.
    """

    TYPE_TEXT   = "text"
    TYPE_PATH   = "path"
    TYPE_SECRET = "secret"
    TYPE_BOOL   = "bool"
    TYPE_INT    = "int"
    TYPE_CHOICES = [
        (TYPE_TEXT,   "Text"),
        (TYPE_PATH,   "Path"),
        (TYPE_SECRET, "Secret"),
        (TYPE_BOOL,   "Boolean"),
        (TYPE_INT,    "Integer"),
    ]

    GROUP_SCRAPING   = "Scraping"
    GROUP_LIBRARY    = "Library"
    GROUP_IMPORT     = "Import"
    GROUP_APPEARANCE = "Appearance"

    key   = models.CharField(max_length=128, unique=True)
    value = models.TextField(blank=True, default="")
    label = models.CharField(max_length=256)
    type  = models.CharField(max_length=16, choices=TYPE_CHOICES, default=TYPE_TEXT)
    group = models.CharField(max_length=64, default=GROUP_LIBRARY)
    help_text = models.CharField(max_length=512, blank=True, default="")

    class Meta:
        ordering = ["group", "label"]

    def __str__(self):
        return f"{self.group} / {self.label}"

    @property
    def typed_value(self):
        if self.type == self.TYPE_BOOL:
            return self.value.lower() in ("true", "1", "yes")
        if self.type == self.TYPE_INT:
            return int(self.value) if self.value else 0
        return self.value


def get_setting(key: str, default=None):
    """Convenience accessor used throughout the app."""
    try:
        return Setting.objects.get(key=key).typed_value
    except Setting.DoesNotExist:
        return default
