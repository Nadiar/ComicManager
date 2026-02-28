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
- [ ] [P1.11] Implement a manual entry form (Django admin or a custom UI) to add physical comic records (`medium=physical`, no file).
- [ ] [P1.12] Research and implement bulk import functionality for physical comics from CSV/spreadsheet.
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
- [ ] [P2.7] Implement mechanism to mark comics for later scraping (`skipped` flag or `CVDBSKIP`).
- [x] [P2.8] Implement rescrape logic for comics with `CVDB` note (or error flags) but missing `comicvine_issue`.
    *   *Analysis:* Existing `scrape_all` task already clears error flags and retries comics in the `IMPORTED` state. Individual re-scrape is available via UI.
- [ ] [P2.9] Implement metadata-only matching for physical comics, leveraging the same queue system but bypassing hash-based matching.
- [x] [P2.10] Confirmed all ComicVine fields are stored correctly and `scrape_source` is recorded.
- [x] [P2.11] Confirmed `Comic.state` is updated to `counted` (as `scraped` state was removed).
- [ ] [P2.12] Implement explicit prioritization/workflow for scraping TPBs and Director's Cuts *before* general scraping.
- [ ] [P2.13] Implement metadata-only matching for physical comics.

### Phase 3: Issue Count (Comicrack_guide 04 - Add Count)

**Goal:** Populate and manage `count` for series, identifying and resolving discrepancies.

**Current Status & Tasks:**
- [x] [P3.1] Implemented `Issue count management` (detect, populate missing counts from local CV DB, auto-flag `missing_count`, detect `count_mismatch`).
- [ ] [P3.2] Leverage existing `Issue count management` to create a Celery task to retrieve and update `count` for `comicvine_volume`, and populate `comicvine_issue_count` custom field.
- [ ] [P3.3] Implement a smart list for comics where `count` is null or `comicvine_issue_count` is missing.
- [ ] [P3.4] Implement a smart list to detect comics sharing a `comicvine_volume` but having differing `count` values, with an action to re-run the CVIssueCount task.

### Phase 4: Publisher Management / Data Manager (Comicrack_guide 05 - Data Manager)

**Goal:** Manage publishers, apply tagging rules, and enrich comic metadata.

**Current Status & Tasks:**
- [x] [P4.1] Confirmed `ComicDb.xml import support` enriches imports with data including `MainCharacterOrTeam`, `SeriesGroup`, `CustomValuesStore`.
- [x] [P4.2] Confirmed `Organizer profile rule editor` provides UI for creating and editing matching rules.
- [x] [P4.3] Confirmed rules populate `series_group`, `main_character_team`, `first_series`, `datamanager_processed`.
- [x] [P4.4] Confirmed rules are stored in DB and are editable via UI.
- [ ] [P4.5] Implement mechanism to "Surface comics from publishers not yet in the system; prompt keep or delete."
- [ ] [P4.6] Implement UI for "Publisher config: maintain 'known publishers' list with associated tagging rules."
- [ ] [P4.7] Implement/verify built-in rule sets for Marvel and DC within the existing rule editor.
- [ ] [P4.8] Continue development of experimental Star Wars ruleset (WIP).

### Phase 5: Format Tagging (Comicrack_guide 06 - Format)

