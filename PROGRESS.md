# ComicManager

## Overall Workflow Phases (based on Comicrack_guide)

### Phase 1: Ingest & Clean Up (Comicrack_guide 01 - Clean Up)

**Goal:** Import new digital comic files and perform initial cleaning, flagging, and conversion.

**Current Status & Tasks:**
- [x] [P1.1] Implement a service (`apps/core/services.py` or similar) to scan a designated import directory (e.g., `/comics/untagged`).
- [x] [P1.2] For each new file, create a `Comic` record, assign a UUID, and parse `series`, `number`, `volume`, `year` from filename into `proposed_*` fields.
- [x] [P1.3] Integrate settings for low page count detection.
- [x] [P1.4] Implement logic to identify comics with `page_count < configurable_threshold` and surface them for review/deletion.
- [x] [P1.5] Implement logic to identify `file_format = 'pdf'` and surface for manual review before delete.
- [x] [P1.6] Implement logic to identify comics where `proposed_series` (or similar parsed fields) are null/empty and surface for manual fix.
- [x] [P1.7] Integrate settings for cover-only detection.
- [x] [P1.8] Implement logic to identify files with `page_count <= 3` and "cover" in the filename (case-insensitive) and flag for deletion.
- [x] [P1.9] Implement Celery batch action for `Convert CBR/CB7` and ensure it handles conversion to CBZ via `p7zip`.
- [-] [P1.10] (Cancelled) Integrate file conversion into the import pipeline, triggering automatically for non-CBZ files.
- [x] [P1.11] Implement a manual entry form (Django admin or a custom UI) to add physical comic records (`medium=physical`, no file). Form at `/physical/add/` creates Comic with `medium=physical, state=imported`. Redirects to comic detail on success.
- [x] [P1.12] Research and implement bulk import functionality for physical comics from CSV/spreadsheet. CSV upload at `/physical/import/` with columns: series (required), number, volume, year, publisher, format, title, notes. UTF-8 with BOM support.
- [-] [P1.13] (Cancelled) Implement explicit "Commit Proposed Values" action/UI for parsed filename data.
- [-] [P1.14] (Cancelled) Implement a "Remove and Rescan" workflow for comics with missing names, involving deleting the comic record and potentially re-triggering the scan on the original folder.
- [-] [P1.15] (Cancelled) Implement specific cleanup actions: "Remove Leading Numbers" from titles.
- [-] [P1.16] (Cancelled) Implement specific cleanup actions: "Remove Language" from the language field.
- [-] [P1.17] (Cancelled) Distinguish removal of *unwanted* covers from management of *variant* covers, providing specific tools for removing unwanted cover files.
- [x] [P1.18] Inline editing for `proposed_series`, `proposed_number`, `proposed_volume`, `publisher`, and `format` on the `STATE_NEW` list — click any cell to edit in place without navigating to the detail page. The `new` state now uses a `proposed_*`-focused default column layout.
- [x] [P1.19] Fix search and filter functionality for comics in the `STATE_NEW` state. Search now queries `proposed_series`, `proposed_number`, and `file_path`. Publisher/Format/Medium dropdowns are hidden for `state=new`. Sort options replaced with `Proposed Series`, `Proposed #`, `Year`, `Pages`, `Updated`.

### Phase 2: ComicVine Scraping (Comicrack_guide 02 & 03)

**Goal:** Scrape metadata from ComicVine, prioritizing TPBs and Director's Cuts, then 0Day and backlog comics.

