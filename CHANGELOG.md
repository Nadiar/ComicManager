# Changelog

All notable changes to ComicManager will be documented in this file.

## [Unreleased]

### Added
- **Organizer profile rule editor** — Full UI for creating and editing matching rules on organizer profiles, including nested rule groups with AND/OR logic. Supports all fields (Publisher, Format, Series Group, Tags, etc.) and operators (is, contains, starts with, etc.). Profiles imported from .lop files are now fully editable.
- **Organizer base_folder fix** — Profiles now use their configured `base_folder` instead of the hardcoded `/comics/library` path. Each profile can organize comics into a different root folder.
- **Issue Count management** — Detect and populate missing issue counts from the local ComicVine SQLite DB. Auto-flags comics with `missing_count` during scraping when no count is returned. Detects count mismatches within the same `comicvine_volume` (different comics disagree on issue count) and flags them with `count_mismatch`. Dashboard review queue shows both flags with action buttons: "Populate Counts" (batch-fills from CV DB) and "Detect Mismatches" (scans all volumes for inconsistencies).
- **Tags, Teams, Locations fields** — New model fields for tags, teams, and locations (comma-separated TextFields). Displayed on comic detail page and editable on edit page. Added to FIELD_MAP so they read/write from ComicInfo.xml.
- **ComicDb.xml import support** — `import_library --comicdb /path/to/ComicDb.xml` enriches imports with data from ComicRack's master database: Tags, Teams, Locations, MainCharacterOrTeam, SeriesGroup, and CustomValuesStore. Uses memory-efficient iterparse for ~44K entries. ComicInfo.xml values take precedence; ComicDb.xml fills in gaps.
- **Scraper now saves teams and locations** — The ComicVine scraper already extracted teams and locations from comicvine.db but silently dropped them. Both `_apply_match()` functions (management command and UI view) now persist these fields.
- **Smart Lists** — Saved, named queries with filters on Comic model fields. Create lists with multiple filter criteria (field + lookup + value), optional sorting, and dashboard visibility toggle. Accessible from the main navigation bar.
- **Missing issues detection** — Link a Smart List to a ComicVine volume to compare your library against the full CV issue list. Shows completion percentage, owned vs missing issues, and a detailed comparison table with toggle filters (All/Missing/Owned).
- **ComicVine volume search** — HTMX-powered search when creating/editing Smart Lists to find and link CV volumes from the local database.
- **Dashboard smart list cards** — Smart Lists with `show_on_dashboard` enabled appear as cards on the dashboard with comic counts and completion progress bars.
- **Search, filter, and sort for comic list** - `/comics/` now has a search bar (series, title, publisher, number), filter dropdowns (publisher, format, medium), and sortable column headers with ascending/descending toggle.

- **Server-side pagination** — `/comics/` and smart list detail pages now use server-side pagination (100 per page, configurable 25–500 via `per_page` param). Prevents browser crashes on 40k+ comic libraries. Pagination controls at top and bottom with page number window.
- **ComicVine API fallback** — When the local ComicVine SQLite DB has no match, the scrape modal now shows a "Search API" section to query the live ComicVine API. Always available alongside local results (in case local matches are wrong). Works in both the comic list scrape modal and the comic detail re-scrape modal. API key configured via `/settings/`. API results use the same match selection flow — clicking an API result applies it identically to a local match.
- **4-way metadata comparison** — "Compare All Sources" button on comic detail page fetches data from all 4 sources (PostgreSQL DB, ComicInfo.xml, local comicvine.db, live CV API) and shows a side-by-side comparison table. Fields shared across sources show Match/Different status; source-specific fields (genre, tags, story arcs, etc.) appear in a separate "extras" section.
- **API rate limit display** — When ComicVine returns HTTP 420/429, the UI shows a yellow warning alert with a clear "rate limited" message instead of a generic error. Applies to both the scrape API search and the "Compare All Sources" modal.

### Fixed
- **ComicInfo.xml output parity** — XML output now matches ComicRack format: Tags mapped to model field (not CustomValues), Summary preserves paragraph breaks, Notes auto-populated with CV reference, Pages element with image dimensions, DataManager_Processed normalized to "Yes", standard field names filtered from CustomValues.
- **API rate limiting** — Added 1.1-second delay between ComicVine API calls to prevent HTTP 420 rate limit errors.
- **Natural number sorting** — Comic lists and smart lists now sort issue numbers numerically (1, 2, 3... 10, 11) instead of lexicographically (1, 10, 11... 2, 20). Uses a PostgreSQL annotation to extract leading digits for sorting, with string fallback for non-numeric issues.
- **HTML stripped from ComicVine summaries** — Summary/description fields from ComicVine are now passed through `strip_tags()` to remove HTML markup (`<p>`, `<em>`, etc.).
- **Smart List JSONField filtering** — Filtering on `custom_values__*` fields (e.g., `comicvine_volume` exact "33909") now works correctly. Previously, the value was coerced to an integer which didn't match the string stored in the JSONField.
- **CSS watcher in Docker** — Changed to `@tailwindcss/cli` with `--poll` flag so the Tailwind watcher stays alive on Docker bind mounts where inotify doesn't propagate.
- **Force actions now always advance state** — `force_organize` and `force_write` on the comic detail page now correctly advance the workflow state from any earlier state, matching the existing behavior of `force_tag` and `force_format`.
- **Detail page actions now show result modals** — Re-tag, Re-format, and Re-organize on the comic detail page now display result modals (matched rulesets, detected format, file paths) instead of silently reloading.
- **Standardized all modals** — All modals now use DaisyUI's native `modal` component with centered positioning, dark backdrop, constrained cover images (100px width), and consistent close behavior via `form method="dialog"`.
- **Cover ordering now prioritizes matched/official covers** - When scraping, the cover that matched via hash is shown first. For metadata matches, official ComicVine covers (`/0/4/` path) are prioritized over user-uploaded variants.
- **Force-tag button now properly applies DataManager rules** - Previously, clicking "Re-tag" on a comic detail page would not apply rules if the comic wasn't in 'counted' state. Now it bypasses the state check and applies all matching rulesets regardless of current state. This fixes issues where comics showed "(fallback)" profile instead of the correct organizer profile.

### Changed
- **Workflow pipeline reduced from 9 to 8 states** - Removed unused "scraped" state since scraping goes directly to "counted". Dashboard and comic list now show correct 8-state workflow.
- **Added "Format All" button** - The tagged state now has a "Format All" bulk action button (was missing before).
- **Added workflow navigation bar** - Comic list pages (`/comics/?state=XXX`) now show a clickable navigation bar with all 8 workflow states for easy jumping between stages.
