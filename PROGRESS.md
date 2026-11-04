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
- [x] [P1.20] Implement logic to identify `.zip` and rezip them to `.cbz` if user wants. Use Review Queue like [P1.5].
- [x] [P1.21] Verified: `is_zip` does not block batch scraping. `scrape_all_task` only excludes `scrape_skipped` and inducks-sourced comics — `is_pdf`, `low_page_count`, and `needs_conversion` are not excluded either. ZIP files are valid comic archives and can be scraped for metadata normally; the rename to `.cbz` is a separate step. No change needed.
- [x] [P1.22] Workflow pipeline step 1 (New) should show an action button for "Convert to CBZ" when any comics in the new state are in CBR or CB7 format — similar to the "Needs Conversion" row in the Review & Maintenance card.
- [x] [P1.23] Removed the unused `import_convert_cbr` setting. CBR/CB7 files are always flagged `needs_conversion` unconditionally. A future improvement (FI.8) tracks making this configurable.
- [x] [P1.24] On `/comics/?state=new` we need a 'Scan for Comics' button next to the other buttons like 'Convert All CBR' and 'Rename All ZIP'.
- [x] [P1.25] RAR and 7-Zip archives named `.cbz` or `.zip` were reported as corrupted, or a `.zip` was renamed into a broken `.cbz`. The untagged scan now detects the real format and flags such files for conversion; Convert and Rezip turn them into real CBZ files, and the original is only replaced once the new archive is complete and contains pages. Fixed in v1.1.0.
- [x] [P1.26] `convert_misnamed_archives` command converts RAR or 7-Zip archives named `.cbz` in the library in place (`--dry-run`, `--path`). `import_library` skips such files and points to the command. Added in v1.1.0.
- [x] [P1.27] The untagged scan deleted the record of every comic whose file was missing, scraped and hand-edited metadata included, for example when the disk was not mounted. Only untouched New comics are removed now; the others get the `file_missing` flag, which clears itself when the file is back. If the folder looks unmounted, nothing is changed. The scan also finds uppercase extensions, skips hidden files and reports how many comics were removed, flagged or found again. Fixed in v1.1.0.
- [x] [P1.28] CBR conversion deleted the original without converting it when a CBZ with the same name already existed. It now refuses and keeps both files. Fixed in v1.1.0.
- [x] [P1.29] A conversion that is killed halfway left a hidden `.cm-convert-*.tmp` file next to the original (`apps/core/archives.py`), and its extracted pages in the container's temp folder. Fixed in v1.2.0: when the worker starts, `remove_convert_leftovers` deletes the temp file next to each comic still flagged `needs_conversion` and the `cm-convert-*` folders in the temp folder. (Gitea #6)
- [x] [P1.30] The filename parsers (`parse_filename` in `scan_untagged.py`, `_parse_filename` in `apps/core/services.py`) do not know the ComicRack-style date in brackets: `Saga #040 [November, 2016].cbz` gives the series `Saga [November, 2016]` and no year. Strip `[Month, Year]` and `[Year]` and read the year from it. Fixed in v1.1.2: `parse_filename` (`apps/core/services.py`, now also used by `scan_untagged`, whose copy was removed) reads the year from `[Month, Year]` or `[Year]` when there is none in parentheses, and strips every bracketed group. All 49 sandbox comics parse.

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
- [x] [P2.15] Workflow pipeline step 2 (Scrape) should show two separate counts: all scrapeable comics (excluding scrape_skipped) and skipped comics. The "Scrape All" action button should be disabled (or hidden) when all remaining comics in that state have `scrape_skipped=True`.
- [x] [P2.16] Verified: `scrape_0day_hours` IS read in `apps/dashboard/views.py` to calculate `new_comics_0day_count`, which powers the "Last Xh (N)" button on the dashboard New Comics card. Clicking it runs the pipeline only on comics imported within that window. Not a Celery priority queue, but the setting is actively used.
- [x] [P2.17] ComicVine API calls were only spaced 1.1 seconds apart within one scraper instance, and the call budget was counted separately by the web and worker processes. Both are shared across processes now (see FI.6). Fixed in v1.1.0.
- [x] [P2.18] Publisher allow and block lists for auto-match (`scrape_publisher_allow`, `scrape_publisher_block` under Settings > Scraping). Auto-match only accepts publishers on the allow list and never picks one on the block list; manual search still shows them. Added in 98d8962, after v1.1.0 was tagged (see DOC.9).
- [x] [P2.19] Scraping failed with comicvine.db files that store cover hashes as signed SQLite integers: the negative hashes raised `OverflowError` while loading the hash cache, outside its try, so the scrape window showed `Unexpected token '<' ... is not valid JSON` and cover matching did not work. Hashes are masked to unsigned 64-bit now, and a hash table that can't be read turns off cover matching instead of stopping the scrape. Fixed in v1.1.2 (Gitea #8).
- [x] [P2.20] `scrape_preview` had no error handling, so any error reached the scrape window as invalid JSON, and the Search API section only opened after a successful preview. It now returns the reason as JSON together with the comic, logs the traceback to the container log, and the scrape window keeps Search API open so the comic can still be matched by hand. Fixed in v1.1.2 (Gitea #8).
- [x] [P2.21] `is_cv_db_available` (`apps/scraper/cv_sources.py`) only checks the `cv_volume` table, and `enrich_matches_with_covers` and `get_all_covers` (`apps/scraper/comicvine.py`) queried `comic_covers` with no fallback, so a comicvine.db without that table failed the scrape preview and Search Alt Covers instead of skipping the covers. Fixed in v1.2.0: both check for the table (`_has_covers`) and skip it; the hash match already turned itself off (empty hash cache), and Search Alt Covers falls back to the API.
- [x] [P2.22] The automatic API match gives up on comics the manual search finds. `try_api_metadata_match` searches volumes by series name (top 10), keeps only the single best-scored volume (series plus a start year within 2 of the comic's year) and looks up the issue number in that volume only, so a wrong volume pick (relaunches with the same name) ends the search. It also rejects matches with a cover hash distance over 15 (variant covers) and stops silently when the 200/hour budget is used. The manual search searches issues with "series number year" directly. Fix: try the next 2-3 scored volumes when the issue is not in the first, and record why the API path gave up in `scrape_error_detail`. Note that `scrape_api_fallback` is off by default, so without it a comic missing from the local comicvine.db is never looked up automatically. (Reported on Reddit) Fixed in v1.1.2: `rank_api_volumes` ranks up to 30 volume results (started after the comic last, fewer issues than its number next, then score, start year closest to the comic's year, ComicVine's order), the issue is looked up in the best 3, then `search_api` with "series number" (same number, score 3 or more, up to 3 results). Every issue found gets the cover check before `/issue` is fetched, so a comic found in the first volume still costs 3 calls, at most 6. Every give-up stores its reason in `scrape_error_detail`, also when the local DB found nothing and API fallback is off, and `workflow.scrape` puts it in the no-match message. Tested live on 8 comics with same-name volumes: 6 matched correctly (the old code: 2), each with 3 calls.
- [ ] [P2.23] Match series names with and without a leading "The", "A" or "An" in `match_by_metadata` (`apps/scraper/comicvine.py`), tried only when nothing else matched. Example: "The Snowpiercer" #1 should find "Snowpiercer" #1.
- [ ] [P2.24] Use the in-store date instead of the cover date for chosen publishers (Gitea #11). Marvel and DC cover dates run about three months ahead, which breaks "recently released" views in Komga. The scraper sets Year, Month and Day from `cover_date` only (`apply_cv_match`); `store_date` exists in comicvine.db's `cv_issue` table and in the API but is never read (not in the local queries or the `get_issue_from_api` field list). Plan: store the store date when scraping and add a Scraping setting listing the publishers that use it (matched like the publisher allow and block lists), falling back to the cover date. Already scraped comics need a rescrape, or a command that fills it from comicvine.db by `comicvine_issue`. Planned together with UI.37.
- [x] [P2.25] Layer 2 (`match_by_metadata` in `apps/scraper/comicvine.py`) compares the comic's year with the volume's start year, but a comic's year is usually its cover year. For an issue from a later year than its volume's first, the exact query finds nothing and the LIKE query takes the volume with the most issues and that number, with no score and no cover check (Batman #100 from 2020 can match the 1940 run). Names are also compared as written (`Batman: Year One` does not find `Batman Year One`). Fix: rank like `rank_api_volumes` (start year at or before the comic's year, closest first) and check the cover hash of the chosen issue against `comic_covers`. Fixed in v1.1.2: `match_by_metadata` no longer filters on the start year; it sorts by `year_gap` (cover year or volume start year, whichever is closer). `try_metadata_match` takes the first issue whose cover in comicvine.db agrees (`covers_agree` via `scraper.cover_hashes`, from the hash cache), else the first when its year is within 2, or for a comic without a year only when one volume has the number, and stores the reason otherwise. The dry run preview uses it. Sandbox, Layers 1 and 2 on 49 comics: 43 right and 2 wrong (old code: 40 and 5).
- [x] [P2.26] The API cover check (`_verify_cover_hash`) needs both distances within 15, so a correct issue just over it is rejected: Guardians of the Galaxy (2020) #14 had pHash 16 and aHash 5. Consider accepting when one distance is well inside and the sum is within 30, and test it against wrong issues with the same number. Fixed in v1.1.2: `covers_agree` (pHash + aHash <= 28, `COVER_MATCH_MAX_SUM`) for the API check and Layer 2. Measured on 1,485 random library comics against the right issue and 2,003 same-name same-number issues: both <= 15 accepted 92.1% right and 30 wrong, sum <= 28 95.4% and 31, sum <= 30 95.8% and 33. Guardians of the Galaxy #14 now matches through the API with 3 calls.
- [x] [P2.27] Layer 1 broke a tie between candidates with the same score by the smaller hash distance, so a reprint with the same cover could win: Star Wars #45 (2018) matched the Planeta DeAgostini edition (2019) instead of Marvel's, and Planet of the Apes/Green Lantern #1 (February 2017) the TPB from November 2017. Fixed in v1.1.2: `hash_match_rank` sorts by score, then `year_gap`, then `month_gap` (the comic's Month, or the month of a ComicRack date in its filename, `comic_date`), then the hash distance. `try_hash_match`, the dry run preview (which now shows the cover date), the scrape window's list and `manage.py scrape --method hash` use it. `manage.py scrape --method metadata` still had the old Layer 2 and now calls `try_metadata_match`. Measured on 1,500 random library comics (series, number and date from the filenames, no publisher lists): Layer 1 picked 11 wrong issues with the old order, 5 with the year and 2 with the year and month, mostly Panini, Planeta DeAgostini and Editorial Televisa reprints, and no right pick became wrong. For the 2 left, the right issue is not among the cover candidates. In the sandbox, Scrape All matches all 45 comics whose names are in comicvine.db (was 43 right, 2 wrong).
- [ ] [P2.28] Show each match's volume issue count in the scrape window ("Marvel (2015) · 1 issue"), so an annual or one-shot can be told from the ongoing series with the same cover. `CVMatch.issue_count` is known for local matches, but `_scrape_preview` and the direct lookup in `scrape_api_search` (`apps/core/views.py`) leave it out, and the card ignores the count `scrape_volume_batch` already returns. Also link each match to the issue on ComicVine. (Gitea #15)
- [ ] [P2.29] The ComicVine search boxes take a whole ComicVine URL: the scrape window's API search only takes `4000-<id>` (`re.fullmatch` in `scrape_api_search`), and the Smart List form's volume search only takes names. (Gitea #15)
- [ ] [P2.30] Make the scrape window fill most of the screen with much bigger covers, keeping the text size. At 1920x1080 the window is 936 px wide and a match cover 108x148 px (`templates/partials/modals/_scrape.html`, `_scrapeCard` in `static/js/scrape.js`). (Gitea #15)
- [ ] [P2.31] Page buttons and the page count on the current file in the scrape window, to skip a scanner's credit page and tell a 25-page issue from a 200-page annual. (Gitea #15)
- [ ] [P2.32] A volume filter in the scrape window: paste a ComicVine volume URL or ID, or pick a volume by name, and the window only offers that volume's issue with the comic's number (plus cover matches from that volume) until it is cleared. It stays set from comic to comic in the Confirm-each loop. (Gitea #15)


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
- [-] [P4.9] (Moved to FI.4) Ruleset export from DB state.
- [x] [P4.10] When clicking "Create Ruleset" from an uncovered publisher on `/tagging/publishers/`, pre-fill the group path as "Publishers to keep" and add a default action: `SetValue` on `Publisher` with the publisher name as the value. This makes new publisher rulesets usable without any manual setup.
- [x] [P4.11] `import_library` fixes: with `--comicdb`, files without a ComicInfo.xml are imported from their ComicDb.xml entry instead of being skipped; `.CBZ` files with an uppercase extension are found; a dry run reports how many comics it would import instead of 0; running it as the container user no longer fails (its error log is `data/logs/import_errors.log`). Fixed in v1.1.0.
- [x] [P4.12] Imprint is a standard field. The `<Imprint>` element was dropped on import and never written, so ComicRack templates like `{<publisher>}/{<imprint>}/{<series>}` could not be used. It is now read from and written to ComicInfo.xml, editable on the edit page, and works as the `{<imprint>}` organizer variable, a profile condition, a tagging rule field, a Smart List filter and in CBL import and export (`ComicBookImprintMatcher`). Migration 0022 moves an `Imprint` custom value into the field, and a changed imprint marks the comic for reorganizing. Added in v1.1.2.
- [x] [P4.13] `backfill_imprint` command fills in the Imprint of comics imported before v1.1.2 from their ComicInfo.xml (`--dry-run` lists the changes). It only reads the files and never changes a comic that already has an imprint. Added in v1.1.2 (Gitea #9). Renamed to `backfill_from_files`, which also fills in the Story Arc (P4.16).
- [x] [P4.14] `import_library --comicdb` only matches ComicDb.xml entries whose path starts with `B:\Comics\ComicRack\` (`COMICDB_STRIP_PREFIX` in `apps/core/management/commands/import_library.py`). Anyone else gets no enrichment and no imports from ComicDb.xml, while the docs describe it as general. Fix: match each Book's path by its end against the scanned files (longest match first, report ties), or add a `--comicdb-root` option. Fixed in v1.1.2: `match_comicdb_paths` matches each Book path by the longest end that is a scanned file, so ComicRack's folder is found for any library and with `--path` set to a subfolder. The output lists the folders found with their file counts; when a file is under more than one, the folder with the most matches wins. `--comicdb-root` (repeatable, first wins) sets the folders by hand, and when nothing matches the command stops before importing anything.
- [x] [P4.15] `import_library` did not decode ComicRack's escaping in ComicDb.xml's `CustomValuesStore`, so names and values that contain a comma or `=` came in encoded (`Black&#44; White & Red`; 6 such values in the real ComicDb.xml, all Star Wars `SW`). Splitting on raw commas was right, since ComicRack escapes them inside values. Fixed in v1.2.0: `decode_custom_value` decodes numeric character references after splitting, and migration 0023 decodes values imported before (and bumps `updated_at`, so written files show as stale).
- [x] [P4.16] `import_library` had its own ComicInfo field map (`parse_comic_info_xml`) instead of using `FIELD_MAP` in `apps/core/utils.py`, and it left out `StoryArc`, so story arcs in existing files and in ComicDb.xml were not imported, and Write to CBZ then replaced the files' ComicInfo.xml without them. Fixed in v1.1.2: the import uses `FIELD_MAP`, and `backfill_from_files` fills in the story arcs of comics imported earlier.
- [x] [P4.17] `RegExVarReplace` and `RegExVarAppend` turned every `(?<` into `(?P<` (`apps/tagging/engine.py`), which also broke lookbehinds `(?<=` and `(?<!`: a ruleset with a lookbehind raised `re.error` and did nothing. Regex conditions did not convert .NET named groups at all, so a condition with `(?<name>...)` never matched. Fixed in v1.2.0: `_python_regex` converts only `(?<` followed by a name, for the actions and the conditions.
- [ ] [P4.18] RegEx rules write the capture into the action's field. ComicRack's Data Manager seems to write it into the custom value named by the group (old organizer profiles use `{<Custom(SW)>}`). Check in ComicRack and match it.
- [ ] [P4.19] Rulesets created in the UI get the highest priority, so they run after the Clean-Up rulesets (a main character set by a new ruleset comes too late for "Alternate Universes" and "Cleanup: Processed"). Let the user place a new ruleset, or document it.
- [ ] [P4.20] The rule editor has a fixed field list, so a custom value like `Custom(Franchise)` cannot be set from a ruleset made in the UI, while the Franchise-first example in `docs/guide/organizing.md` relies on one. Allow custom value keys in the rule editor, or change the example.

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
- [x] [P5.15] Add a button in the workflow nav bar (pipeline steps) for the Format Review page (`/comics/format/`), so users can navigate directly to it from any stage without hunting in menus.
- [x] [P5.16] Format Review page (`/comics/format/`) needs a "Detected Format" column alongside the existing "Current Format" column, so users can see what the system would assign before accepting. Column is labelled "Suggested Format".
- [x] [P5.17] Under `/comics/format/`, the "### Needs Re-format" section should be collapsible (fold in/out), so users can hide it when not needed.
- [x] [P5.18] Format detection should recognise "Preview" and "Previews" in the issue title as a distinct format (or flag), so comics like "Spider-Man Preview" are not mis-tagged as a regular series issue.

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
- [x] [P6.11] Duplicate detection fixes: new comics are compared against comics kept or marked intentional in earlier duplicate groups (before, a new copy of such a comic was never detected); deduplicating a batch no longer creates groups among old library comics and is faster; cover-hash groups no longer chain loosely similar covers together. Fixed in v1.1.0.

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
- [x] [P7.11] Externalize Docker paths for `library` and `untagged` directories, and the `PORT` variable, into a `.env` file. `UNTAGGED_DIR` and `LIBRARY_DIR` added to both compose files with defaults so existing setups are unaffected. `.env.sample` created documenting all required variables.
- [x] [P7.12] TPB folder path improvements: numeric rule operators (`greater than`, `less than`, etc.) added to profile matching engine, along with `Count` and `Page Count` fields. Indexed credit field access added to template engine (`{<writer[1]>}`, `{<writer[1][l]>}`, etc.). Two-profile pattern documented in `docs/guide/organizing.md`: Profile 1 matches `Format is TPB AND Count greater than 1` and groups into `{<series>} ({<volume>})` subfolder; Profile 2 catches remaining TPBs and uses `{ by <writer[1][l]>}` in the filename.
- [x] [P7.13] Drag-and-drop priority reordering on the organizer profiles list. Drag handle column added to the table; native HTML5 drag-and-drop reorders rows live and persists via `POST /organizer/profiles/reorder/`.
- [x] [P7.14] When using the CLI import command on an existing library, errors such as "Error processing X.cbz: Invalid or corrupted CBZ file" and informational lines like "No ComicInfo.xml in: X.cbz" are only printed to stdout and lost. These should be written to a persistent log file (e.g. `data/logs/import_errors.log`) so they can be reviewed after a large import run without having to keep the terminal open.
- [x] [P7.15] AU (Alternate Universe) comics that later gain a `main_character_or_team` value should be detected and moved to their correct publisher folder. Currently `needs_reorganize` is set when the field changes (P7.8), but there is no dedicated detection pass that scans organized AU comics for a newly populated main character and re-queues them.
- [x] [P7.16] Check that Path Audit (`/organizer/path-audit/`) only shows and runs on comics in stage `Write to CBZ` or `Done`, as any other stage is in the pipeline where we will get to `Move Files` later on. Path Audit is meant as a way to audit files already organized and through the pipeline. 
- [x] [P7.17] Path Audit offered comics whose files are missing for a move. They now get the `file_missing` flag and are listed in a separate Missing files table with Relink (find the file in the library) and Remove (delete only the record; refused if the file is back). The flag shows in the Review Queue and as a Smart List field. Added in v1.1.0 (Gitea #4).
- [x] [P7.18] Organizer moves could overwrite an existing file and leave partial copies. Moves never replace a file now, and moves between the untagged folder and the library copy through a hidden temporary file, so an interrupted move never leaves a half-copied comic. Fixed in v1.1.0.
- [x] [P7.19] The built-in Default profile filed every comic that matched none of the user's profiles under `[publisher]/[series]`. A migration corrects it if it still has the original templates. Fixed in v1.1.0.
- [x] [P7.20] Path Audit fixes: the list of comics to reorganize was empty; Sync Paths covers Done comics and no longer matches a different series that starts with the same name; the Correct Location count shows a number; the result says how many files are missing. Fixed in v1.1.0.
- [x] [P7.21] Move Files failed with `[Errno 1] Operation not permitted` on every filesystem without hard links (SMB/CIFS, exFAT, Windows drives under Docker Desktop), because `_safe_move` hard-linked the temporary copy into place. The copy is now renamed into place after checking that nothing exists under that name (`rename_no_clobber`). The original was never touched by the failed moves. Fixed in v1.1.2 (Gitea #10).
- [x] [P7.22] A failed Move or Re-organize only showed its reason on the page: `organize_comic` turned the exception into a message, and the Audit Log only recorded file conflicts. Every failure, including a missing source file, now adds an `organize_error` entry with the reason, and file system errors are written with their traceback to the container log (`web` for the comic page, `worker` for batch actions). Fixed in v1.1.2 (Gitea #10).
- [x] [P7.23] A `.lop` import keeps ComicRack's Windows base folder (for example `B:\Comics\ComicRack`). Move Files then treats it as a folder relative to `/app`: as UID 1000 every move fails with Permission denied, and as root the original is deleted and the only copy is inside the container. Path Audit flags every comic those profiles match. Fix: in `parse_profile` (`apps/organizer/parser.py`), replace base folders with a drive letter, backslashes or anything outside `/comics/library` with `/comics/library`, and list the changed profiles in the import result. Only a docs warning so far (DOC.4). Fixed in v1.1.2: when a `.lop` file has base folders outside `/comics/library`, the import page opens a window where the user clicks the last part of each path to replace, sets the replacement (default `/comics/library`) and whether backslashes become slashes, and sees the new base folder before importing. The server applies the same rule (`map_base_folder`, `apply_base_folder_map` in `apps/organizer/parser.py`) and imports nothing while any base folder would still be outside the library folder.
- [x] [P7.24] Refuse to move a comic when its profile's base folder is outside `/comics/library`. `_safe_move` cannot catch it, because its allowed root is that same base folder. Fixed in v1.1.2: `organize_comic` and `reorganize_comic` check `base_folder_error` (`apps/organizer/services.py`, against `settings.LIBRARY_DIR`) before creating any folder, the error names the profile and is logged as `organize_error`, and the profile list and the profile edit page warn about such profiles.
- [x] [P7.25] `sync_library_paths()` (shell and an unlinked POST endpoint, not in the UI) deleted a missing comic's record when its file turned out to belong to another record. Fixed in v1.2.0: it flags it `file_missing` instead, like the untagged scan (P1.27), so Path Audit offers to relink or remove it; the result reports `flagged_missing` instead of `removed_dupes`.
- [x] [P7.26] A move within one filesystem without hard links copied the whole file before renaming it (P7.21). Correct but slow. Fixed in v1.2.0: `_safe_move` (`apps/organizer/services.py`) renames the file itself with `rename_no_clobber` when the hard link fails with EPERM or ENOTSUP, and only copies across filesystems (EXDEV) or when that rename fails (a share that spans disks).

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
- [x] [P8.9] An interrupted ComicInfo.xml write (power loss, full disk, killed process) could leave an archive that would not open, even with Rezip. The archive index is backed up first (`.cm-index`), and an interrupted write is undone on the next write or with Rezip. On btrfs and XFS the patched copy is synced to disk before it replaces the original. Rewrites reuse the space of the old ComicInfo.xml instead of adding a copy to the archive on every write. Fixed in v1.1.0.
- [x] [P8.10] Write errors only said "Failed to write ComicInfo.xml": `write_comicinfo_xml` returned False for every error. It now raises with the reason, which goes into the `write_error` audit entry, the container log and the edit page's Save + Write XML message. A read-only file is reported as "File is read-only" before anything is changed, and no longer leaves a `.cm-index` file behind. Fixed in v1.1.2 (Gitea #7).
- [x] [P8.11] `restore_index_backup` (`apps/core/utils.py`) restored a leftover `.cm-index` at the start of every write, even when the file was changed or replaced since, which could break it. Fixed in v1.2.0: the backup also stores a digest of the first and last 64 KiB before the patch offset, and is only used when the archive does not open (an interrupted write always leaves it that way) and those bytes are unchanged; otherwise it is dropped with a warning. A valid archive with a backup means the write finished or the file was replaced. Backups from older versions (no digest) still restore, but only into an archive that does not open.
- [x] [P8.12] Rewriting ComicInfo.xml dropped the pages' `Bookmark`, `Type`, `DoublePage` and `Key` attributes (except the cover's), even when the pages were unchanged: `_build_pages_element` (`apps/core/utils.py`) built the Pages element from the image files only. Fixed in v1.2.0: the attributes in the file's current ComicInfo.xml are kept, matched to the images by `ImageSize` (written by ComicRack, and now by ComicManager too), so they follow their page after the page manager added, deleted or reordered pages; without `ImageSize` only by position and only when the page count is unchanged. The first page is always the only FrontCover. Files already rewritten lost them for good (the 49 sandbox files from the real library only had FrontCover left).
- [ ] [P8.13] Setting "Write ComicInfo.xml before moving", so a file lands in the library (for example a Komga library) finished. When on, `workflow.organize` writes into the file at its current path (with the deferred alt covers), then moves it and sets the state to Done; if the write fails, the file stays in Move. The write is already atomic and the full pipeline writes right after the move, so the gap is only long when Move Files and Write to CBZ run as separate batches. (Requested on Reddit)

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
- [x] [RE.8] The `needs_reorganize` signal (`apps/core/signals.py`) only flagged comics in Move or Write to CBZ, but Path Audit lists Write to CBZ and Done, so changing the publisher or series of a Done comic never flagged it. The profile template signal (`apps/organizer/signals.py`) had the same gap. Fixed in v1.2.0: both include Done (Re-organize already accepted it).
- [x] [RE.9] Only six fields marked a library comic `needs_reorganize` (`_PATH_RELEVANT_FIELDS` in `apps/core/signals.py`: publisher, imprint, series, format, main character, volume), but the profile templates can use many more (`TEMPLATE_FIELD_MAP`: number, year, title, story arc, writer...), so a profile with `{<storyarc>}` or `{#<number3>}` kept the old path when that field changed. Adding story arc to the six would have flagged every comic `backfill_from_files` gave an arc. Fixed in v1.2.0: `path_fields()` (`apps/organizer/services.py`) reads the fields and custom values that the templates (`template_fields`) and match rules (`rule_fields`) of every enabled profile and the Default profile use; the signal compares those. Any profile, not only the comic's own (decided by the user, 2026-10-30): Re-organize only clears the flag when the path is unchanged. One small query on the profiles per full save of a library comic; saves whose `update_fields` hold no field a profile could use read nothing.

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
- [x] [SL.4] Nested Smart List groups: groups can contain groups, up to three levels deep, each matching ANY or ALL of its filters, so lists like (A and B) or (C and D) can be built. Add OR Group became Add Group, and nested groups from a CBL import are no longer lost when the list is edited. Added in v1.1.0 (Gitea #3).

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
- [x] [UI.8] Consolidate and enhance existing settings into a single, comprehensive settings UI for templates, publisher rules, and API keys. Help text moved below inputs to fix line wrapping.
- [x] [UI.9] Batch audit log at `/settings/log/` — filterable by action (Scrape/Tag/Format/Organize/Write/Audit), per-comic changes diff, copyable UUID, rollback buttons. Log written to `./data/logs/batch_actions.jsonl`. Audit entries include a "To Scrape" rollback button to reset bad matches. Log entries are only written when a flag is newly added or cleared (not on repeated re-runs). All pipeline stages now log: `scrape_all`, `tag_all`, `format_all`, `organize_all` (records old/new path), `write_all` (records comicinfo write), `audit_metadata`.
- [x] [UI.10] Implement functionality to export comic metadata as JSON for individual comics and potentially in bulk. "Export as JSON" action added to comic detail page Actions dropdown — downloads all metadata fields, flags, custom values, and cover hashes as a named JSON file.
- [x] [UI.11] Enhance global search to return both digital and physical comics, clearly indicating the medium with a "medium badge". Physical comics show a "physical" badge next to the series name in the comic list when no medium filter is active.
- [x] [UI.12] Ensure all smart lists have full pagination, sorting, and column toggling capabilities. Smart list detail page now supports runtime sort via clickable column headers and column toggle dropdown (GET params override saved smart list defaults).
- [x] [UI.13] Bulk actions on filtered comic list. A "Bulk Action" dropdown appears on all comic list views with results. Actions: Scrape, Tag/Re-tag, Detect Format, Organize, Force Write, Suppress Flag (flag views only). Backend: `bulk_action_from_filter` view + `bulk_action_task` Celery task + `_run_scrape` / `_run_force_write` helpers. Reuses existing `_build_comic_list_queryset` to match exactly what the user sees. Inherits progress toast, cancellation, and stopped_early handling.
- [x] [UI.14] Add search functionality for minor characters and main characters to the comic table. Character search field added next to the main search bar with a "Main only" checkbox (on by default) — searches main_character_or_team when checked, or both main_character_or_team and characters when unchecked.
- [x] [UI.15] ComicVine API-only mode when comicvine.db is absent. Auto-detects DB/MCL availability. Batch scraping falls back to API search (try_api_metadata_match). Series Audit uses latest.mcl CSV fallback (mount ./data/latest.mcl; format: one row per volume, semicolon-delimited, comma-separated issue IDs and numbers). API call budget tracked in Redis (200/hour). Dashboard banner shows mode + remaining calls. Settings page shows data source status. Series Audit disabled (with message) when neither DB nor MCL is available. Unified find_best_match() entry point in services.py replaces scattered if-db-available branches in tasks, views, and management command. Scrape modal views (scrape_preview, scrape_comic, force_scrape) now guard all DB calls with is_cv_db_available() to prevent 500 errors. enrich_match_with_credits() no longer crashes when DB is absent. Celery task stops gracefully (with user-visible message) when API budget is exhausted mid-run.
- [x] [UI.16] character_audit_search opens a new SQLite connection per volume in a loop (N+1). Fixed via get_volume_completion_bulk() in dashboard/services.py: one SQLite connection, three batch IN queries (volumes, issues, covers), one PostgreSQL query for all owned comics across all volumes.
- [x] [UI.17] Edit comic needs a 'clear flag'.
- [x] [UI.18] ALL popups needs to use a custom modal and not browser based popup.
- [x] [UI.19] Edit comic needs a save to DB (where we skip saving to XML), as we can alwyas use the re-write option later on.
- [x] [UI.20] `/comics` table column selector now sorts columns alphabetically by label. Fixed by sorting `COLUMNS_REGISTRY` by `label` in the view before passing `all_columns` to the template.
- [x] [UI.21] `/comics` table search, filter, and sort overhauled: (1) search expanded to writer, penciller, inker, colorist, letterer, cover_artist, editor, characters, teams, genre, notes; (2) smart search tokens: `#N` filters by issue number, `(YYYY)` by year, `VYYY` by volume, combinable freely; (3) column header sort fixed (sort key mismatch between COLUMNS_REGISTRY and view's sort_fields dict was silently falling back to series sort for every non-trivial column); (4) pages sort uses `NULLS LAST` in both directions. Documented in `docs/guide/searching.md`.
- [x] [UI.22] `/settings/log/` batch log — the UUID column is now an "Info" button that opens the comic detail page in a new tab.
- [x] [UI.25] Review whether zero-count rows in the Review & Maintenance card (both Active and Maintenance tabs) should be hidden entirely, or kept visible as permanent status indicators. Resolved via Appearance setting: "Hide zero-count maintenance rows".
- [x] [UI.23] Dashboard Review Queue and re-organize/stale widgets consolidated into a single "Review & Maintenance" card with Active and Maintenance tabs. Active tab shows existing review queue; Maintenance tab shows Duplicates, Needs Re-organize, Stale Metadata, and Missing ComicInfo.xml rows with counts and action buttons. Tab auto-selects based on which count is non-zero.
- [x] [UI.24] Duplicate review page gains method filter tabs (All / CV ID / Series-Number / Cover Hash / Filename). Clicking a tab filters the groups list and shows the count per method on each tab button.
- [x] [UI.25] Remove up/down arrows on integer input fields on the edit comic page. 
- [x] [UI.26] Thumb in row on comics should show in full (non-thumb size) lightbox when clicked. Other parts of the row should behave as normal. 
- [x] [UI.27] Icons in sidebar when collapsed are not centeret. 
- [x] [UI.28] In Comics -> Grid layout: Top left corner of cover should be a select circle, so we can select 1..x comics for bulk actions
- [x] [UI.29] In Comics -> Grid layout: rightclick a cover should show a custom rightclick form with actions to run. Including a new action where we delete the cover image. This is because some scans have an info sheet on the first page. Current workflow is select comic, go to its details page, select Actions->Manage Pages, delete the first page, save changes. 
- [x] [UI.30] Filter rail in `/comics/` (`rail=1`) should have toggle in the settings page to be on/off by default for the user. The button on the comics page should still be there to turn it on/off on-demand. 
- [-] [UI.31] Change icons in sidebar to better match the links
- [-] [UI.32] Change icons in action bar to better match the links
- [x] [UI.33] Actions sidebar on comic details page should have a run pipeline button (should let the user confirm the comic, before running the rest of the pipeline[This is not possible with current workflow action. Button is normal pipeline. Use scrape button for confirm scape.]). 
- [x] [UI.34] Comics details page is missing action buttons for dedupe.
- [x] [UI.35] The Audit Log page's action filter only searched the newest 2000 lines and called 2000 the total. It searches the whole log and shows the real total now, and a comic's Pipeline history loads about 9 times faster on a large log. Fixed in v1.1.0.
- [x] [UI.36] Free-text search on `/comics/` did not include Imprint. Fixed in v1.2.0.
- [ ] [UI.37] Mass edit: change metadata fields on many selected comics at once. Today there is only the per-comic edit page, and tagging rules can only set fixed values (Month and Day are not rule fields, and no action copies one field into another). Planned together with P2.24. (Requested on Reddit)
- [x] [UI.38] The buttons in the comic page's More actions grid (Refresh File Info, Refresh Credits, Compare All Sources) were wider than their 124 px column (the Actions panel is a fixed 254 px at any window width) and stuck out, cut off. Fixed in v1.2.0: `.cm-btn-grid` lets their labels wrap onto two lines.
- [ ] [UI.40] The comic list's columns are all the same width (`1fr` in `templates/core/partials/comic_list_results.html`), so long series names and titles are cut off. Give each column its own default width (more for Series and Title) and show the full text on hover. (Gitea #17)
- [ ] [UI.41] Drag to resize the comic list's columns, saved with the column layout (`save_column_layout`). (Gitea #17)
- [x] [UI.42] Proposed Year was the only proposed value in the New list that could not be edited in place (`_INLINE_EDITABLE_FIELDS` in `apps/core/views.py`), so a misread year meant opening the comic's edit page. Fixed in v1.2.0: it is in the set and saved as a number like Proposed Vol (empty or not a number saves nothing), with a number input.

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
- [x] [BUG.25] Physical comics have no path forward after reaching `deduplicated` state. Fixed: physical comics now skip directly to `written` when format is detected; deduplicate batch logs correctly.
- [x] [BUG.26] Deduplicate shows in toast eg. 15 of 16 processed, but pressing the auditlog link doesn't show anything logged. Fixed in same commit as BUG.25.
- [x] [BUG.29] `/comics/?state=tagging` gives `error` everytime 'Tag' is pressed. Fixed: per-row button for STATE_TAGGED comics now calls `formatComic()` (next pipeline step) instead of `tagComic()`.
- [x] [BUG.30] Phase 4 (state=tagging) and Phase 5 (state=formats) both show a "Format" row button — need distinct labels to differentiate the two actions.
- [x] [BUG.31] Toast for Format All on dashboard, doesn't log all instances but only some of them.
- [x] [BUG.32] MCL/.db are hardcoded in docker-compose and settings page. If changed on /settings it doesn't change the file location
- [x] [BUG.33] On `?state=scrape`, after scraping via the API the Year column displays the Publisher name instead of the year value. Likely a column index mismatch in `updateRowAfterScrape()` in `comic_list.html`.
- [x] [BUG.34] "Compare All Sources" scrape option fails with `JSON.parse: unexpected character at line 1 column 1` when `comicvine.db` is not available. The endpoint likely returns a non-JSON error response (500 or HTML) instead of a proper JSON error when the local CV DB is missing.
- [x] [BUG.35] The "State" dropdown in the comic edit page still lists removed/legacy states (e.g. `count`) and does not reflect the current 7-stage pipeline. Update the dropdown to only show valid pipeline states and keep the warning "Changing state manually can break the pipeline workflow. Use with caution."
- [x] [BUG.36] `scrape_all` excludes comics with empty `custom_values` due to JSONField NULL behaviour in PostgreSQL `exclude`. Fixed by using `filter` with negated Q objects instead of `exclude` on JSONField lookups.
- [x] [BUG.37] On the comic detail page, the "Write to file" action under Actions does not advance the comic state after writing. The comic remains in the "Write to CBZ" state instead of moving to the written state.
- [x] [BUG.38] Run Path Audit progress bar does not stretch to fill the full width of its container box.
- [x] [BUG.39] New, Scrape, Tagging, Move Files, Write to CBZ all live at `/comics/?state=X`. Since active detection uses `request.path`, all five match `/comics/` and highlight the "Comics" item instead of the individual workflow step. Fix: pass the active state name via a template context variable and compare against `request.GET.state` in the sidebar.
- [x] [BUG.40] Redis warning in Docker: WARNING Memory overcommit must be enabled!
- [x] [BUG.41] When a comic has been tagged the audit log shows rollback to 'To Count', but that stage does not work anymore. 
- [x] [BUG.42] If I'm using Hybrid/Grid/Compact view and use the 'x Clear' button, the view resets to Table. Is it possible that the view isn't a url variable? 
- [x] [BUG.43] When in Grid view theres sometimes a small exclamationmark on a comic, when hovering we want to see what the issue is, eg. CBR file or ZIP or PDF or whatever it could be. or maybe the flag? 
- [-] [BUG.44] After using row buttons on `/comics/` table we get the error `Convert failed: TypeError: can't access property "querySelectorAll", row is null`. Errors and results from row actions now correctly route to the toast system via the unified endpoint.
- [x] [BUG.45] On production server the container (using `docker-compose.yaml` and not `*override*`) gives `web-1 | Not Found: /ws/tasks/`. 
- [x] [BUG.46] Comics not deselected in table view. Reproduce: go to `/comics/?state=new`, select 3 comics, using the action bar, press `Run Pipeline`, after finished, dismiss the modal popup. The comics disappear but the 3 comics that took their place are still selected.
- [x] [BUG.47] Action bar isn't shown in table/hybrid/grid/compact view if navigation = topbar. It works with navigation=sidebar. 
- [x] [BUG.48] Selecting New/Scrape/Taggning/move/Write in sidebar, then removing the filter from the rail and applying, does not remove the url filter for that stage and still highlights the stage in the sidebar. 
- [x] [BUG.49] Smartlists using 'is empty' or 'is not empty' doesn't save that filter line, as the field if empty. Also add warning if a filter line is not gonna be saved. All smartlists/filters/etc should warn the user if a filter is not gonna be saved for some reason. 
- [x] [BUG.50] Correct / new path isn't always shown on the comics details page.  
- [x] [BUG.51] In Comics details view. Pressing 'Write' makes the 'Format' button spin, but the action is 'Write'
- [x] [BUG.52] 'New Comics' on dashboard, when the convert button is shown, the view link should go to `/comics/?flag=needs_conversion` and not `/comics/?state=new&file_format=cbr`
- [x] [BUG.53] Going to `/comics/?flag=scrape_no_match` and clicking the in-line row button `Scrape` does autoscrape with no confirmation, but the flag is already no match, so we need the manual confirm scrape window.
- [-] [BUG.54] (Superseded) Toast actions doesn't batch actions correctly. Starting `Rewrite all` for "Count Updated Issue count changed - needs ComicInfo.xml rewrite" and then running a pipeline scan like from eg. 'New Comics' will replace the toast. When the pipeline is finished and the user dismisses the popup, the page reloads and the old toast for `Rewrite` will appear again. Same underlying work as FI.10 (multi-task toast). Replaced by the serial server-side task queue (`apps/core/task_queue.py`): tasks run one at a time, and the toast shows "Task N of M" and the queued tasks on every device. Reopen if a task still disappears from the toast.
- [x] [BUG.55] On `/smartlists/<uuid>/edit/`, `/tagging/ruleset/<x>/`, `/tagging/ruleset/<x>/edit/`, `/organizer/profiles/<x>/`, `/organizer/profiles/<x>/edit/` we need cm-card to have padding like 8px or something. Match it with other padding locations, check CSS.
- [x] [BUG.56] On `/organizer/au-scan/` the progressbar needs to use toast and not on-page bar.
- [x] [BUG.57] Using the in-row button on `/comics/?state=tagging` does not advance the comic to Format stage. Fixed in a07ec88: a comic already in the tagging stage moves on to the format stage after the row Tag, like `tag_all_task`.
- [x] [BUG.58] Going to /comics/?state=new and pressing Convert on the in-row button for an eg. CBR file, runs convert in the background but does not use celery or show the toast. Queuing multiple converts works, but it is not possible to see the process. Fixed: the row Convert queues `convert_cbr_task` and the toast follows it.
- [x] [BUG.59] A task-progress toast pinned to a forgotten task id stuck showing "Queued…" forever, with Cancel doing nothing, no Dismiss button, and the toast reappearing on every hard refresh. Root cause: with the django-db result backend a cleaned-up/never-written task reports `PENDING`, indistinguishable from a freshly queued one, and the resume block in `templates/partials/_scripts.html` treated `PENDING` as "still running" while the session id was never cleared. Fix: resume only on `STARTED`/`PROGRESS`; `task_progress` clears the session id for `PENDING`/`REVOKED`; the Dismiss button is shown in every state and clears the session via a new `task-dismiss/<id>/` endpoint (`dismiss_task` view). Secondary finding (not fixed, low priority): the worker consumes only `import,scrape,organize,write`, so the default `celery` queue is never drained and `celery.backend_cleanup` piles up unconsumed in Redis.
- [x] [BUG.60] The Run Pipeline button stayed stuck when a bulk run had errors. Fixed in 02d887a.
- [x] [BUG.61] Fast task buttons stayed on "Running": the task id is now stored before the task is dispatched. Fixed in ac93405.
- [x] [BUG.62] The task toast vanished instantly when a fast task had already finished. Fixed in 0e58589.
- [x] [BUG.63] The page manager could edit the wrong page: hidden files such as the macOS `._001.jpg` resource forks were counted as pages, so deleting, reordering or adding pages could change the wrong page, and a junk file could become the cover. Every part of the app uses the same page list now. Fixed in v1.1.0.
- [x] [BUG.64] Page edits (page manager, variant cover insertion) left files with mode 0600, which could lock out ComicOPDS or SMB clients. Files keep their permissions now; the new file is written next to the original and swapped in at the end, so an interrupted edit leaves the original untouched; page count, file size and cover hashes are refreshed after an edit. Fixed in v1.1.0.
- [x] [BUG.65] Page order: pages are sorted by name with numbers compared by value (page2 before page10) and case ignored. Everything else keeps plain name order, so double-page spreads named like `0304.jpg` and suffixes like `ifc` and `ifc2` keep their place. Changed in v1.1.0.
- [x] [BUG.66] The single-comic Run Pipeline result popup closed by itself when the task toast refreshed the page. Fixed in v1.1.0.
- [x] [BUG.67] The toast's Cancel (`task-cancel/`, `cancel_task` in `apps/core/views.py`) only set the Redis cancel flag, so a task that was still queued and never started never saw it, and Cancel did nothing. Fixed in v1.2.0: it cancels the QueuedTask like the queue panel's `queue/<id>/cancel/` (shared `_cancel_queued`), and only sets the flag for tasks without a QueuedTask. (Gitea #6)
- [x] [BUG.68] A cancelled task came back after a restart. Redis keeps the queued messages (`./data/redis`), but revokes live in worker memory and are lost, and `_on_prerun` (`apps/core/task_queue.py`) then set the cancelled row back to running. `reconcile_orphans` only ran with `RECONCILE_ON_START=1` or `RUN_MAIN`, so rows left running stayed forever. Fixed in v1.2.0: `_on_prerun` leaves cancelled rows alone and `ProgressTask.__call__` skips a task whose QueuedTask is cancelled (all 25 queued tasks use it). On `worker_ready` (sent once, before the worker takes a task) rows left running are marked failed; ComicManager runs one worker. Tested in the sandbox: worker stopped, task queued and cancelled from the toast, worker started, the task was delivered and skipped. Queued rows whose message is gone are listed in Task Health (BUG.70). (Gitea #6)
- [x] [BUG.69] `convert_cbr_task` (single file) never checked the cancel flag. Fixed in v1.2.0: it checks it before converting. (Gitea #6)
- [x] [BUG.70] Task Health (`apps/core/settings_views.py`) only checked TaskResult rows, so a QueuedTask stuck in queued or running without a TaskResult showed as healthy. Fixed in v1.2.0: Check tasks lists every queued or running QueuedTask under Queue, and Force stop all cancels them (`_cancel_queued`) along with the stuck TaskResult rows. (Gitea #6)
- [x] [BUG.71] BUG.59's secondary finding: the worker consumes `serial,import,scrape,organize,write`, and no default queue was set, so tasks on the default `celery` queue (such as beat's `celery.backend_cleanup`) never ran and piled up in Redis, and TaskResult rows were never cleaned up. Fixed in v1.2.0: `CELERY_TASK_DEFAULT_QUEUE = "serial"`, no compose change needed. Messages already in the `celery` list stay until purged (`celery -A comicmanager purge -f -Q celery`).
- [x] [BUG.72] The comic page crashed (server error) when no page count was stored and the file was missing or could not be read, because `_get_cbz_page_count` only catches `BadZipFile` and `EOFError`. Refresh File Info and Download also crashed on a file the container cannot read. The comic page now shows without a page count and does not flag the file as corrupted, and Refresh File Info and Download say `Could not read the file: Permission denied`. The untagged scan still reports an unreadable file as an import error instead of importing it. Found by checking every comic page, action and task with missing and unreadable files. Fixed in v1.1.2. (Gitea #12)
- [x] [BUG.73] Refresh Credits and Search Alt Covers crashed on every comic when there was no local comicvine.db (API-only setups): `ComicVineScraper` opened the missing file, and the page showed `Network error: Unexpected token`. Search Alt Covers never reached its API fallback. Both now check `is_cv_db_available()` and use the API without the local database, Refresh Credits also when the issue is not in it, like Scrape by ID. A ComicVine rate limit is reported instead of crashing. Fixed in v1.1.2.
- [x] [BUG.83] Write Stale said "No stale comics to write" while the dashboard listed comics under Stale Metadata: `write_stale_comics` counted only `state=write` (BUG.18's `written`, from before the states were renamed), but a written comic is in Done. The dashboard count, the list's `?stale=1`, the Smart List `is_stale` field and `write_stale_comics_task` had no state check at all, so a comic sent back to an earlier step counted as stale, and Write Stale would have written it and set it to Done, skipping the steps in between. All five use `STALE_Q` (`apps/core/models.py`) now: written before, changed since, in Write or Done. Fixed in v1.2.0.
- [x] [BUG.74] In the Confirm-each loop (Scrape All with Confirm each), Cancel, the X, Esc and a click outside the scrape window only skipped the comic and opened the next one, so the only way out was reloading the page: `onCancel` in `openListScrapeModal` (`templates/core/comic_list.html`) counted the comic as skipped. Closing the window now ends the loop, and the button shows Stopped with the counts; Skip still moves on. The close listener in `static/js/scrape.js` also ignores a close event that arrives after the window was opened for the next comic, which counted that comic as cancelled when a save answered quickly. Fixed in v1.2.0 (Gitea #15)
- [x] [BUG.75] In the Confirm-each loop, a failed save stalled the loop: `scrapeSelectMatch` (`static/js/scrape.js`) closed the window before the save and on an error only showed a toast, so the queue never moved on and the Scrape All button kept spinning. In the loop the window now stays open between comics (dimmed, "Saving...", while a pick is saved) and shows a failed save's error, so the comic can be picked again or skipped. A single scrape still closes the window first. Found while checking BUG.74. Fixed in v1.2.0 (Gitea #15)
- [x] [BUG.76] The cover match (`match_by_hash_fast` in `apps/scraper/comicvine.py`) listed the same issue more than once when comicvine.db has several close covers for it (the same cover uploaded twice, or variants that look alike), and the copies used up its limit of 5 candidates: Firefly: River Run #1 showed three times in the scrape window, and auto-match had fewer other issues to choose from. Each issue is now kept once, at its closest cover, and the limit counts different issues. Found while testing the scrape window for Gitea #15. Fixed in v1.2.0.
- [x] [BUG.79] The dashboard ran about 40 separate COUNT queries on the comics table, one for each flag and figure, and each one read the whole table (`index` in `apps/dashboard/views.py`); with 116,547 comics a page view took 2.5 to 3 s. All its comic counts now come from one aggregate with filtered counts. Fixed in v1.2.0 (Gitea #18).
- [x] [BUG.80] The comic list's filter rail ran a count and an `exists()` for each flag plus two counts for the Convert buttons on every request (`comic_list` in `apps/core/views.py`), also for HTMX paging, sorting and filtering, which only render the results. The rail data moved to `_filter_rail_context`, with one aggregate for the flag counts, and HTMX requests skip it. Fixed in v1.2.0 (Gitea #18).
- [x] [BUG.81] The duplicate review page built every pending group at once, with one query per group for its pending comics (`get_pending_groups` in `apps/duplicates/services.py` filtered the prefetched memberships again), so 75,000 groups could not load. It shows 100 groups per page now, counts the groups per method in the database (`pending_groups_queryset`), and fetches the pending comics in one query. Groups with one pending comic left are still resolved when the page loads (`resolve_single_comic_groups`). Fixed in v1.2.0 (Gitea #18, from a comment).
- [x] [BUG.82] 70 links in 19 templates had a stray quote before `cm-no-underline` (`class="cm-btn sm ghost" cm-no-underline"`), left from moving inline styles into utility classes in May, so the class closed early and `cm-no-underline` became a broken attribute. Nothing looked different, since links have no underline anyway. Fixed in v1.2.0: the class is inside the attribute.


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
- [x] [IND.9] Inducks-scraped comics (`scrape_source == "inducks"`) should skip CV-specific pipeline phases: issue count propagation (Phase 3), alt cover search, and count mi smatch detection. `populate_counts_task` Phase 1 and Phase 2 both exclude `custom_values__scrape_source="inducks"`.                                                           
- [x] [IND.10] Inducks-scraped comics should skip the "Find Alt Covers" action and any CV API lookups on the detail page. `search_alt_covers` view returns an error response when `scrape_source == "inducks"`.                                                                                                                                             
- [x] [IND.11] Review all batch tasks (scrape_all, populate_counts, format_all, etc.) to ensure they handle Inducks-sourced comics gracefully without errors or false flags. `scrape_all_task` and both phases of `populate_counts_task` now exclude `custom_values__scrape_source="inducks"`. `tag_all` and `format_all` are source-agnostic and work correctly on all comics.
- [x] [IND.12] Story-code search should accept `D92380` as well as `D 92380`. Fixed by normalizing spaces in `search_by_storycode`: strips spaces from input and uses `REPLACE(s.storycode, ' ', '') LIKE ?` in the SQL query.
- [x] [IND.13] Inducks comics should skip `/comics/?state=count` and go directly from `/comics/?state=scrape` to `/comics/?state=tagging`. Fixed: `apply_inducks_match` now sets `comic.state = Comic.STATE_TAGGED` instead of `STATE_COUNTED`.
- [x] [IND.14] Inducks comics should skip the `missing_format` review queue. Fixed in `detect_and_set_format`: Inducks-sourced comics do not receive the `missing_format` flag when no format is auto-detected, since they have no CV issue count for count-based format rules.
- [x] [IND.15] When matching a comic directly via story code, the `series` field (and potentially `number`, `publisher`) are not populated from the story/publication metadata. Comics scraped this way end up with missing core fields, blocking later pipeline stages. Improve `apply_inducks_match` (or the story-code search result handling) to populate `series` from the publication title or story title, and set `number` / `publisher` where available.


## Flag List Action Button Audit

**Goal:** Ensure every `?flag=X` list view has consistent, correct action buttons matching the style and behaviour of `?state=new`.

**Current Status & Tasks:**
- [x] [FL.1] `?flag=count_updated` — pressing Accept removes the row and shows `{"success": true}` in the first column instead of a proper inline response. Fixed in commit 4467157.
- [x] [FL.2] `?flag=count_updated` — no per-row action button. Added "Rewrite" button calling `force_write` endpoint; row fades out on success.
- [x] [FL.3] `?flag=no_series` — shows two Accept buttons. One must be removed. Fixed in commit 4467157.
- [x] [FL.4] Audited all `?flag=X` views. Two issues found and fixed: (1) `count_updated` missing Rewrite button (FL.2); (2) `corrupted_archive` incorrectly showed "Add to Workflow" — excluded from that condition and given a "Try Rezip" button instead. All other flags verified correct.

## Documentation Needed

**Goal:** Write docs that explain internal behaviour for future reference or contributors.

**Current Status & Tasks:**
- [x] [DOC.1] Write a section in `./docs` explaining what fields are populated by each scrape source: comicvine.db (local hash/metadata match), ComicVine API (live search), and Inducks. Cover which fields each source fills, whether issue count is included, and why the Count pipeline stage was removed (CV scraping already populates the count field, making a separate step unnecessary).
- [x] [DOC.2] In scraping.md under ## Single Comic Scraping we need to specify that a 4000-xxxx comicvine ID can be used for direct match.
- [x] [DOC.3] Docs pages for the dashboard, the comic detail page, appearance and flags, and the guides updated for the v1.1.0 changes.
- [x] [DOC.4] Warning in `docs/guide/organizing.md` to check the base folder after a `.lop` import (see P7.23). Done in b7dd60e.
- [x] [DOC.5] The docs site ran the Vite dev server, so one page view meant hundreds of requests for source files. It is built with `vitepress build` and served by nginx now (`docs/Dockerfile`, `docs/nginx.conf`); glightbox is loaded in `onMounted`, so the build no longer fails. Done in c489bcc.
- [x] [DOC.6] `docs/guide/tagging.md` said Export includes all rulesets; it leaves out disabled ones (`export_datamanager_xml` filters `is_enabled`). Fixed in v1.2.0: the docs say so. Exporting disabled ones too belongs with FI.13.
- [ ] [DOC.7] `docs/guide/tagging.md` marks Imprint "Not verified" for DataManager compatibility. Check whether ComicRack's Data Manager has an Imprint field.
- [x] [DOC.8] `docs/guide/philosophy.md` said ComicManager runs "on any OS" (line 3), but Windows is not supported, and "No other sources will be added" (line 24), which changes if FI.16 goes ahead. Fixed in v1.2.0: built and tested on Linux, Windows not supported; no other sources planned right now. Also added a Local Network Only section (no login, plain HTTP on the local network, HTTPS and HTTPS reverse proxies not supported; Gitea #13) and a Troubleshooting entry for "CSRF verification failed".
- [x] [DOC.9] CHANGELOG.md does not list the publisher allow and block lists (P2.18), which were added after v1.1.0 was tagged. Added to the v1.1.2 section.
- [x] [DOC.10] The docs container had no restart policy, so it stayed down after a reboot. `docs/docker-compose.yml` has `restart: unless-stopped` now.
- [x] [DOC.11] The docs image failed a vulnerability scan (1 critical, 2 high) even when built on the newest `nginx:alpine`: that image lagged behind Alpine's fixes for curl, libcurl and brotli-libs. None of them were reachable (nginx links neither, only the `curl` tool and freetype use them). `docs/Dockerfile` runs `apk upgrade --no-cache` in the nginx stage, so a rebuild gets Alpine's fixed packages. The scan is now 0 critical, 0 high.
- [x] [DOC.12] Docs gaps found while checking the docs for 1.1.2: `writing.md` listed story arcs under Custom Values and `organizing.md` said `{<storyarc>}` comes from custom values (it reads the Story Arc field, `template_engine.py`), and used `{<Custom(StoryArc)>}` as an example. Troubleshooting had no entry for the `Operation not permitted` error on a `.cm-move-*.tmp` file from before 1.1.2 (P7.21), and the comic page guide did not say that Refresh Credits and Search Alt Covers use the ComicVine API without a local comicvine.db. Fixed in v1.2.0.
- [x] [DOC.13] The README, Getting Started (Updating) and `.env.sample` did not say what the image tags are. `latest` and version tags are releases; `dev` follows the dev branch for testing, can break, and can run migrations a release doesn't have yet, so going back to `latest` may not work. Added in v1.2.0.

## Future Improvements

**Goal:** Track nice-to-have features and enhancements that are not yet prioritised.

**Current Status & Tasks:**
- [x] [FI.4] Export tagging rulesets as a `.dat` file generated from the current database state (all rulesets, including ones created or edited in the UI), not a re-export of the originally imported file. Export button removed from `/tagging/` until this is properly implemented.
- [x] [FI.5] Export organizer profiles as a `.lop` file generated from the current database state. Would complete the import/export round-trip for both `.dat` (tagging rules) and `.lop` (organizer profiles).
- [x] [FI.6] Persist CV API call budget counters to the database (or a Redis-backed store with AOF/RDB persistence) so a container restart does not reset them. Currently counters live only in Redis memory and are lost on restart, allowing the hourly budget to be exceeded unintentionally after a redeploy. Done in v1.1.0: the budget is kept in the Django cache in Redis (database 1), shared by the web and worker processes, and Redis saves to `./data/redis`, so a restart keeps it.
- [x] [FI.7] Navbar restructured: added a "Workflow" dropdown with numbered links to each pipeline stage; plugin links (Tagging Rules, Publishers, File Organizer, Path Audit) moved under the Settings dropdown; Physical moved as a submenu under Comics. All dropdowns open on hover with a 150ms grace period.
- [ ] [FI.1] PDF to CBZ conversion. Currently `convert_cbr` only handles CBR/CB7 (archive re-pack). PDF conversion requires rendering each page to an image (e.g. via `pdf2image` / Ghostscript), which is a separate, non-trivial operation. Would allow PDFs flagged `is_pdf` to be converted in-place rather than only deleted or suppressed.
- [x] [FI.2] ComicVine API call budget management. Per-path rolling counters (/search, /volume, /issues, /issue) tracked in Redis and displayed as progress bars in Settings. Budget checked before every call; comics skipped when exhausted rather than errored. Manual search results loaded in batches of 3 with lazy /volume fetching to minimise cost.
- [x] [FI.3] Resolved by redesigning `try_api_metadata_match` to use a 3-call volume-based strategy: /search returns credits inline via /issue on the final call, so there is no separate budget-gated credits fetch. Full credits are always included or the entire match is skipped.
- [ ] [FI.8] Add a configurable setting to control whether CBR/CB7 files are flagged `needs_conversion` on import. Currently flagging is unconditional. Implementation: re-introduce a setting (e.g. `import_convert_cbr`), read it in `services.py` and `scan_untagged.py`, and only set the flag when enabled.
- [ ] [FI.9] Extend `snapshot_fields` / `diff_fields` (in `apps/core/audit.py`) to handle nested dict-key paths like `comic.custom_values["comicvine_issue"]` with audit-key renaming, so scrape audit code can declare one shared field list and avoid the inline `before_cv_issue` / `before_cv_volume` currently in `_run_scrape`, `scrape_comic`, and `force_scrape`.
- [-] [FI.10] (Superseded) When multiple tasks are running concurrently (e.g. a re-write batch from the dashboard Maintenance tab and a separate `/organizer/au-scan/` Run Scan), the toast notification shows only the most recent task and silently replaces the previous one. Instead, show a running task count in the toast header and cycle or stack the active task statuses so the user can see all in-progress operations at once. See BUG.54: tasks no longer run at the same time, and the toast shows the queue.
- [x] [FI.11] The `/organizer/au-scan/` Run Scan progress counter stayed at 0 until the full scan completed: in `scan_au_paths_task` the skip paths hit `continue` before the end-of-loop `update_state`, and most candidates are skipped. Fixed in v1.2.0: progress is reported at the start of every iteration (comics done so far); the finished event shows 100%.
- [ ] [FI.12] The organizer `.lop` Export differs from what ComicRack's Library Organizer writes: root `LibraryOrganizer` instead of `Profiles`, no `Version`, about 20 settings missing, and templates and illegal characters escaped twice (`&amp;lt;publisher&amp;gt;`). The `.lop` import skips Simulate profiles, so Export cannot give them back. Export in ComicRack's own format.
- [ ] [FI.13] The `.dat` import skips group comments, group-level filters and defaults, and the Disabled section, so the ruleset Export cannot give them back. Import, export and import again should give the same data.
- [ ] [FI.14] Opt-in Matomo telemetry with a first-run consent splash, written in July on the `telemetry` branch (not merged). Review every field sent before merging, and add a docs page on what is sent. The version in the top bar is hardcoded in `templates/partials/_topnav.html`, so a build cannot be identified; the branch adds `apps/core/version.py`.
- [ ] [FI.15] ComicBook.xml (ComicRackCE) support: read and write it next to ComicInfo.xml in one archive update, keep the parts ComicManager does not know, and read it in `import_library`, so custom values come in without ComicDb.xml. Add a docs page.
- [ ] [FI.16] More metadata sources for comics ComicVine lacks: Metron (metron.cloud), the Grand Comics Database (comics.org) and League of Comic Geeks. For each, check the API or data dump, accounts and rate limits, and the terms of use (League of Comic Geeks: check for an official API, don't scrape the site). GCD: comics.org blocks scripts, so use its SQLite dump read-only like comicvine.db; the data is CC BY-SA 4.0 and needs attribution. Order: measure how many unmatched comics it would find, then manual search in the Scrape modal, then a fallback when ComicVine has no match, then Compare All Sources. (Requested on Reddit)
- [ ] [FI.17] Reading status and ratings per comic, synced from ComicOPDS and ComicTracker, shown as columns and Smart List filters, and written to ComicBook.xml so ComicRackCE gets them (needs FI.15).
- [-] [FI.18] (Not planned) Rotate `data/logs/batch_actions.jsonl`. It grows about 1-2 MB in a normal month, rotating it would lose rollback history, and reading it is fast since UI.35.

## Redesign 

**Goal:** Redesign the UI for nicer look and better usability. 

**Current Status & Tasks:**
- [x] [RD.1] User never had Kanban selected in settings, as Kanban was never shipped. Remove Kanban fallback to Segments.
- [x] [RD.2] Segments should be default with optional Flow or None. If None is selected the Workflow pipeline is hidden on the dashboard. 
- [x] [RD.3] Flow needs redesigned. The alignment is wrong and the line looks bad. Either disable or fix.
- [x] [RD.4] Add accent style color choice to settings.
- [x] [RD.5] `/comics/` list page
- [x] [RD.6] Dashboard
- [x] [RD.7] Series Audit (`/comics/series-audit/volume/<id>/`)
- [x] [RD.8] Series Audit Search (`/comics/series-audit/search/`)
- [x] [RD.9] Format Review
- [x] [RD.10] Duplicate Review
- [x] [RD.11] Path Audit
- [x] [RD.12] Smart Lists index
- [x] [RD.13] Smart Lists detail dropdown
- [x] [RD.14] Organizer profile list/detail/form
- [x] [RD.15] Tagging ruleset list/detail/form
- [x] [RD.16] Smart List form
- [x] [RD.17] Comic detail page (`/comics/<uuid>/`)
- [x] [RD.18] Scrape modal
- [x] [RD.19] Compare All Sources modal
- [x] [RD.20] Manage Pages modal
- [x] [RD.21] Comic edit page (`/comics/<uuid>/edit/`)
- [x] [RD.22] Comic reader (`/comics/<uuid>/read/`)
- [x] [RD.23] `/scraper/`
- [x] [RD.24] `/settings/log/`
- [x] [RD.25] `view=compact` on `/comics/` should also have 'Columns' setting like `view=table`. 
- [x] [RD.26] Comic details page:
    - [x] [RD.26a] Right sidebar with 'Actions' have buttons that are just hyperlinks, change them to actual buttons
    - [x] [RD.26b] File info box, needs the border to match the normal box.
    - [x] [RD.26c] Double check that all values like hash/api/match info exists somehwere
    - [x] [RD.26d] Remove extra 'View on Comicvine'
    - [x] [RD.26e] Add Pipeline History (use Audit log info?)
- [x] [RD.27] Migrate the three JS form builders off the DaisyUI to `cm-*` components: `templates/tagging/ruleset_form.html`, `templates/dashboard/smartlist_form.html`, `templates/organizer/profile_form.html`. This seems to be the last remaining DaisyUI. Remember the server-rendered rule rows in `ruleset_form.html` must stay visually identical to its JS-generated rows. Done in e3c1e12.
- [ ] [RD.28] After RD.27, prune the now-unused DaisyUI from `static/css/input.css`. Not possible yet: the modals (`modal-box`, `modal-backdrop`) and the loading spinners (`loading-spinner`) still use DaisyUI and have to move to `cm-*` first.


## Code to Port

**Goal:** Ensure all relevant ComicRack scripts and logic are properly integrated or reimplemented in ComicManager.

**Current Status & Tasks:**
- [x] [CP.1] Confirmed CVIssueCount script equivalent implemented (`Issue count management`).
- [x] [CP.2] Confirmed ComicInfo.xml / Write-to-File equivalent implemented (`ComicInfo.xml output parity`).
- [x] [CP.3] Confirmed Library Organizer config equivalent implemented (`Organizer profile rule editor`).
- [x] [CP.4] Confirmed DataManager file equivalent implemented (`ComicDb.xml import support`).
- [x] [CP.5] Thoroughly verify that existing implementations fully replicate the functionality of ComicRack script counterparts, ensuring all nuances are handled.
- [x] [CP.6] Import ComicRack CBL files as Smart Lists. A CBL (Comic Book List) is a ComicRack smart list export format. Importing a CBL should create a corresponding Smart List in ComicManager, mapping the stored filters and column layout to the ComicManager equivalents where possible.


## Architecture

**Current Status & Tasks:**
- [x] [AC.1] Replace `xml.etree.ElementTree` with `defusedxml.ElementTree` project-wide. Affects `ComicInfo.xml` read/write, `.lop` parser, and any other XML ingestion.
- [x] [AC.2] Check batch task functions for missing `transaction.atomic()` wrapping. If a worker crashes mid-batch (e.g. `tag_all` at comic 25 of 50) the DB is left in a split state. Wrap each item's DB writes atomically.
- [x] [AC.3] Check `get_setting()` call sites inside task loops. If called per-comic in a batch, snapshot settings once before the loop instead of hitting the DB on every iteration.
- [x] [AC.4] Reduce `ProgressTask` boilerplate. Add a shared helper so individual tasks don't each reimplement the same cancellation-check + progress-update pattern. Probably no change to the JS polling layer.
- [x] [AC.5] Rewrite action endpoint to a single unified one. 
- [x] [AC.6] Test suite: tests run in the production Docker image against generated sample data (`docker compose -f docker-compose.test.yml run --rm --build tests`). Added in v1.1.0.
- [x] [AC.7] The cover proxy endpoints fetched any URL they were given, including local files such as the container environment (database password and secret key) and addresses on the local network. Only http(s) to public addresses is allowed now, with a size limit, and the Inducks login is only sent to inducks.org. Fixed in v1.1.0.
- [x] [AC.8] The rollback response and the Smart List form put user-provided text into the page without escaping it. Fixed in v1.1.0.
- [x] [AC.9] The WhiteNoise static storage setting was ignored on Django 5.1+, so static files are served compressed now; Python dependencies are pinned to the tested versions; the Django cache is in Redis database 1 (`CACHE_URL`); the unused task pause endpoints were removed. Done in v1.1.0.
- [ ] [AC.10] `ComicVineScraper.match_by_hash` (`apps/scraper/comicvine.py`) is unused and broken (it builds `CVMatch` without `cover_url`). Remove it.
- [ ] [AC.11] Check whether request tracebacks reach the container log with `DEBUG=False`. `LOGGING` (`comicmanager/settings.py`) only configures the duplicates, organizer and scraper loggers, but daphne and celery set a root handler, and a user's web log showed `django.request` lines, so it probably works already.
- [x] [AC.12] A non-number in some URL parameters gave a server error instead of being ignored: `per_page` on `/comics/` (`apps/core/views.py`) and the Smart List page (`apps/dashboard/views.py`), and `limit` and `max_distance` on the scraper's dry run (`apps/scraper/views.py`) called `int()` without a check; `offset` on the dashboard already had one. Found while checking AC.11. Fixed in v1.2.0: they use `int_param` (`apps/core/utils.py`), which falls back to the default.
- [x] [AC.13] `InterruptedWriteTests` (`apps/core/test_files.py`) failed when Docker runs on btrfs or XFS (5 failures and 1 error). The tests fake a crash in the in-place ComicInfo.xml write and check its index backup, but on a copy-on-write filesystem `write_comicinfo_xml` patches a reflink clone instead, so the fake crash hit the clone and there was no backup to restore. The code was right; the tests now force the in-place path, as the other in-place tests already did. Fixed in v1.2.0.
- [x] [AC.15] The 1.1.0 image failed a vulnerability scan (grype: 13 critical, 163 high, 208 with a fix): outdated Debian packages from a stale `python:3.12-slim` base, Python 3.12.12, and Pillow 12.3.0. The `Dockerfile` uses `python:3.12-slim-trixie` and uninstalls pip after installing, `requirements.txt` has Pillow 13.0.0, `docker-compose.test.yml` builds with `pull: true`, and `.dockerignore` leaves out `staticfiles/` (an old git-ignored copy in a clone was copied in as root, so `collectstatic` failed on start). The scan dropped to 1 critical and 68 high, 12 with a fix. The cover hashes of the 49 sandbox comics are the same on Pillow 13. Twisted (through `channels[daphne]`) waits for 26.10.0: the only finding the app can reach is a medium in twisted.web. Fixed in v1.1.2.
- [x] [AC.16] Twisted, which `channels[daphne]` pulls in, was 26.4.0 in the image: 3 high and 2 medium findings in the vulnerability scan, the only one the app can reach a medium in twisted.web (AC.15 waited for this). `requirements.txt` pins Twisted 26.10.0, released 2026-10-30. Fixed in v1.2.0.