**Current Status & Tasks:**
- [x] [P2.1] Implemented Celery notifications for all batch actions, including `Scrape All`.
- [x] [P2.2] Implemented `Scrape error flags` (`scrape_no_match`, `scrape_error`, `scrape_error_detail`) for handling scrape failures.
- [x] [P2.3] Implemented matching strategies: pHash / aHash, filename + series + number fuzzy match, ComicVine API fallback, and manual match UI.
- [x] [P2.4] Confirmed `ComicVine API fallback` feature.
- [x] [P2.14] Metadata mismatch audit — background task compares local `series` name against CV volume name in `comicvine.db`. Flags `metadata_mismatch` on comics linked to the wrong volume. Real-time flagged/cleared progress in toast. Results in Batch Log with "To Scrape" rollback per entry. Button only active when `comicvine.db` is present. Flag appears in the dashboard Review Queue. The flag list view uses the full scrape UI (Scrape All + per-row Scrape buttons) with `?force=1` to allow re-scraping from any workflow state. `apply_cv_match` clears the flag after a successful re-scrape. See `AUDIT_FUNC.md` for full details.
- [x] [P2.5] Created `apps/scraper/services.py` as single source of truth for matching logic (`try_hash_match`, `try_metadata_match`, `apply_cv_match`, `metadata_alignment_score`, `series_matches`, `normalize_issue_number`). Removed duplicate implementations from `core/views.py` and `scraper/views.py`. Batch task and management command now import from service layer. Unified `metadata_alignment_score` handles both fresh imports and re-scrapes. Pending: resilience (rate limit retry), metadata depth (story arcs).
- [-] [P2.6] (Cancelled) Implement priority-based queuing for scraping: `0Day`, `Backlog`, `Skipped`, `Rescrape`.
- [x] [P2.7] Implement mechanism to mark comics for later scraping (`skipped` flag or `CVDBSKIP`). `scrape_skipped` flag added — toggled via comic detail Actions menu. Batch scrape excludes flagged comics. Appears in dashboard Review Queue.
- [x] [P2.8] Implement rescrape logic for comics with `CVDB` note (or error flags) but missing `comicvine_issue`.
    *   *Analysis:* Existing `scrape_all` task already clears error flags and retries comics in the `IMPORTED` state. Individual re-scrape is available via UI.
- [x] [P2.9] Implement metadata-only matching for physical comics. Physical comics use the same scrape modal (hash matching skipped automatically when no file_path). After CV match, cover image is downloaded and cached at `cover_cache/{pk}.jpg`. Same for Inducks. Batch `scrape_all` now includes physical comics. `force_scrape` no longer blocks physical.
- [x] [P2.10] Confirmed all ComicVine fields are stored correctly and `scrape_source` is recorded.
- [x] [P2.11] Confirmed `Comic.state` is updated to `counted` (as `scraped` state was removed).
- [-] [P2.12] (Cancelled) Scraping TPBs/Director's Cuts first is unnecessary — format detection (P5.12) handles mis-tagging prevention; pipeline order does not matter.
- [x] [P2.13] Implement metadata-only matching for physical comics. (See P2.9.)
- [x] [P2.14] If flag=scrape_skipped but manually scraping is done and confirmed, the flag should be cleared. `apply_cv_match` and `apply_inducks_match` both call `comic.remove_flag("scrape_skipped")` on successful match confirmation.

### Phase 3: Issue Count (Comicrack_guide 04 - Add Count)

**Goal:** Populate and manage `count` for series, identifying and resolving discrepancies.

**Current Status & Tasks:**
- [x] [P3.1] Implemented `Issue count management` (detect, populate missing counts from local CV DB, auto-flag `missing_count`, detect `count_mismatch`).
- [x] [P3.2] Celery task `populate_counts_task` wraps `_populate_missing_counts()` + `_detect_count_mismatches()` with progress reporting and cancellation. Dispatch via POST `/comics/populate-counts-all/`.
- [x] [P3.3] Covered by existing `missing_count` flag — set during `populate_counts_task` when count cannot be found in CV DB. Appears in dashboard Review Queue with "Populate Counts" button.
- [x] [P3.4] Covered by existing `count_mismatch` flag — set during `populate_counts_task` when comics in the same CV volume disagree on count. Appears in dashboard Review Queue with "Detect Mismatches" button.

### Phase 4: Publisher Management / Data Manager (Comicrack_guide 05 - Data Manager)

**Goal:** Manage publishers, apply tagging rules, and enrich comic metadata.

**Current Status & Tasks:**
- [x] [P4.1] Confirmed `ComicDb.xml import support` enriches imports with data including `MainCharacterOrTeam`, `SeriesGroup`, `CustomValuesStore`.
- [x] [P4.2] Confirmed `Organizer profile rule editor` provides UI for creating and editing matching rules.
- [x] [P4.3] Confirmed rules populate `series_group`, `main_character_team`, `first_series`, `datamanager_processed`.
- [x] [P4.4] Confirmed rules are stored in DB and are editable via UI.
- [x] [P4.5] `unknown_publisher` flag set after scraping when publisher is not covered by any enabled ruleset's Publisher rules. Appears in dashboard Review Queue.
- [x] [P4.6] Publishers page at `/tagging/publishers/` shows covered publishers (from rulesets) vs uncovered publishers with comic counts. "Create Ruleset" button pre-fills publisher rule.
- [-] [P4.7] (Cancelled) Built-in rulesets for Marvel and DC — rulesets are user-managed via the rule editor.
- [-] [P4.8] (Cancelled) Star Wars ruleset — user-managed via the rule editor.

