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
        # Import
        dict(key="min_page_count",        label="Minimum page count",          type="int",    group="Import",     help_text="Comics below this page count are flagged for review", value="5"),
        dict(key="cover_page_threshold",  label="Cover-only page threshold",   type="int",    group="Import",     help_text="Files at or below this count + 'cover' in name are flagged", value="3"),
        dict(key="import_convert_cbr",    label="Auto-convert CBR to CBZ",     type="bool",   group="Import",     help_text="Automatically queue CBR/CB7 files for conversion on import", value="true"),
        # Library
        dict(key="untagged_dir",          label="Untagged (drop) folder",      type="path",   group="Library",    help_text="Where new digital comics are dropped for import", value="/comics/untagged"),
        dict(key="library_dir",           label="Organized library folder",    type="path",   group="Library",    help_text="Where the Library Organizer moves finished comics", value="/comics/library"),
        dict(key="cv_db_path",            label="ComicVine SQLite DB path",    type="path",   group="Library",    help_text="Path to your local ComicVine SQLite index", value="/cv_db/comicvine.db"),
        dict(key="dry_run_organizer",     label="Dry-run Library Organizer",   type="bool",   group="Library",    help_text="Preview moves without touching any files", value="true"),
        # Format Detection
        dict(key="one_shot_max_count",       label="One-Shot Max Count",       type="int", group="Format", help_text="Comics with count <= this value are One-Shot (default: 1)", value="1"),
        dict(key="limited_series_max_count", label="Limited Series Max Count", type="int", group="Format", help_text="Comics with count <= this (but > One-Shot max) are Limited Series; above = Main Series (default: 15)", value="15"),
        # Appearance
        dict(key="show_series_completion", label="Show Series Completion", type="bool", group="Appearance", help_text="Show a progress bar on comic detail pages indicating how complete the series/volume is", value="true"),
    ]

    for d in defaults:
        Setting.objects.get_or_create(key=d["key"], defaults=d)
