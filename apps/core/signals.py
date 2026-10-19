from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver


# Fields that affect the library organizer's computed path
_PATH_RELEVANT_FIELDS = frozenset({"publisher", "imprint", "series", "format", "main_character_or_team", "volume"})


@receiver(pre_save)
def _capture_path_fields_before_save(sender, instance, update_fields, **kwargs):
    """
    Store the current values of path-relevant fields before saving.

    Called for all models; filters to Comic instances in organized/written state.
    Stored as `_pre_save_path_snapshot` on the instance for use by the
    post_save handler. Uses `.only()` to minimise the extra DB read.
    """
    from .models import Comic

    if sender is not Comic:
        return
    if instance.pk is None:
        instance._pre_save_path_snapshot = None
        return

    # Skip if none of the relevant fields are being written
    if update_fields is not None and not _PATH_RELEVANT_FIELDS.intersection(update_fields):
        instance._pre_save_path_snapshot = None
        return

    try:
        old = Comic.objects.only(*_PATH_RELEVANT_FIELDS, "state", "medium", "file_path").get(pk=instance.pk)
    except Comic.DoesNotExist:
        instance._pre_save_path_snapshot = None
        return

    # Only track changes for comics that are already in the organized library
    if old.state not in (Comic.STATE_ORGANIZED, Comic.STATE_WRITTEN):
        instance._pre_save_path_snapshot = None
        return

    if old.medium != Comic.MEDIUM_DIGITAL or not old.file_path:
        instance._pre_save_path_snapshot = None
        return

    instance._pre_save_path_snapshot = {f: getattr(old, f) for f in _PATH_RELEVANT_FIELDS}


@receiver(post_save)
def flag_needs_reorganize_on_metadata_change(sender, instance, created, **kwargs):
    """
    Set needs_reorganize=True when a path-relevant field changes on an
    organized or written digital comic.

    Uses the snapshot captured by _capture_path_fields_before_save. Writes
    via QuerySet.update() to avoid triggering another post_save cycle.
    """
    from .models import Comic

    if sender is not Comic or created:
        return

    if instance.state not in (Comic.STATE_ORGANIZED, Comic.STATE_WRITTEN):
        return

    snapshot = getattr(instance, "_pre_save_path_snapshot", None)
    if snapshot is None:
        return

    for field in _PATH_RELEVANT_FIELDS:
        if getattr(instance, field) != snapshot.get(field):
            if not instance.needs_reorganize:
                Comic.objects.filter(pk=instance.pk).update(needs_reorganize=True)
            return