### Phase 5: Format Tagging (Comicrack_guide 06 - Format)

**Goal:** Automatically and manually assign format tags (TPB, Director's Cut, One-Shot, etc.) based on filename, title, and count rules.

**Current Status & Tasks:**
- [x] [P5.1] Implemented auto-tag from filename/title keywords and rule-based detection from Series + Title fields.
- [x] [P5.2] Implemented count-range rules: One-Shot (count = 1), Limited Series (count 2–15), Main Series (count > 15).
- [x] [P5.3] Implemented manual format assignment with confirmation (via `Detail page actions now show result modals`).
- [x] [P5.4] Implemented `Search, filter, and sort for comic list`.
- [x] [P5.5] Implemented `Auto-scan page count on comic detail`.
- [x] [P5.6] Implement a `format_ok` boolean field on the `Comic` model to suppress false positives in smart lists.
- [x] [P5.7] `format_mismatch_in_volume` flag: set by `_detect_format_conflicts()` when comics in the same CV volume have different formats. Appears in Review Queue with "Detect Conflicts" button. Respects `accepted_flags` for permanent per-comic suppression.
- [x] [P5.8] `cv_volume_conflict` flag: set by `_detect_format_conflicts()` when comics with the same Series+Volume+Format are linked to different CV volumes. Appears in Review Queue with "Detect Conflicts" button. Respects `accepted_flags`.
- [x] [P5.9] Implement smart list/logic to surface comics with no format set. Implemented as a `missing_format` flag (set during format detection when no format can be determined, cleared when a format is assigned). Appears in the dashboard Review Queue.
- [x] [P5.10] `needs_reformat` field now set in `populate_counts_task` when a count-based format comic's count changes and the current format no longer matches. Appears in Review Queue with "Re-format All" button. View at `/comics/?needs_reformat=1`.
- [x] [P5.11] Covered by `needs_reorganize` signal in `apps/core/signals.py` — watches `format` field. When an organized/written comic's format changes, `needs_reorganize=True` is set automatically. Surfaced by the Library Re-organize Queue widget on the dashboard.
- [x] [P5.12] Refine existing rules for TPB, Omnibus, Director's Cut, etc. to avoid mis-tagging.
- [x] [P5.13] Fixed search/filter bar on `/comics/?state=new` — see P1.19.
- [x] [P5.14] We need to show page count, so we can see if we talk about TPB or limited series on low issue count.

### Phase 6: Duplicate Detection (Comicrack_guide 07 - Duplicated)

**Goal:** Identify and manage duplicate comic entries to maintain a clean collection.

**Current Status & Tasks:**
- [x] [P6.1] Confirmed pre-move gate blocks comics with `is_duplicate=True`.
- [x] [P6.2] Implemented duplicate detection by `comicvine_issue`, series + number + volume match, pHash / aHash similarity, and filename patterns.
- [x] [P6.3] Confirmed "Digital + Physical same CV ID is explicitly NOT a duplicate" rule.
- [x] [P6.4] Implemented duplicate resolution UI with side-by-side comparison and actions (keep/soft-delete/delete).
- [x] [P6.5] Implemented soft-delete only (`is_duplicate=True`, `duplicate_of` FK set).
- [x] [P6.6] Audit log already implemented via `DuplicateResolution` model. Every resolve_keep / resolve_requeue / resolve_delete / resolve_keep_all call creates a `DuplicateResolution` entry. Viewable at `/duplicates/history/`.
- [x] [P6.7] Duplicate Review group card now shows a tip line: "Delete unwanted comics first — the last remaining one is auto-kept. Or use Keep & Del Rest to decide in one step."
- [x] [P6.8] `resolve_keep` now sets `winner.format_ok = True` so the kept comic is marked as format-confirmed.
- [x] [P6.9] Series link in the group card and "View" button in the group detail page both open in a new tab (`target="_blank"`).
- [x] [P6.10] "Keep & Del Rest" button now uses `showConfirm` DaisyUI modal instead of the browser `confirm()` popup. Uses `htmx.ajax()` with `source: btn` so the ancestor `hx-headers` CSRF token is inherited.

### Phase 7: Library Organizer (Comicrack_guide 08 - Library Organizer)

**Goal:** Move and rename comic files into an organized folder structure based on defined templates and metadata.

**Current Status & Tasks:**
- [x] [P7.1] Implemented folder template engine with variable substitution.
- [x] [P7.2] Implemented editable templates stored in DB via `Organizer profile rule editor`.
- [x] [P7.3] Implemented organize passes (Marvel, DC, etc.) and confirmed `Organizer profiles use configured base_folder`.
- [x] [P7.4] Implemented dry-run mode and duplicate gate.
- [x] [P7.5] Implemented tracking `last_organized_path`.
- [x] [P7.6] Implemented `Path audit page` for batch-scanning and reporting path mismatches.
- [x] [P7.7] Implemented Celery notifications for `Organize All` and confirmed `force_organize` advances state.
- [x] [P7.8] Covered by `needs_reorganize` signal in `apps/core/signals.py` — `main_character_or_team` is in `_PATH_RELEVANT_FIELDS`. When this field changes on an organized/written comic, `needs_reorganize=True` is set. Surfaced by the Library Re-organize Queue widget on the dashboard.
- [-] [P7.9] (Cancelled) Physical comics are stored on shelves with a storage_location field — path calculation is irrelevant.
- [x] [P7.10] Organize and write failures are now logged to the batch audit log as `organize_error` / `write_error` entries. Errors appear in the log viewer at `/settings/log/` with a red badge and dedicated filter tabs. Covers: file-not-found during organize, failed file move, failed ComicInfo.xml write — logged from both standalone batch tasks and smart list actions.
- [x] [P7.11] Externalize Docker paths for `library` and `untagged` directories, and the `PORT` variable, into a `.env` file. `UNTAGGED_DIR` and `LIBRARY_DIR` added to both compose files with defaults so existing setups are unaffected. `.env.example` created documenting all required variables.

### Phase 8: Write to File (Comicrack_guide 09 - Write to File)

**Goal:** Update `ComicInfo.xml` within CBZ files with the latest metadata when changes occur.

**Current Status & Tasks:**
- [x] [P8.1] Implemented detection of missing or outdated `ComicInfo.xml`.
- [x] [P8.2] Implemented writing `ComicInfo.xml` into CBZ on demand only (user-triggered).
- [x] [P8.3] Implemented tracking `last_written` timestamp and show staleness indicator.
- [x] [P8.4] Confirmed physical comics are skipped.
- [x] [P8.5] Implemented Celery notifications for `Write to File` and confirmed `force_write` advances state.
- [x] [P8.6] Implemented `ComicInfo.xml output parity` (XML matches ComicRack format, includes `DataManager_Processed`, standard fields).
- [-] [P8.7] (Cancelled) Embed UUID as a custom field in `ComicInfo.xml` — not needed.
- [x] [P8.8] Validation before writing ComicInfo.xml. Blocks write if `series`, `number` (unless format is TPB/Omnibus/etc.), or `publisher` is missing. `write_comic` view returns HTTP 400 with a clear error message. All 4 batch write tasks skip and log invalid comics as `write_error` in the audit log. `force_write` bypasses validation as the explicit escape hatch.

## Re-organize Efficiency

**Goal:** Improve efficiency of path checking and re-organization for large comic collections.

**Current Status & Tasks:**
- [x] [RE.1] Implemented `Path audit page`.
- [x] [RE.2] `needs_reorganize` boolean field on `Comic` model (indexed) — implemented in migration 0006.
- [x] [RE.3] `post_save` signal in `apps/core/signals.py` sets `needs_reorganize=True` when `publisher`, `series`, `format`, `main_character_or_team`, or `volume` changes on organized/written comics. `pre_save` signal on `OrganizerProfile` flags all organized/written comics when folder/file template or base folder changes.
- [x] [RE.4] Dashboard widget shows queue count with direct "Re-organize All" button when `needs_reorganize_count > 0`. Links to Path Audit page.
- [x] [RE.5] Batch re-organize action available via Path Audit page (`reorganize_all_flagged_task`) and now also from the dashboard widget.
- [x] [RE.6] `reorganize_comic()` service already clears `needs_reorganize=False` and `expected_path=None` after successful move.
- [x] [RE.7] Path audit page provides the full browse/compare interface.

## Smart Lists Needed

**Goal:** Implement all required smart lists for better comic management and user insights.

**Current Status & Tasks:**
- [x] [SL.1] Implemented `Smart Lists` framework (saved, named queries with filters, optional sorting, dashboard visibility).
- [x] [SL.2] Implemented `Dynamic column customization` for table columns.
- [x] [SL.3] Extended smart list filter field whitelist (`ALLOWED_FIELDS`) and UI dropdown (`FILTER_FIELD_OPTIONS`) to support `proposed_*` fields, all `flags__*` keys, `file_format`, `needs_reorganize`, `needs_reformat`, `last_written`, `imported_at`, `custom_values__comicvine_issue`, `custom_values__scrape_source`, and two new sort options (`Import Date`, `Last Written`). Documented flag filter usage in README.
- [-] [SL.P1.1] (Superseded) Page Count Too Low — already surfaced via `low_page_count` flag in the dashboard Review Queue.
- [-] [SL.P1.2] (Superseded) PDF Files — already surfaced via `is_pdf` flag in the dashboard Review Queue.
- [-] [SL.P1.3] (Superseded) Unparseable Filename — already surfaced via `missing_series` flag in the dashboard Review Queue.
- [-] [SL.P1.4] (Superseded) Standalone Covers — already surfaced via `standalone_cover` flag in the dashboard Review Queue.
- [-] [SL.P5.1] (Superseded) Format Mismatches — surfaced via `format_mismatch_in_volume` flag in the dashboard Review Queue (P5.7).
- [-] [SL.P5.2] (Superseded) CV Volume Conflicts — surfaced via `cv_volume_conflict` flag in the dashboard Review Queue (P5.8).
- [-] [SL.P5.3] (Superseded) Missing Format — surfaced via `missing_format` flag in the dashboard Review Queue (P5.9).
- [-] [SL.P5.4] (Superseded) Format Upgrades Needed — surfaced via `needs_reformat` field in the dashboard Review Queue (P5.10).
- [-] [SL.P6.1] (Superseded) Duplicates by CV Issue — surfaced in the Maintenance tab of the Review & Maintenance dashboard card with breakdown by method; filterable via `/duplicates/?method=cv_id`.
- [-] [SL.P6.2] (Superseded) Duplicates by Series/Number — surfaced in the Maintenance tab; filterable via `/duplicates/?method=metadata`.
- [-] [SL.P6.3] (Superseded) Duplicates by pHash — surfaced in the Maintenance tab; filterable via `/duplicates/?method=phash`.
- [-] [SL.P8.1] (Superseded) Missing ComicInfo.xml — surfaced as a Maintenance tab row with count and "Write Missing" action.
- [-] [SL.P8.2] (Superseded) Stale Metadata — surfaced as a Maintenance tab row with count and "Write Stale" action.
    *   *Implementation Note:* All these smart lists will be created using the existing `Smart Lists` and `Dynamic column customization` framework.

## Dashboard & UI Enhancements

**Goal:** Enhance the user interface with better dashboard features, settings management, and task monitoring.

**Current Status & Tasks:**
- [x] [UI.1] Confirmed existing dashboard shows 8-state workflow and Smart Lists with `show_on_dashboard` appear as cards.
- [x] [UI.2] Confirmed `Celery notifications`, `Task cancel button`, `Task failure dismiss button` provide task monitoring.
- [x] [UI.3] Confirmed `Settings for low page count and cover-only detection`, `Organizer profile rule editor`, and ComicVine API key config are implemented.
- [x] [UI.4] Confirmed `Search, filter, and sort for comic list` provides search bar functionality.
- [x] [UI.5] Confirmed `Dynamic column customization`, `Server-side pagination`, and sortable column headers are implemented.
- [x] [UI.6] Confirmed `Celery notifications for all batch actions` covers various bulk actions.
- [x] [UI.7] Visual pipeline funnel and smart list counts on the dashboard — both already implemented. Pipeline shows 8-stage `steps` component with per-stage counts and action buttons. Smart lists with `show_on_dashboard=True` render as count cards with optional CV completion progress bars.
- [ ] [UI.8] Consolidate and enhance existing settings into a single, comprehensive settings UI for templates, publisher rules, and API keys.
- [x] [UI.9] Batch audit log at `/settings/log/` — filterable by action (Scrape/Tag/Format/Organize/Write/Audit), per-comic changes diff, copyable UUID, rollback buttons. Log written to `./data/logs/batch_actions.jsonl`. Audit entries include a "To Scrape" rollback button to reset bad matches. Log entries are only written when a flag is newly added or cleared (not on repeated re-runs). All pipeline stages now log: `scrape_all`, `tag_all`, `format_all`, `organize_all` (records old/new path), `write_all` (records comicinfo write), `audit_metadata`.
- [ ] [UI.10] Implement functionality to export comic metadata as JSON for individual comics and potentially in bulk.
- [ ] [UI.11] Enhance global search to return both digital and physical comics, clearly indicating the medium with a "medium badge".
- [ ] [UI.12] Ensure all smart lists have full pagination, sorting, and column toggling capabilities.
- [ ] [UI.13] Extend existing bulk actions framework to encompass more granular bulk actions like delete file, flag ok, etc.
- [ ] [UI.14] Add search functionality for minor characters and main characters to the comic table.
- [x] [UI.15] ComicVine API-only mode when comicvine.db is absent. Auto-detects DB/MCL availability. Batch scraping falls back to API search (try_api_metadata_match). Series Audit uses latest.mcl CSV fallback (mount ./data/latest.mcl; format: one row per volume, semicolon-delimited, comma-separated issue IDs and numbers). API call budget tracked in Redis (200/hour). Dashboard banner shows mode + remaining calls. Settings page shows data source status. Series Audit disabled (with message) when neither DB nor MCL is available. Unified find_best_match() entry point in services.py replaces scattered if-db-available branches in tasks, views, and management command. Scrape modal views (scrape_preview, scrape_comic, force_scrape) now guard all DB calls with is_cv_db_available() to prevent 500 errors. enrich_match_with_credits() no longer crashes when DB is absent. Celery task stops gracefully (with user-visible message) when API budget is exhausted mid-run.
- [x] [UI.16] character_audit_search opens a new SQLite connection per volume in a loop (N+1). Fixed via get_volume_completion_bulk() in dashboard/services.py: one SQLite connection, three batch IN queries (volumes, issues, covers), one PostgreSQL query for all owned comics across all volumes.
- [x] [UI.17] Edit comic needs a 'clear flag'.
- [x] [UI.18] ALL popups needs to use a custom modal and not browser based popup.
- [x] [UI.19] Edit comic needs a save to DB (where we skip saving to XML), as we can alwyas use the re-write option later on.
- [x] [UI.20] `/comics` table column selector now sorts columns alphabetically by label. Fixed by sorting `COLUMNS_REGISTRY` by `label` in the view before passing `all_columns` to the template.
- [x] [UI.21] `/comics` table search, filter, and sort overhauled: (1) search expanded to writer, penciller, inker, colorist, letterer, cover_artist, editor, characters, teams, genre, notes; (2) smart search tokens: `#N` filters by issue number, `(YYYY)` by year, `VYYY` by volume, combinable freely; (3) column header sort fixed (sort key mismatch between COLUMNS_REGISTRY and view's sort_fields dict was silently falling back to series sort for every non-trivial column); (4) pages sort uses `NULLS LAST` in both directions. Documented in `docs/guide/searching.md`.
- [x] [UI.22] `/settings/log/` batch log — the UUID column is now an "Info" button that opens the comic detail page in a new tab.
- [ ] [UI.25] Review whether zero-count rows in the Review & Maintenance card (both Active and Maintenance tabs) should be hidden entirely, or kept visible as permanent status indicators.
- [x] [UI.23] Dashboard Review Queue and re-organize/stale widgets consolidated into a single "Review & Maintenance" card with Active and Maintenance tabs. Active tab shows existing review queue; Maintenance tab shows Duplicates, Needs Re-organize, Stale Metadata, and Missing ComicInfo.xml rows with counts and action buttons. Tab auto-selects based on which count is non-zero.
- [x] [UI.24] Duplicate review page gains method filter tabs (All / CV ID / Series-Number / Cover Hash / Filename). Clicking a tab filters the groups list and shows the count per method on each tab button.

## Major Issues / Bugs

**Goal:** Address and resolve all identified bugs and major issues.

**Current Status & Tasks:**
- [x] [BUG.1] Addressed `/comics/<uuid>/` button to load specific comic from API/db and show differences (`4-way metadata comparison`).
- [x] [BUG.2] Addressed button to scan for path changes (`Path audit page`).
- [x] [BUG.3] Fixed pipeline graphics circle overflow.
- [x] [BUG.4] Implemented cover lightbox on comic detail.
- [x] [BUG.5] Implemented dynamic column customization for comic tables.
- [x] [BUG.6] Implemented variant covers swipe/arrows support (`Navigable Lightbox Gallery`).
- [x] [BUG.7] Implemented 'Manage Pages' lightbox preview.
- [x] [BUG.8] Addressed major issue: Re-search for alt covers does not work (`Variant cover gallery no longer shows stale images`).
- [x] [BUG.15] Fixed PostgreSQL JSONField integer/string type mismatch for `custom_values` CV IDs. `parse_comicinfo_xml` now casts all `CustomValue` entries to `str` on import. Previously, numeric IDs stored as integers caused string-based queries to return zero results, breaking Series Audit owned counts and character audit volume matching.
- [x] [BUG.9] Ensure `Summary` and `Notes` fields are multi-line in UI, especially in "Compare All Sources" and "Metadata Comparison" tables.
- [x] [BUG.10] Implement validation to prevent saving tagging rulesets without a modifier and show an error.
- [x] [BUG.11] Add a button/action to refresh all file & system info (hashes, page count, filesize).
- [x] [BUG.12] Verify and implement specific handling of warnings for data-destructive operations in Celery tasks (tell user, finish current comic, stop next). `PermissionError` and disk-full `OSError` in `organize_all_task`, `reorganize_all_flagged_task`, `convert_all_cbr_task`, and `run_smartlist_action_task` (organize/write) now return `stopped_early: True` after the current comic, stopping the batch. The toast label changes to "stopped early" with a red bar; `successText()` shows how many were processed and the error count.
- [x] [BUG.13] When a comic has flag scrape_no_match and is re-scraped, the flag is not removed, even though the comic moves on to the next stage.
- [x] [BUG.14] Fixed corrupted/truncated CBZ files causing blank detail pages and missing page counts. Comics with unreadable archives are now flagged `corrupted_archive` at import and on first detail-page visit. A "Try Rezip" action on the detail page recovers readable entries and repacks the archive in place; if too damaged, the user is prompted to delete and reimport.
- [x] [BUG.16] Stale Metadata dashboard widget "View Comics" link relabelled to "View Written" (honest label since filtering by is_stale at URL level is not possible without a dedicated endpoint).
- [x] [BUG.17] Backfill migration 0008 sets `last_written = updated_at` for all existing comics in `written` state with no `last_written`, so they no longer appear stale after the migration runs.
- [x] [BUG.18] Added dedicated `core:write_stale` endpoint and `write_stale_comics_task` Celery task that filters `state=written AND updated_at > last_written`. Dashboard widget button updated to call this endpoint.
- [x] [BUG.19] Fixed auto_now race condition in all four write paths (`write_comic`, `force_write`, `write_all_comics_task`, `_run_write`). After `comic.save()`, `Comic.objects.filter(pk=comic.pk).update(last_written=F("updated_at"))` syncs `last_written` to the exact same value Django set for `updated_at`.
- [x] [BUG.20] Batch log link in toast now opens in a new tab (`target="_blank"`) with `hx-boost="false"` to prevent HTMX interference.
- [x] [BUG.21] `Last Written` timestamp now shown in the File & System Info section on the comic detail page.
- [x] [BUG.22b] Simplified "No Comics Found" empty state in the comics table: removed the docker import command hint; now just shows "No Comics Found".
- [x] [BUG.24] Batch task queuing implemented client-side. A second batch action triggered while one is running is queued and dispatched automatically once the first completes. The toast label updates to show "Starting next task..." between tasks.
- [x] [BUG.22] Library Re-organize Queue (Re-organize All) now calls `log_batch_entry("organize_all", ...)` for every file that was actually moved, recording `old_path` → `new_path` in the batch log at `/settings/log/`.
- [x] [BUG.23] Library Re-organize Queue toast completion message now shows "X moved, Y already ok (of Z)" instead of "0 processed". Fixed by handling `r.moved` in `successText()` and `progressText()` in `base.html`.
- [x] [BUG.27] `?flag=is_pdf` showed two "Accept" buttons with completely different behaviours. Renamed: flag-suppress button is now "Suppress Flag" (ghost/success, with tooltip explaining it doesn't change state); state-advance button is now "Add to Workflow" when a flag is active (stays "Accept" on plain `?state=new`).
- [x] [BUG.28] Added a "Delete" button (error outline style) to all flag list rows. Uses `showConfirm` modal with a danger confirmation before calling the existing `delete_comic` endpoint. On success the row fades out and is removed from the DOM.
- [ ] [BUG.25] Physical comics have no path forward after reaching `deduplicated` state. The pipeline assumes "Organize All" as the next step, but physical comics live on a shelf (no file to move). A physical comic stuck at state 6 (deduplicated) cannot progress. Needs a dedicated "advance" action or state bypass for physical comics so they can reach `organized` (and optionally `written`) without triggering file operations. Full physical workflow needs end-to-end vetting.
- [ ] [BUG.26] Deduplicate shows in toast eg. 15 of 16 processed, but pressing the auditlog link doesn't show anything logged. 

## I.N.D.U.C.K.S. Integration

**Goal:** Integrate the I.N.D.U.C.K.S. database as an alternative scraping source for Disney/European comics not covered by ComicVine.

**Current Status & Tasks:**
- [x] [IND.1] ISV download script (`download_isv.sh`) downloads and builds a local SQLite database (`data/inducks.db`) from inducks.org ISV flat files (75 tables, 7M+ rows).
- [x] [IND.2] Standalone CLI search tool (`search_inducks.py`) for querying inducks.db by story title, publication title, author, and country code.
- [x] [IND.3] `InducksScraper` class (`apps/scraper/inducks.py`) with `search()` and `get_issue_details()` methods. Searches publication titles, story titles, and entry titles. Returns `InducksMatch` dataclass with credits, characters, publisher, cover date, pages, and Inducks URLs.
- [x] [IND.4] `apply_inducks_match()` in `apps/scraper/services.py` maps Inducks metadata to the Comic model. Sets `custom_values["scrape_source"] = "inducks"` and `custom_values["inducks_issuecode"]`.
- [x] [IND.5] Settings: `inducks_enabled`, `inducks_username`, `inducks_password`, `inducks_country_lock`, `inducks_country_codes`, `inducks_db_path`. Seeded via `signals.py`.
- [x] [IND.6] Scrape modal UI: "I.N.D.U.C.K.S. Search" section in both `comic_list.html` and `comic_detail.html` with search input, country dropdown (or locked), and result cards with direct links to inducks.org.
- [x] [IND.7] Docker volume mount for `inducks.db` in both `docker-compose.yml` and `docker-compose.override.yml`.
- [x] [IND.8] `scrape_comic` view handles both ComicVine and Inducks sources via `source` field in JSON payload.
- [ ] [IND.9] Inducks-scraped comics (`scrape_source == "inducks"`) should skip CV-specific pipeline phases: issue count propagation (Phase 3), alt cover search, and count mismatch detection.
- [ ] [IND.10] Inducks-scraped comics should skip the "Find Alt Covers" action and any CV API lookups on the detail page.
- [ ] [IND.11] Review all batch tasks (scrape_all, populate_counts, format_all, etc.) to ensure they handle Inducks-sourced comics gracefully without errors or false flags.

## Flag List Action Button Audit

**Goal:** Ensure every `?flag=X` list view has consistent, correct action buttons matching the style and behaviour of `?state=new`.

**Current Status & Tasks:**
- [ ] [FL.1] `?flag=count_updated` — pressing Accept removes the row and shows `{"success": true}` in the first column instead of a proper inline response. Needs the same dismiss/inline behaviour as other flags.
- [ ] [FL.2] `?flag=count_updated` — Accept button style and format does not match `?state=new`. Button styling must be made consistent across all flag views.
- [ ] [FL.3] `?flag=no_series` — shows two Accept buttons. One must be removed.
- [ ] [FL.4] Audit every `?flag=X` option end-to-end: verify action buttons are correct (right actions, right labels, right styles, no duplicates, no missing buttons).

## Future Improvements

**Goal:** Track nice-to-have features and enhancements that are not yet prioritised.

**Current Status & Tasks:**
- [ ] [FI.1] PDF to CBZ conversion. Currently `convert_cbr` only handles CBR/CB7 (archive re-pack). PDF conversion requires rendering each page to an image (e.g. via `pdf2image` / Ghostscript), which is a separate, non-trivial operation. Would allow PDFs flagged `is_pdf` to be converted in-place rather than only deleted or suppressed.

## Code to Port

**Goal:** Ensure all relevant ComicRack scripts and logic are properly integrated or reimplemented in ComicManager.

**Current Status & Tasks:**
- [x] [CP.1] Confirmed CVIssueCount script equivalent implemented (`Issue count management`).
- [x] [CP.2] Confirmed ComicInfo.xml / Write-to-File equivalent implemented (`ComicInfo.xml output parity`).
- [x] [CP.3] Confirmed Library Organizer config equivalent implemented (`Organizer profile rule editor`).
- [x] [CP.4] Confirmed DataManager file equivalent implemented (`ComicDb.xml import support`).
- [ ] [CP.5] Thoroughly verify that existing implementations fully replicate the functionality of ComicRack script counterparts, ensuring all nuances are handled.