**Goal:** Automatically and manually assign format tags (TPB, Director's Cut, One-Shot, etc.) based on filename, title, and count rules.

**Current Status & Tasks:**
- [x] [P5.1] Implemented auto-tag from filename/title keywords and rule-based detection from Series + Title fields.
- [x] [P5.2] Implemented count-range rules: One-Shot (count = 1), Limited Series (count 2–15), Main Series (count > 15).
- [x] [P5.3] Implemented manual format assignment with confirmation (via `Detail page actions now show result modals`).
- [x] [P5.4] Implemented `Search, filter, and sort for comic list`.
- [x] [P5.5] Implemented `Auto-scan page count on comic detail`.
- [ ] [P5.6] Implement a `format_ok` boolean field on the `Comic` model to suppress false positives in smart lists.
- [ ] [P5.7] Implement smart list/logic to detect mismatched formats within the same `comicvine_volume`.
- [ ] [P5.8] Implement smart list/logic to detect scraping conflicts (same Series + Volume + Format, different `comicvine_volume`).
- [ ] [P5.9] Implement smart list/logic to surface comics with no format set.
- [ ] [P5.10] Implement smart list/logic to detect format upgrades for ongoing series (One-Shot → Limited → Main Series).
- [ ] [P5.11] Implement smart list/logic to flag comics whose format changed and need re-organizing.
- [ ] [P5.12] Refine existing rules for TPB, Omnibus, Director's Cut, etc. to avoid mis-tagging.
- [x] [P5.13] Fixed search/filter bar on `/comics/?state=new` — see P1.19.
- [ ] [P5.14] We need to show page count, so we can see if we talk about TPB or limited series on low issue count. 

### Phase 6: Duplicate Detection (Comicrack_guide 07 - Duplicated)

**Goal:** Identify and manage duplicate comic entries to maintain a clean collection.

**Current Status & Tasks:**
- [x] [P6.1] Confirmed pre-move gate blocks comics with `is_duplicate=True`.
- [x] [P6.2] Implemented duplicate detection by `comicvine_issue`, series + number + volume match, pHash / aHash similarity, and filename patterns.
- [x] [P6.3] Confirmed "Digital + Physical same CV ID is explicitly NOT a duplicate" rule.
- [x] [P6.4] Implemented duplicate resolution UI with side-by-side comparison and actions (keep/soft-delete/delete).
- [x] [P6.5] Implemented soft-delete only (`is_duplicate=True`, `duplicate_of` FK set).
- [ ] [P6.6] Implement an audit log entry for every duplicate resolution decision.
- [ ] [P6.7] Duplicate Review needs better explenation for what Keep, Re-Q, Del does. Right now if we say Keep on one of the pairs, the other set just disappeard, so the user should delete the one they dont want. 

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
- [ ] [P7.8] Implement logic to detect Alternate Universe comics that gained a `Main Character or Team` and trigger their re-organization.
- [ ] [P7.9] Ensure physical comics participate in path calculation (catalogue display) but *without* performing any file moves.
- [ ] [P7.10] Implement robust logging for file processing errors (e.g., "Invalid or corrupted CBZ file", "No ComicInfo.xml") to a dedicated log file or application error reporting.
- [ ] [P7.11] Externalize Docker paths for `library` and `untagged` directories, and the `PORT` variable, into a `.env` file.

### Phase 8: Write to File (Comicrack_guide 09 - Write to File)

**Goal:** Update `ComicInfo.xml` within CBZ files with the latest metadata when changes occur.

**Current Status & Tasks:**
- [x] [P8.1] Implemented detection of missing or outdated `ComicInfo.xml`.
- [x] [P8.2] Implemented writing `ComicInfo.xml` into CBZ on demand only (user-triggered).
- [x] [P8.3] Implemented tracking `last_written` timestamp and show staleness indicator.
- [x] [P8.4] Confirmed physical comics are skipped.
- [x] [P8.5] Implemented Celery notifications for `Write to File` and confirmed `force_write` advances state.
- [x] [P8.6] Implemented `ComicInfo.xml output parity` (XML matches ComicRack format, includes `DataManager_Processed`, standard fields).
- [ ] [P8.7] Embed UUID as a custom field in `ComicInfo.xml` for re-linking records if files move.
- [ ] [P8.8] Implement validation before allowing `ComicInfo.xml` to be written, ensuring all required metadata fields are populated.

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
- [ ] [SL.P1.1] **Phase 1 Smart Lists:** 1.2 — Page Count Too Low (digital, `page_count < 5`)
- [ ] [SL.P1.2] **Phase 1 Smart Lists:** 1.3 — PDF Files (`file_format = 'pdf'`)
- [ ] [SL.P1.3] **Phase 1 Smart Lists:** 1.4 — Unparseable Filename (`proposed_series` is null)
- [ ] [SL.P1.4] **Phase 1 Smart Lists:** 1.7 — Standalone Covers (`page_count <= 3` + "cover" in filename)
- [ ] [SL.P5.1] **Phase 5 Smart Lists:** Format Mismatches (same `comicvine_volume`, different `format`)
- [ ] [SL.P5.2] **Phase 5 Smart Lists:** CV Volume Conflicts (same Series+Volume+Format, different `comicvine_volume`)
- [ ] [SL.P5.3] **Phase 5 Smart Lists:** Missing Format (`format` is null)
- [ ] [SL.P5.4] **Phase 5 Smart Lists:** Format Upgrades Needed (`count` increased, `format` should change)
- [ ] [SL.P6.1] **Phase 6 Smart Lists:** Duplicates by CV Issue (digital only)
- [ ] [SL.P6.2] **Phase 6 Smart Lists:** Duplicates by Series+Number+Volume
- [ ] [SL.P6.3] **Phase 6 Smart Lists:** Duplicates by pHash similarity
- [ ] [SL.P8.1] **Phase 8 Smart Lists:** Missing ComicInfo.xml
- [ ] [SL.P8.2] **Phase 8 Smart Lists:** Stale Metadata (DB newer than `last_written`)
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
- [ ] [UI.7] Further develop a visual pipeline funnel and counts per smart list on the dashboard.
- [ ] [UI.8] Consolidate and enhance existing settings into a single, comprehensive settings UI for templates, publisher rules, and API keys.
- [x] [UI.9] Batch audit log at `/settings/log/` — filterable by action (Scrape/Tag/Format/Organize/Write/Audit), per-comic changes diff, copyable UUID, rollback buttons. Log written to `./data/logs/batch_actions.jsonl`. Audit entries include a "To Scrape" rollback button to reset bad matches. Log entries are only written when a flag is newly added or cleared (not on repeated re-runs). All pipeline stages now log: `scrape_all`, `tag_all`, `format_all`, `organize_all` (records old/new path), `write_all` (records comicinfo write), `audit_metadata`.
- [ ] [UI.10] Implement functionality to export comic metadata as JSON for individual comics and potentially in bulk.
- [ ] [UI.11] Enhance global search to return both digital and physical comics, clearly indicating the medium with a "medium badge".
- [ ] [UI.12] Ensure all smart lists have full pagination, sorting, and column toggling capabilities.
- [ ] [UI.13] Extend existing bulk actions framework to encompass more granular bulk actions like delete file, flag ok, etc.
- [ ] [UI.14] Add search functionality for minor characters and main characters to the comic table.
- [x] [UI.15] ComicVine API-only mode when comicvine.db is absent. Auto-detects DB/MCL availability. Batch scraping falls back to API search (try_api_metadata_match). Series Audit uses latest.mcl CSV fallback (mount ./data/latest.mcl; format: one row per volume, semicolon-delimited, comma-separated issue IDs and numbers). API call budget tracked in Redis (200/hour). Dashboard banner shows mode + remaining calls. Settings page shows data source status. Series Audit disabled (with message) when neither DB nor MCL is available. Unified find_best_match() entry point in services.py replaces scattered if-db-available branches in tasks, views, and management command. Scrape modal views (scrape_preview, scrape_comic, force_scrape) now guard all DB calls with is_cv_db_available() to prevent 500 errors. enrich_match_with_credits() no longer crashes when DB is absent. Celery task stops gracefully (with user-visible message) when API budget is exhausted mid-run.
- [ ] [UI.16] character_audit_search opens a new SQLite connection per volume in a loop (N+1). For characters with many volumes this will be slow. Consider batching the CV DB lookups in a single connection inside get_volume_completion or a new bulk variant.
- [ ] [UI.17] Edit comic needs a 'clear flag'. 
- [ ] [UI.18] ALL popups needs to use a custom modal and not browser based popup. 
- [ ] [UI.19] Edit comic needs a save to DB (where we skip saving to XML), as we can alwyas use the re-write option later on. 

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
- [ ] [BUG.9] Ensure `Summary` and `Notes` fields are multi-line in UI, especially in "Compare All Sources" and "Metadata Comparison" tables.
- [ ] [BUG.10] Implement validation to prevent saving tagging rulesets without a modifier and show an error.
- [ ] [BUG.11] Add a button/action to refresh all file & system info (hashes, page count, filesize).
- [ ] [BUG.12] Verify and implement specific handling of warnings for data-destructive operations in Celery tasks (tell user, finish current comic, stop next).
- [ ] [BUG.13] When a comic has flag scrape_no_match and is re-scraped, the flag is not removed, even though the comic moves on to the next stage.
- [x] [BUG.14] Fixed corrupted/truncated CBZ files causing blank detail pages and missing page counts. Comics with unreadable archives are now flagged `corrupted_archive` at import and on first detail-page visit. A "Try Rezip" action on the detail page recovers readable entries and repacks the archive in place; if too damaged, the user is prompted to delete and reimport.

## Code to Port

**Goal:** Ensure all relevant ComicRack scripts and logic are properly integrated or reimplemented in ComicManager.

**Current Status & Tasks:**
- [x] [CP.1] Confirmed CVIssueCount script equivalent implemented (`Issue count management`).
- [x] [CP.2] Confirmed ComicInfo.xml / Write-to-File equivalent implemented (`ComicInfo.xml output parity`).
- [x] [CP.3] Confirmed Library Organizer config equivalent implemented (`Organizer profile rule editor`).
- [x] [CP.4] Confirmed DataManager file equivalent implemented (`ComicDb.xml import support`).
- [ ] [CP.5] Thoroughly verify that existing implementations fully replicate the functionality of ComicRack script counterparts, ensuring all nuances are handled.