def seed_default_settings(sender, **kwargs):
    """
    Seeds default settings into Postgres after migrations.
    Uses get_or_create so re-running never overwrites user values.
    """
    from django.db import connection
    from .models import Setting

    # Only seed after core app migrations have created the table
    if sender.name != "apps.core":
        return

    # Double-check the table exists (safety for fresh DBs)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'core_setting')"
        )
        if not cursor.fetchone()[0]:
            return

    defaults = [
        # Scraping
        dict(key="cv_api_key",            label="ComicVine API Key",          type="secret", group="Scraping",   help_text="Get yours at comicvine.gamespot.com/api/", value=""),
        dict(key="scrape_0day_hours",     label="0Day window (hours)",         type="int",    group="Scraping",   help_text="Comics added within this many hours go into the 0Day queue", value="24"),
        dict(key="scrape_hash_threshold", label="Hash match threshold",        type="int",    group="Scraping",   help_text="Max hamming distance for pHash match (lower = stricter)", value="8"),
        dict(key="scrape_api_fallback",   label="API fallback when DB present", type="bool",   group="Scraping",   help_text="If no match is found in the local ComicVine DB, also try the ComicVine API. Uses your API budget.", value="false"),
        dict(key="scrape_publisher_allow", label="Publisher allow list",        type="text",   group="Scraping",   help_text="Comma-separated publisher names. If set, auto-match only accepts matches whose publisher contains one of these (e.g. 'DC, Marvel, Image'). Matches with no publisher recorded always pass. Leave blank to allow all.", value=""),
        dict(key="scrape_publisher_block", label="Publisher block list",        type="text",   group="Scraping",   help_text="Comma-separated publisher names auto-match must never pick (e.g. 'Panini, Editorial Televisa'). Applied after the allow list. Manual search still shows them.", value=""),
        dict(key="scrape_insert_covers",   label="Insert alt covers on manual scrape", type="bool", group="Scraping", help_text="Fetch and insert variant covers from ComicVine immediately when scraping a single comic manually. If disabled, URLs are saved and covers are inserted at Write time instead.", value="true"),
        dict(key="batch_insert_covers",    label="Insert alt covers on batch scrape",  type="bool", group="Scraping", help_text="Insert variant covers immediately during a batch scrape (slow). If disabled, URLs are saved and covers are inserted at Write time instead.", value="false"),
        dict(key="pipeline_insert_covers", label="Insert alt covers during pipeline",  type="bool", group="Scraping", help_text="Insert variant covers immediately when the pipeline runs its scrape step. If disabled, URLs are saved and covers are inserted at Write time instead.", value="false"),
        dict(key="inducks_enabled",       label="Enable Inducks search",      type="bool",   group="Scraping",   help_text="Show Inducks search option in the scrape modal for Disney comics", value="false"),
        dict(key="inducks_username",      label="Inducks username",           type="text",   group="Scraping",   help_text="Your inducks.org username (required for cover images)", value=""),
        dict(key="inducks_password",      label="Inducks password",           type="secret", group="Scraping",   help_text="Your inducks.org password (required for cover images)", value=""),
        dict(key="inducks_country_lock",  label="Inducks country lock",       type="text",   group="Scraping",   help_text="Force this country code for all Inducks searches (e.g. 'dk'). Leave blank to show the country dropdown.", value=""),
        dict(key="inducks_country_codes", label="Inducks country codes",      type="text",   group="Scraping",   help_text="Comma-separated country codes shown in the Inducks search dropdown (e.g. 'dk,de,nl,se,no,fi,us,it,fr,br')", value="dk,de,nl,se,no,fi,us,it,fr,br"),
        # Import
        dict(key="min_page_count",        label="Minimum page count",          type="int",    group="Import",     help_text="Comics below this page count are flagged for review", value="5"),
        dict(key="cover_page_threshold",  label="Cover-only page threshold",   type="int",    group="Import",     help_text="Files at or below this count + 'cover' in name are flagged", value="3"),
        # Library
        dict(key="untagged_dir",          label="Untagged (drop) folder",      type="path",   group="Library",    help_text="Where new digital comics are dropped for import", value="/comics/untagged"),
        dict(key="library_dir",           label="Organized library folder",    type="path",   group="Library",    help_text="Where the Library Organizer moves finished comics", value="/comics/library"),
        dict(key="cv_db_path",            label="ComicVine SQLite DB path",    type="path",   group="Library",    help_text="Path to your local ComicVine SQLite index", value="/cv_db/comicvine.db"),
        dict(key="cv_mcl_path",           label="ComicVine MCL file path",     type="path",   group="Library",    help_text="Path to latest.mcl (semicolon-delimited volume/issue index). Used for Series Audit when comicvine.db is unavailable.", value="/cv_db/latest.mcl"),
        dict(key="inducks_db_path",       label="Inducks SQLite DB path",     type="path",   group="Library",    help_text="Path to inducks.db (built from ISV files via download_isv.sh)", value="/cv_db/inducks.db"),
        # Format Detection
        dict(key="one_shot_max_count",       label="One-Shot Max Count",       type="int", group="Format", help_text="Comics with count <= this value are One-Shot (default: 1)", value="1"),
        dict(key="limited_series_max_count", label="Limited Series Max Count", type="int", group="Format", help_text="Comics with count <= this (but > One-Shot max) are Limited Series; above = Main Series (default: 15)", value="15"),
        # Deduplication
        dict(key="duplicate_phash_distance", label="Cover Hash max distance", type="int", group="Deduplication", help_text="Maximum pHash Hamming distance for two covers to be considered duplicates (0 = identical, default: 5). Lower values are stricter.", value="5"),
        # Appearance
        dict(key="owner_name",                  label="Your first name",                   type="text", group="Appearance", help_text="Used in the dashboard greeting ('Good morning, Name.'). Leave blank to show 'there'.", value=""),
        dict(key="show_series_completion",     label="Show Series Completion",            type="bool", group="Appearance", help_text="Show a progress bar on comic detail pages indicating how complete the series/volume is", value="true"),
        dict(key="hide_zero_maintenance_rows", label="Hide zero-count maintenance rows",  type="bool", group="Appearance", help_text="Hide rows with a count of 0 in the Review & Maintenance card on the dashboard", value="false"),
        dict(key="filter_rail_default",        label="Filter rail open by default",       type="bool", group="Appearance", help_text="Show the filter rail sidebar on the comics list page by default. Can still be toggled on-demand.", value="false"),
        dict(key="show_au_scan",               label="Show AU Scan in navigation",        type="bool", group="Appearance", help_text="Show the AU Scan link in the sidebar and top navigation. Disable if you don't use the Alternate Universe folder feature.", value="true"),
    ]

    for d in defaults:
        Setting.objects.get_or_create(key=d["key"], defaults=d)

    # Remove obsolete settings
    Setting.objects.filter(key="dry_run_organizer").delete()
    Setting.objects.filter(key="import_convert_cbr").delete()
