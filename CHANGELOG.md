# Changelog

## [1.1.1]

A hotfix release.

### Fixed

- **Scraping failed with some local comicvine.db files (#8)**: A comicvine.db that stores cover hashes as plain SQLite integers keeps some of them as negative numbers. Loading those failed, so the scrape window showed `Unexpected token '<' ... is not valid JSON` and cover matching did not work. These hashes are now read correctly, and a hash table that can't be read turns off cover matching instead of stopping the scrape.

## [1.1.0]

A reliability release. Back up the database before upgrading. The upgrade runs one migration, which corrects the built-in Default organizer profile. If your library has RAR files named `.cbz`, see `convert_misnamed_archives` in the Getting Started guide.

### Added

- **Nested Smart List groups (#3)**: Groups can contain groups, up to three levels deep, so lists like (A and B) or (C and D) can be built. Each group matches ANY or ALL of its filters, and a group added inside a group starts with the opposite setting. The **Add OR Group** button is now **Add Group**. Saved lists with nested groups (for example from a CBL import) no longer lose them when the list is edited and saved.

- **Missing files on the Path Audit page (#4)**: Comics whose files are not on disk get the `file_missing` flag and are listed in a separate **Missing files** table with **Relink** (find the file in the library) and **Remove** (delete only the database record; refused if the file is back). They are no longer offered for a move. The flag also appears in the dashboard Review Queue and as a Smart List field.

- **RAR and 7-Zip archives named .cbz or .zip**: The untagged scan detects the real format and flags such files for conversion, instead of reporting them as corrupted or renaming a `.zip` into a broken `.cbz`. **Convert** and **Rezip** turn them into real CBZ files. A file is only replaced once the new archive is complete and contains pages.

- **`convert_misnamed_archives` command**: Converts RAR or 7-Zip archives named `.cbz` in the library in place. Use `--dry-run` to list them first.

- **`import_library` reads ComicDb.xml for files without ComicInfo.xml**: With `--comicdb`, files that have no ComicInfo.xml are imported from their ComicDb.xml entry. Files with an uppercase `.CBZ` extension are found too, and a dry run reports how many comics it would import.

- **Test suite**: Tests run in the production Docker image against generated sample data: `docker compose -f docker-compose.test.yml run --rm --build tests`.

### Fixed

- **Page manager could edit the wrong page**: Hidden files such as the macOS `._001.jpg` resource forks were counted as pages, so deleting, reordering or adding pages could change the wrong page, and a junk file could become the cover. Every part of the app now uses the same page list.

- **Page edits locked out other readers**: Files edited in the page manager or by variant cover insertion ended up with mode 0600, which could lock out ComicOPDS or SMB clients. They now keep their permissions, and the new file is written next to the original and swapped in at the end, so an interrupted edit leaves the original untouched. Page count, file size and cover hashes are refreshed after an edit.

- **Interrupted ComicInfo.xml writes could break an archive**: On ext4 and similar filesystems, a power loss, full disk or killed process during a write could leave an archive that would not open, even with Rezip. The archive index is now backed up first, and an interrupted write is undone on the next write or with Rezip. On btrfs and XFS the patched copy is flushed to disk before it replaces the original. Rewrites reuse the space of the old ComicInfo.xml instead of growing the archive by one copy per write.

- **Untagged scan deleted the metadata of missing files**: A comic whose file was missing lost its record, including scraped and hand-edited metadata, for example when the disk was not mounted. Only untouched New comics are removed now; the others get the `file_missing` flag, which clears itself when the file is back. If the folder looks unmounted, nothing is changed. The scan result says how many comics were removed, flagged or found again, and the scan finds uppercase extensions and skips hidden files.

- **CBR conversion could delete the original**: When a CBZ with the same name already existed, the CBR was deleted without being converted. Conversion now refuses and keeps both files.

- **Moves could overwrite files**: Organizer moves never replace an existing file. Moves between the untagged folder and the library copy through a hidden temporary file, so an interrupted move never leaves a half-copied comic.

- **Default organizer profile**: The built-in Default profile filed every comic that matched none of your own profiles under `[publisher]/[series]`. A migration corrects it if it still has the original templates.

- **Path Audit**: Sync Paths covers Done comics and no longer matches a different series that starts with the same name. The Correct Location count shows a number, and the audit result says how many files are missing.

- **Duplicates**: New comics are compared against comics kept or marked intentional in earlier duplicate groups; before, a new copy of such a comic was never detected. Deduplicating a batch no longer creates groups among old library comics and is faster. Cover-hash groups no longer chain loosely similar covers together.

- **Cover proxy fetched local files and LAN addresses**: The cover endpoints fetched any URL they were given, including local files such as the container environment (database password and secret key) and addresses on your network. Only http(s) to public addresses is allowed now, with a size limit, and the Inducks login is only sent to inducks.org.

- **Unescaped text**: The rollback response and the Smart List form put user-provided text into the page without escaping it.

- **ComicVine API budget and pacing**: The API call budget was counted separately by the web and worker processes and reset on every restart; it is kept in Redis now. API calls are spaced 1.1 seconds apart across processes, not only within one task.

- **Batch Audit Log page**: The action filter only searched the newest 2000 lines, and the page called 2000 the total. The filter searches the whole log and the page shows the real total. A comic's Pipeline history loads about 9 times faster on a large log.

- **Run Pipeline result closed by itself**: The single-comic result popup no longer closes when the task toast refreshes the page.

- **import_library permission error**: Running it as the container user no longer fails. Its error log is `data/logs/import_errors.log` on the host.

- **Static files**: The WhiteNoise setting was ignored on current Django versions; static files are now served compressed.

### Changed

- **Page order**: Pages are sorted by name with numbers compared by value (page2 before page10) and case ignored. Everything else keeps plain name order, so double-page spreads named like `0304.jpg` and suffixes like `ifc` and `ifc2` keep their place. Archives with unpadded page numbers or mixed upper and lower case show their pages in a different, now correct, order.

- **Django cache in Redis**: Redis database 1 on the same server holds the Django cache (override with `CACHE_URL`). No configuration change is needed.

- **Pinned dependencies**: Python dependencies are pinned to the tested versions.

- **Removed**: The unused task pause endpoints.

## [1.0.0]

### Added

- **CBL import for Smart Lists (CP.6)**: ComicRack `.cbl` files can now be imported as Smart Lists via the **Import CBL** button on the Smart Lists index page. Matcher types (Publisher, Series, Title, File, Format, Custom Values, etc.) are mapped to ComicManager filter fields. OR/AND groups are preserved. If the CBL contains filter fields not in the standard list, a mapping step prompts the user to choose the correct internal field or skip those filters. Unsupported matcher types are skipped with a warning shown on the edit page.

- **CBL export for Smart Lists**: Any Smart List can be exported as a `.cbl` file via the **Download CBL** button on the Smart List detail page. If all filters map cleanly to CBL, the file downloads immediately. If any filters have no CBL equivalent (flag filters, numeric operators, etc.) a choice page is shown with two options: **ComicRack-safe** (standard CBL, unsupported filters skipped, works in ComicRack) and **Complete** (all filters preserved by embedding the full filter data in the file, for lossless ComicManager round-trips). Complete exports can be re-imported into ComicManager without data loss; ComicRack ignores the extra element.

- **OR group support in Smart List filters**: The filter system now supports nested AND/OR groups in addition to the existing flat AND-only list. Use **Add OR Group** on the Smart List form to group conditions that should match any (OR) or all (AND) of their filters. The filter JSON schema is backward compatible; all existing Smart Lists continue to work without changes.

- **New filter lookup operators**: Smart List filters now support `starts with`, `not starts with`, `ends with`, and `not ends with` in addition to the existing operators.

- **Expanded Smart List filter fields**: DataManager custom values (`DataManager_Processed`, `Original Format`, `Leading Numbers`, `First Series`, `Second Series`, `IsStarWars`, `Has Alt Covers`), ComicVine fields (`CV Issue Count`, `Scrape Score`) are now available in the filter field dropdown.

- **Cover hash verification for API matches**: Layer 3 (CV API matching) now downloads the ComicVine cover image for the matched issue and compares it against the comic's stored pHash and aHash using Hamming distance. If both distances exceed 15, the match is rejected and `scrape_no_match` is set. The rejection reason (e.g. `cover hash mismatch (phash dist 42, ahash dist 38)`) is stored in `flags.scrape_error_detail` and shown in the audit log. Verification is skipped automatically when the comic has no stored hashes or the API returns no cover URL. Cover downloads do not count against the API call budget.

- **Cover hashes computed at accept time**: When a comic is accepted from the New stage (single Accept, Accept All, or Run Full Pipeline), the first page of the CBZ is now read and both pHash and aHash are computed and saved to the database. Previously hashes were only set as a side effect of Layer 1 hash matching (DB mode only), leaving API-only mode comics without hashes. A fallback still computes hashes on the fly during Layer 3 matching for comics accepted before this change.

- **Audit logging for single-comic scrapes**: `scrape_comic` and `force_scrape` views now write entries to the Batch Audit Log at `/settings/log/`, matching the detail level of batch scraping. Successful matches log `series`, `publisher`, `cv_issue`, and `cv_volume` changes. Failed matches log `result: null -> no_match` plus a `reason` field when a cover hash mismatch was the cause. Previously only batch scrape tasks were logged.

- **ComicVine API fallback toggle**: A new setting `scrape_api_fallback` (Settings page, Scraping group) enables the ComicVine API as a Layer 3 fallback even when `comicvine.db` is present. When the local DB finds no hash or metadata match, ComicManager will attempt an API match before giving up.

- **Volume-based API matching strategy**: `try_api_metadata_match` now uses a 3-call approach inspired by comic-vine-scraper. A single `/search?resources=volume` call returns publisher, start year, and issue count inline (no separate `/volume` calls). The best-scoring volume is then probed with `/issues?filter=volume:{id},issue_number:{num}`, and full details including credits are fetched with a single `/issue` call. Total cost is exactly 3 API calls and 0 `/volume` calls per comic, down from the previous 1+N+1 approach.

- **Per-path API budget tracking**: API call counts are now tracked independently for each ComicVine endpoint path (`/search`, `/volume`, `/issues`, `/issue`). Per-path usage bars are shown in the Settings page under ComicVine Data Sources and only appear when API mode is active.

- **Batched manual search results**: The scrape modal now fetches 12 results in a single `/search` call but displays them in batches of 3. Publisher and year are loaded lazily via a dedicated `/comics/scrape/volume-batch/` endpoint so initial results appear with only 1 `/search` + 3 `/volume` calls. Each "Show 3 more" click costs at most 3 additional `/volume` calls, all cached within the worker process.

- **Run Full Pipeline**: A single-click button that runs all 8 import phases automatically for CBZ files in the New state. Available as a per-row button (single comic) and a toolbar button (all eligible CBZ comics in the list). Each comic is accepted, scraped, tagged, formatted, deduplicated, organized, and written in sequence. Duplicate detection stops processing early and marks the comic accordingly. After completion a results modal shows a per-step breakdown for single runs or a summary table for bulk runs, with "View Comic" and "View Original" links. Non-CBZ files are excluded; CBR files must be converted to CBZ first. A single-click button that runs all 8 import phases automatically for CBZ files in the New state. Available as a per-row button (single comic) and a toolbar button (all eligible CBZ comics in the list). Each comic is accepted, scraped, tagged, formatted, deduplicated, organized, and written in sequence. Duplicate detection stops processing early and marks the comic accordingly. After completion a results modal shows a per-step breakdown for single runs or a summary table for bulk runs, with "View Comic" and "View Original" links. Non-CBZ files are excluded; CBR files must be converted to CBZ first.

- **CBR conversion audit logging and error recovery**: Converting a CBR or CB7 file to CBZ now logs every outcome to the Batch Audit Log (success, recovered, and error). If a CBZ already exists alongside the CBR from a partial previous conversion, the DB record is recovered and the original CBR cleaned up instead of returning an error. If the CBZ path is already assigned to a different comic record, a clear error is shown in a toast notification and logged to the batch log.

- **Populate Counts background task (P3.2)**: The synchronous "Populate Counts" and "Detect Count Mismatches" actions are now wrapped in a single Celery task (`populate_counts_task`) with progress reporting and cooperative cancellation. Dispatched via POST to `/comics/populate-counts-all/`. Runs in two phases: first populates missing counts from the CV SQLite DB, then detects count mismatches within volumes.

- **Unknown Publisher flagging (P4.5)**: After scraping, comics whose publisher is not covered by any enabled DataManager ruleset's Publisher rules are automatically flagged `unknown_publisher`. The flag appears in the dashboard Review Queue. Supports all rule modifiers (Is, Contains, StartsWith, RegEx, etc.) for matching. The flag is cleared on re-scrape, re-tag, or batch re-tag when the publisher becomes covered by a ruleset.

- **Publishers page (P4.6)**: New page at `/tagging/publishers/` (Workflow > Publishers) shows all publishers in the library split into two groups: those covered by at least one tagging ruleset (with linked ruleset badges) and those not covered. Each row shows the comic count. Uncovered publishers have a "Create Ruleset" button that opens the ruleset form with the publisher name and a Publisher "Is" rule pre-filled.

- **Re-tag flagged comics**: A "Re-tag All" button appears on the comic list when filtering by `unknown_publisher` flag. Dispatches a Celery background task that re-applies DataManager rules to all flagged comics, clearing the `unknown_publisher` flag for any publisher now covered by a ruleset. Comics whose publisher still has no ruleset keep the flag.

- **Scrape skip flag (P2.7)**: Comics can be marked to skip batch scraping via a `scrape_skipped` flag. Toggled from the comic detail Actions menu and per-row Skip/Un-skip buttons on the imported list. Batch scrape excludes flagged comics. "Confirm each" defaults to checked on the imported state. Cancel during confirm-each mode skips the current comic instead of freezing.

- **Missing Format review queue item**: Comics that complete format detection with no format assigned are now flagged with `missing_format`. The flag is cleared when a format is eventually set. A "Missing Format" entry in the dashboard Review Queue links to all affected comics for manual assignment.

### Fixed

- **Stuck "Queued…" task toast that could never be dismissed**: A task-progress toast pinned to a forgotten task id (one Celery reports as `PENDING` because its result row was cleaned up or never written) no longer resumes on page load. The resume block now only restarts polling for `STARTED` or `PROGRESS` states, the `task-progress` endpoint clears the stale id from the session for `PENDING` and `REVOKED` states, and the **Dismiss** button is now shown in every state and clears the session id via a new `task-dismiss/<id>/` endpoint. Previously such a toast showed "Queued…" forever, ignored Cancel, offered no Dismiss, and reappeared on every hard refresh.

- **Cover hashes persisted when hash match finds no candidate**: When hash matching computes cover hashes but finds no candidate within the Hamming distance threshold (or all candidates fail metadata cross-validation), the computed pHash and aHash are now immediately saved to the database. Previously they were only saved as a side effect of applying a match, so they were lost whenever scraping found no match at all.

- **Refresh File Info hash status reporting**: The Refresh File Info action now appends a hash-specific note to its response. CBZ files where the cover image cannot be read report a warning; non-CBZ formats (PDF, CBR) report that cover hashes are not supported for the file format. Previously all cases silently showed "No changes detected".

- **Duplicate Review UX improvements**: (1) Each group card now shows a tip explaining that deleting unwanted comics causes the last one to be auto-kept, and that "Keep & Del Rest" resolves everything in one step. (2) Pressing "Keep" on a comic now automatically sets `format_ok = True` on the winner. (3) Series links in the group card and the "View" button in the group detail page now open in a new tab. (4) The "Keep & Del Rest" confirmation uses the DaisyUI custom modal instead of the browser `confirm()` popup.

- **Comic list column selector alphabetical order**: The "Visible Columns" dropdown now lists columns sorted alphabetically by label, making it easier to find a specific column in long lists.

- **Batch log "Info" link**: The UUID column in `/settings/log/` is now an "Info" button that opens the comic detail page in a new tab, replacing the raw truncated UUID badge.

- **Re-organize Queue: completion toast showed "0 processed"**: `successText()` and `progressText()` in `base.html` now handle the `moved` result field. The toast completion message now reads "X moved, Y already ok (of Z)" instead of falling through to the generic `processed` fallback.

- **Re-organize Queue: moves not logged to batch log (BUG.22)**: `reorganize_all_flagged_task` now calls `log_batch_entry("organize_all", ...)` for each file it actually moves, recording old and new paths. Entries appear in `/settings/log/` under the "organize_all" filter.

- **Comic list "No Comics Found" empty state**: Removed the docker import command hint from the empty-state message in the comic table. The message now simply reads "No Comics Found".

- **Column header sorting broken (UI.21)**: Clicking a column header was silently falling back to series sort because the COLUMNS_REGISTRY `sort` values (`page_count`, `updated_at`, etc.) did not match the aliases used as keys in the view's `sort_fields` dict (`pages`, `updated`). All sort keys are now unified to use the actual model field names. The sort dropdown option values have been updated to match. Any column present in the table is now sortable via header click, including credits and custom-value columns, using a safe fallback of `[field, series, volume, number]` for columns without an explicit multi-field sort definition.

- **Pages column sort with NULL values**: Sorting by page count now places comics with no page count at the bottom in both ascending and descending order. Previously, a descending sort put all NULL-page-count comics first, making the result appear random.

- **Custom confirm/alert modals (UI.18)**: All browser-native `confirm()` and `alert()` calls across 11 templates replaced with custom DaisyUI modals. Two global helpers added to `base.html`: `showConfirm(message, onConfirm, label, danger)` shows a dialog modal with Cancel and a styled Confirm button (red when `danger=true`); `showMsgToast(message, type)` shows a non-blocking toast notification (info/success/error) that auto-hides after 4 seconds without reloading the page. Form-based deletes (rulesets, profiles, smart lists) now use a button with `onclick` instead of `onsubmit` on the form, keeping the same UX.

- **Format detection rewritten to follow canonical rules**: `detect_format` now follows the 3-step algorithm defined in `Comic_Book_Format_Definitions.md`. Step 1 checks edition modifiers (Director's Cut, Black & White) from series/title text. Step 2 checks collection formats: Omnibus by keyword or page_count ≥ 300, TPB by keyword or (page_count ≥ 80 + issue range in description like "#1-5"). Step 3 classifies by issue count (Annual → One-Shot → Limited Series → Main Series). The old pattern-list approach that included formats like HC, Special, Giant-Size, King-Size, and Deluxe has been removed; only the 8 supported formats remain. The duplicate `FORMAT_PATTERNS` and `_detect_format` in `views.py` have been removed — views now import `detect_format` from `services.py`.

- **format_ok field**: New `BooleanField(default=False)` on `Comic`. When `format_ok=True`, auto-detection will not overwrite the comic's format and count changes will not set `needs_reformat=True`. The field is exposed as a "Format confirmed" checkbox on the edit page. Migration `0007_comic_format_ok` added.

- **Page count visible during format review**: The format detection modal now shows issue count and page count alongside series and title, making it easier to distinguish TPBs from limited series on low issue counts. Both tables in the Format Review page now include a Pages column.

- **scrape_no_match flag not cleared on manual re-scrape**: `apply_cv_match` now removes `scrape_no_match`, `scrape_error`, and `scrape_error_detail` on every successful match. Previously these flags were only cleared by the batch task path, so comics manually re-scraped via the UI would advance state but still show as flagged in the dashboard review queue.

- **Edit page: clear flags inline**: The comic edit page now shows an "Active Flags" section when a comic has any flags set. Each flag is displayed as a badge with a checkbox; checking it and saving removes the flag from the database. Previously flags could only be cleared via specific action buttons on the detail page.

- **Edit page: save to DB without writing XML**: The comic edit form now defaults to a DB-only save ("Save to DB" button). A second "Save + Write XML" button is available for digital CBZ comics when you want to immediately write ComicInfo.xml as well. Previously every save on a digital comic unconditionally wrote the XML.

### Added

- **Smart search tokens in comic list**: The search box now parses structured modifiers out of the query string. `#N` filters by exact issue number (e.g. `Batgirl #10`), `(YYYY)` filters by year (e.g. `Batman (1940)`), and `VYYY` filters by volume (e.g. `Batman V2`). Tokens can be combined freely: `Grant Morrison V2 #15 (2016)` searches credits/series for "Grant Morrison" and then AND-filters to volume 2, issue 15, year 2016. A `#N`-only query (no text) returns all comics with that issue number.

- **Expanded comic list search fields**: Free-text search now queries writer, penciller, inker, colorist, letterer, cover artist, editor, characters, teams, genre, and notes — in addition to series, title, publisher, and number.

- **Re-organize auto-detection**: Comics in the `organized` or `written` state are now automatically flagged `needs_reorganize=True` when a path-relevant metadata field changes (`publisher`, `series`, `format`, `main_character_or_team`, `volume`). A `post_save` signal handles per-comic detection; a separate `pre_save` signal on `OrganizerProfile` flags all organized/written comics when `folder_template`, `file_template`, or `base_folder` is changed. A dashboard widget shows the queue count and provides a direct "Re-organize All" button when any comics are flagged.

- **Scraper service layer**: Extracted the ComicVine matching logic from `apps/core/views.py` (interactive scrape modal) and `apps/scraper/views.py` (dry-run preview) into a single `apps/scraper/services.py`. Published functions: `try_hash_match`, `try_metadata_match`, `apply_cv_match`, `metadata_alignment_score`, `series_matches`, `normalize_issue_number`. The batch task (`core/tasks.py`) and management command (`scraper/management/commands/scrape.py`) now import from the service layer instead of from a views module. The unified `metadata_alignment_score` uses `series or proposed_series` so it works for both fresh imports and re-scrapes.

- **STATE_NEW search and filter improvements**: Searching on the `?state=new` comic list now queries `proposed_series`, `proposed_number`, and `file_path` instead of the core metadata fields that are null for unscraped comics. Publisher, Format, and Medium filter dropdowns are hidden for the `new` state. Sort options are replaced with `Proposed Series`, `Proposed #`, `Year`, `Pages`, and `Updated` when viewing the `new` list.

- **Inline editing on STATE_NEW list**: Comics in the `new` state now support click-to-edit directly in the table. Clicking a cell for `proposed_series`, `proposed_number`, `proposed_volume`, `publisher`, or `format` opens an inline input (text, number, or select) via HTMX. Confirming saves the value and reverts the cell; cancelling discards changes. The `new` state now defaults to a `proposed_*`-focused column layout (`proposed_series`, `proposed_number`, `proposed_volume`, `proposed_year`, `publisher`, `format`, `pages`, `file_format`).

- **Batch audit log**: All three batch pipeline actions (Scrape All, Tag All, Format All) now write a JSON Lines audit log to `./data/logs/batch_actions.jsonl`. Each entry records the action, comic name and UUID, state transition, and a diff of changed fields. Failed scrapes are logged with `result: no_match` or `result: error`. The log is viewable at `/settings/log/` with tabs to filter by action type, a per-comic changes summary, copyable UUID badge, and pagination.

- **Rollback from batch log**: Each log entry has a "Send back" button that resets the comic to its previous state: scrape successes roll back to `imported` (clearing CV data and flags), failed scrapes roll back to `new` (phase 1), tag entries roll back to `counted` (clearing `series_group`, `main_character_or_team`, `DataManager_Processed`), format entries roll back to `tagged` (clearing `format`). The row updates in place via HTMX to show a confirmation.

- **Extended smart list filter fields**: `ALLOWED_FIELDS` and the filter field dropdown now support `proposed_series`, `proposed_number`, `proposed_volume`, `proposed_year` (filename-parsed values for STATE_NEW comics), all nine `flags__*` keys (`low_page_count`, `is_pdf`, `no_series`, `cover_only`, `needs_conversion`, `missing_count`, `count_mismatch`, `scrape_no_match`, `scrape_error`), `file_format`, `needs_reorganize`, `needs_reformat`, `last_written`, `imported_at`, and two additional CV custom value fields (`comicvine_issue`, `scrape_source`). Added `Import Date` and `Last Written` as sort options. README documents flag filter usage (field, lookup, value) for all flag types.

- **Celery notifications for all batch actions**: All batch operations (Tag All, Format All, Organize All, Scrape All, Scan Untagged, Convert CBR/CB7, Deduplicate All) now run as Celery tasks with a real-time progress bar toast. The toast shows current/total counts, a progress bar, and status text. After completion, any per-comic errors are listed in a scrollable panel inside the toast. The toast stays open until explicitly dismissed, and includes a "View batch log" link. Scrape results now show a matched/failed breakdown (e.g. "37 matched, 12 failed (of 49)") instead of a generic processed count.
- **Task cancel button**: All Celery batch tasks support cooperative cancellation. A "Cancel" button appears in the progress toast while a task is running. Clicking it sets a Redis flag; the worker finishes the current comic and stops before starting the next one. The toast reports how many items were processed before cancellation.
- **Scrape error flags**: Comics that fail during `scrape_all` are now flagged automatically. `scrape_no_match` (boolean) is set when no ComicVine match is found; `scrape_error` (boolean) and `scrape_error_detail` (message string) are set when an exception occurs. Both flags are cleared at the start of each scrape attempt so retrying is clean. The flags appear in the dashboard review queue ("Scrape: No Match" and "Scrape: Error") with View links to filter the comic list.
- **Search Alt Covers now async**: The "Search Alt Covers" action dispatches a Celery task for the image download and CBZ insertion phase, so the page no longer blocks while covers are downloaded.
- **Single-comic action results in toast**: Fast single-comic actions (Re-tag, Re-format, Re-organize, etc.) no longer do a silent page reload. Results are shown briefly in the notification toast via `showQuickToast()` before the page refreshes.
- **Task failure dismiss button**: When a batch task finishes with errors or fails entirely, a "Dismiss" button replaces the auto-hide timer so the user can read the error details before reloading.

- **Metadata mismatch audit**: New "Audit Metadata Mismatches" background task under Settings > Database Audits. Compares each comic's local `series` name against the linked ComicVine volume name in `comicvine.db`. Comics with a significant name mismatch (neither name contained within the other, after stripping non-alphanumeric characters) are flagged `metadata_mismatch`. The flag appears in the dashboard review queue and is available as a Smart List filter field. The task reports real-time flagged/cleared counts in the progress toast. Results are written to the Batch Log (filterable by the new "Audit" tab); each entry has a "To Scrape" rollback button to clear the bad match data and reset the comic to `imported` for re-scraping. Requires `comicvine.db` — the button is disabled when only MCL or API is available.

- **`metadata_mismatch` dashboard Review Queue and scrape UI**: The `metadata_mismatch` flag now appears as a row in the dashboard Review Queue table with a count and "View" link. The flag list view at `/comics/?flag=metadata_mismatch` now shows the full scrape UI: a "Scrape All" button with "Confirm each" toggle and per-row "Scrape" buttons. All scrape requests from this view pass `?force=1` to bypass the `imported`-only state check. `apply_cv_match` now clears the `metadata_mismatch` flag after any successful re-scrape (batch and individual paths), resetting the comic to `counted` to continue through the pipeline.

- **Batch audit log extended to organize and write**: The batch audit log now covers all pipeline stages. `organize_all` entries record the old and new file path when a comic is moved. `write_all` entries record ComicInfo.xml writes. Both action types are filterable in the batch log UI at `/settings/log/`. The `_run_organize` and `_run_write` helpers in `apps/dashboard/tasks.py` (used by Smart List actions) also write to the log, matching the bulk-task coverage.

- **ComicVine API-only mode**: The scraper now auto-detects when `comicvine.db` is absent and gracefully falls back to the ComicVine REST API for batch scraping and the `latest.mcl` CSV file for volume completion / Series Audit. Key additions:
  - `apps/scraper/cv_sources.py`: availability helpers (`is_cv_db_available`, `is_mcl_available`, `get_cv_source_status`), a `latest.mcl` parser (`load_mcl_index`, `get_volume_completion_from_mcl`), and a Redis-backed rolling API call budget tracker (`increment_api_call_count`, `check_api_budget`, 200 calls/hour limit).
  - `try_api_metadata_match()` in `apps/scraper/services.py`: queries `search_api()`, scores candidates with `metadata_alignment_score`, fetches full credits via `get_issue_from_api()`, and respects the budget before each call.
  - `apps/scraper/comicvine.py`: `_api_request()` now increments the budget counter on every successful call.
  - `apps/core/tasks.py` (`scrape_all_task`): checks `is_cv_db_available()` and stops with a user-visible message when the API budget is exhausted mid-run.
  - `apps/dashboard/services.py` (`get_volume_completion`): tries DB first, then MCL, then returns `{"unavailable": True, "reason": "..."}` when neither source is present.
  - Settings page: shows a "ComicVine Data Sources" status block (DB / MCL / API key badges and current mode).
  - Dashboard: shows an API budget banner (remaining calls + progress bar) when operating in API-only mode.
  - Series Audit and Character Audit pages: show a disabled-with-message banner when neither DB nor MCL is available.
  - `docker-compose.yml`: optional `./data/latest.mcl:/cv_db/latest.mcl:ro` volume mount for the MCL file.
  - `cv_mcl_path` added as a runtime setting (default `/cv_db/latest.mcl`) in `apps/core/signals.py`.

- **Navigable Lightbox Gallery**: Refactored the image lightbox into a full navigable gallery. Supports "Previous" and "Next" navigation via on-screen arrows (desktop), keyboard arrows (Left/Right), and horizontal swipe gestures (mobile/tablet). Includes an image counter (e.g., "2 / 5") and dynamic captions.
- **Page Manager Lightbox Previews**: Clicking any page thumbnail in the "Manage Pages" modal now opens the navigable lightbox. The gallery is built dynamically from the current state of the reorderable grid, allowing users to verify page content even for newly uploaded or reordered pages before saving.
- **CBZ Page Manager**: "Manage Pages" button on digital comic detail pages opens a modal to reorder, delete, and add pages inside a CBZ file. Drag-and-drop reordering via Sortable.js. Per-page delete with red overlay preview. Upload staging is client-side: select an image and it appears at the front of the grid immediately, no server call until "Save Changes". All operations (reorder, delete, new pages) are committed atomically in a single POST to a new `/pages/save/` endpoint. Cover and page thumbnail cache is automatically invalidated after save.
- **Variant cover scraping, file insertion, and gallery preview**: After scraping a comic, variant covers are automatically fetched from ComicVine, downloaded, and inserted into the CBZ file after the main cover. A gallery of variant cover thumbnails is shown on the comic detail page. Clicking any thumbnail opens it in the full-size image lightbox.
- **Custom value editing in comic edit form**: The comic edit page now includes an editable table for `CustomValues` (the JSON field storing ComicVine IDs and non-standard metadata). Rows can be added, edited, and removed directly in the form.
- **State reset in comic edit form**: Comic edit form has a new "Reset State" option to move a comic back to an earlier workflow state, useful for forcing a re-run of a specific pipeline phase.
- **Auto-scan page count on comic detail**: When a digital comic's page count is missing (null/0), the detail page now automatically extracts and saves it from the CBZ file on first load.
- **Cover lightbox on comic detail**: The cover thumbnail in the comic detail header is now clickable and opens the full-size image in the existing lightbox modal. Click anywhere outside the image to dismiss.
- **Settings for low page count and cover-only detection**: Import scan thresholds for `low_page_count` and `cover_only` flags are now configurable via the Settings page instead of being hardcoded.
- **Dynamic column customization**: Complete system for customizing table columns across the app. Includes a global `COLUMNS_REGISTRY` in `core.utils` supporting 50+ fields (metadata, credits, file info, system timestamps, and custom JSON values). Column layouts persist per workflow state and per Smart List. A column picker dropdown is available on the main comic list; Smart Lists have a selection grid in their form.
- **Numeric rule operators in organizer profiles (P7.12)**: Profile matching rules now support numeric comparison operators: `greater than`, `less than`, `greater than or equal to`, and `less than or equal to`. The `Count` and `Page Count` fields are added to the rule engine field map. When a numeric field is selected in the rule builder the operator dropdown updates to show both text and numeric operators. This enables patterns like matching TPBs where `Count greater than 1` to apply a different folder template than standalone collected editions.

- **Indexed access to comma-separated template fields**: Template placeholders for comma-separated fields (`writer`, `penciller`, `characters`, etc.) now support index and name-part modifiers. `{<writer[1]>}` returns the first writer's full name; `{<writer[2]>}` the second. Append `[l]` for last name or `[f]` for first name: `{<writer[1][l]>}` → `Dixon`, `{<writer[1][f]>}` → `Chuck`. Out-of-range indices render as empty so they compose safely with conditional segments (e.g. `{ by <writer[1][l]>}`). Works on any field that stores comma-separated values.

- **Drag-and-drop priority reordering for organizer profiles**: The profile list at `/organizer/profiles/` now has a drag handle column. Rows can be dragged up or down to reorder them; priority numbers update live as rows move. The new order is persisted immediately via a `POST /organizer/profiles/reorder/` endpoint using `bulk_update`.

- **Organizer profile rule editor**: Full UI for creating and editing matching rules on organizer profiles, including nested rule groups with AND/OR logic. Supports all fields (Publisher, Format, Series Group, Tags, etc.) and operators (is, contains, starts with, etc.). Profiles imported from `.lop` files are now fully editable.
- **Corrupted archive flag and recovery**: CBZ files that cannot be opened (truncated or corrupted ZIP) are now automatically flagged `corrupted_archive` at import time and on first detail-page visit for already-imported comics. The comic detail page shows a prominent error alert with a "Try Rezip" button that attempts to recover the archive by re-extracting all readable entries and repacking them in place. If recovery succeeds, the flag is cleared and page count updated. If the archive is too damaged (central directory unreadable), the alert tells the user to delete and reimport a working copy. The flag appears in the dashboard review queue and is available as a Smart List filter field.
- **Issue count management**: Detect and populate missing issue counts from the local ComicVine SQLite DB. Auto-flags comics with `missing_count` during scraping when no count is returned. Detects count mismatches within the same `comicvine_volume` and flags them with `count_mismatch`. Dashboard review queue shows both flags with "Populate Counts" and "Detect Mismatches" action buttons.
- **Tags, Teams, Locations fields**: New model fields for tags, teams, and locations (comma-separated TextFields). Displayed on comic detail page and editable on edit page. Added to `FIELD_MAP` so they read/write from `ComicInfo.xml`.
- **ComicDb.xml import support**: `import_library --comicdb /path/to/ComicDb.xml` enriches imports with data from ComicRack's master database: Tags, Teams, Locations, MainCharacterOrTeam, SeriesGroup, and CustomValuesStore. Uses memory-efficient iterparse for ~44K entries. `ComicInfo.xml` values take precedence; `ComicDb.xml` fills in gaps.
- **Smart Lists**: Saved, named queries with filters on Comic model fields. Create lists with multiple filter criteria (field, lookup, value), optional sorting, and dashboard visibility toggle. Accessible from the main navigation bar. Smart Lists with `show_on_dashboard` enabled appear as cards on the dashboard with comic counts and completion progress bars.
- **Missing issues detection**: Link a Smart List to a ComicVine volume to compare your library against the full CV issue list. Shows completion percentage, owned vs missing issues, and a detailed comparison table with toggle filters (All / Missing / Owned). HTMX-powered volume search when creating or editing Smart Lists.
- **Search, filter, and sort for comic list**: `/comics/` now has a search bar (series, title, publisher, number), filter dropdowns (publisher, format, medium), and sortable column headers with ascending/descending toggle.
- **Server-side pagination**: `/comics/` and Smart List detail pages now use server-side pagination (100 per page, configurable 25-500 via `per_page` param). Prevents browser crashes on 40k+ comic libraries. Pagination controls at top and bottom with page number window.
- **ComicVine API fallback**: When the local ComicVine SQLite DB has no match, the scrape modal now shows a "Search API" section to query the live ComicVine API. Works in both the comic list scrape modal and the comic detail re-scrape modal. API key configured via `/settings/`.
- **4-way metadata comparison**: "Compare All Sources" on the comic detail page fetches data from all four sources (PostgreSQL DB, `ComicInfo.xml`, local `comicvine.db`, live CV API) and shows a side-by-side comparison table with Match/Different status per field.
- **API rate limit display**: When ComicVine returns HTTP 420/429, the UI shows a yellow warning alert with a clear "rate limited" message instead of a generic error.
- **Path audit page**: New page at Workflow > Path Audit to batch-scan all organized/written comics for path mismatches. Runs as a Celery task with real-time progress bar. Shows a table of flagged comics with current vs target paths, single-comic "Move" buttons, and a batch "Reorganize All" action.
- **Filename duplicate detection**: New detection method that catches OS-generated duplicate files by filename pattern. Detects Linux duplicates (`file_1.cbz`, `file_2.cbz`) and Windows duplicates (`file (1).cbz`, `file (2).cbz`). Runs as part of both "Run Detection" and "Scan All Comics". Shown in its own section on the duplicate review page.
- **Cover preview on comic detail page**: Digital comics now show a cover image thumbnail in the header next to the title and badges, extracted from the CBZ and served from cache.

### Changed

- **Unified scraper entry point**: All scraping code paths (batch task, management command, scrape modal views) now call a single `find_best_match(comic, scraper)` function in `apps/scraper/services.py`. The function internally decides whether to use the local ComicVine DB (hash + metadata) or the API (`try_api_metadata_match`), based on `is_cv_db_available()`. Callers no longer need to know which strategy was used.

- **Celery toast auto-dismiss on success**: The progress toast now automatically dismisses after 5 seconds when a batch task completes successfully, removing the need to manually click "Dismiss" for routine operations. Failed tasks still require a manual dismiss so the error details can be read.

- **Variant cover gallery improvements**: Updated insertion logic to include ComicVine's primary cover as a variant, as it often differs from the local file's cover. Gallery labels updated to "Local Cover" (for the local file), "Main" (for the primary online reference), and "Variant N" for subsequent covers.
- **Workflow pipeline reduced from 9 to 8 states**: Removed unused "scraped" state since scraping goes directly to "counted". Dashboard and comic list now show the correct 8-state workflow.
- **Organizer profiles use configured `base_folder`**: Profiles now use their own configured `base_folder` instead of the hardcoded `/comics/library` path, allowing each profile to organize comics into a different root folder.
- **Scraper now saves teams and locations**: The ComicVine scraper already extracted teams and locations from `comicvine.db` but silently dropped them. Both `_apply_match()` code paths now persist these fields.
- **"Format All" bulk action added**: The tagged state now has a "Format All" bulk action button.
- **Workflow navigation bar**: Comic list pages (`/comics/?state=XXX`) now show a clickable navigation bar with all 8 workflow states for easy jumping between stages.

### Fixed

- **PostgreSQL JSONField type mismatch for CV IDs**: `parse_comicinfo_xml` in `core/utils.py` now explicitly casts all `CustomValue` entries to `str`. Previously, numeric values imported from `ComicInfo.xml` could be stored as integers in the `custom_values` JSONField. PostgreSQL JSON lookups are type-sensitive, so string-based queries (e.g., `custom_values__comicvine_volume="93370"`) returned zero results when the stored value was the integer `93370`. This caused "0 Owned" counts in Series Audit and broke character audit search volume matching.

- **Series Audit showing wrong owned counts after CV ID type mismatch**: `get_volume_completion` (dashboard services) already filters with `custom_values__comicvine_volume=str(cv_volume_id)`, correctly handling string IDs. Comics stored with integer IDs during the pre-normalization period will be corrected the next time their `ComicInfo.xml` is re-imported or saved.

- **Scrape modal crashes when comicvine.db is absent**: `scrape_preview`, `scrape_comic`, and `force_scrape` views called `match_by_hash_fast`, `match_by_metadata`, `enrich_matches_with_covers`, and `get_issue_details` directly without checking whether the local DB was available. All three views now guard DB calls with `is_cv_db_available()` and route to `find_best_match` (API path) when the DB is absent.

- **API scrapes not logged to audit log**: `enrich_match_with_credits()` in `ComicVineScraper` tried to open a SQLite connection even when the DB was unavailable, raising `sqlite3.OperationalError`. This was caught by the outer `except Exception` in the batch task, causing comics to be flagged `scrape_error` instead of advancing to `counted`. Fixed by wrapping the `_get_connection()` call in a try/except inside `enrich_match_with_credits()`, returning the match unchanged when the DB is absent.

- **Variant cover indexing and metadata sync**: Fixed an issue where variant thumbnails pointed to the wrong page index. Comic page count is now automatically synchronized from the file after variant covers are inserted.
- **Dashboard pipeline circle overflow**: Workflow pipeline circles now expand into ovals for 4-6 digit counts, preventing text overflow.
- **ComicInfo.xml output parity**: XML output now matches ComicRack format: Tags mapped to model field (not CustomValues), Summary preserves paragraph breaks, Notes auto-populated with CV reference, Pages element with image dimensions, `DataManager_Processed` normalized to "Yes", standard field names filtered from CustomValues.
- **API rate limiting**: Added 1.1-second delay between ComicVine API calls to prevent HTTP 420 rate limit errors.
- **Natural number sorting**: Comic lists and Smart Lists now sort issue numbers numerically (1, 2, 3 ... 10, 11) instead of lexicographically (1, 10, 11 ... 2, 20).
- **HTML stripped from ComicVine summaries**: Summary/description fields from ComicVine are now passed through `strip_tags()` to remove HTML markup.
- **Smart List JSONField filtering**: Filtering on `custom_values__*` fields now works correctly. Previously, the value was coerced to an integer which did not match the string stored in the JSONField.
- **CSS watcher in Docker**: Tailwind CLI watcher now uses `--watch=always` so it stays alive in Docker containers where stdin closes.
- **Force actions now always advance state**: `force_organize` and `force_write` now correctly advance the workflow state from any earlier state, matching the existing behavior of `force_tag` and `force_format`.
- **Detail page actions now show result modals**: Re-tag, Re-format, and Re-organize on the comic detail page now display result modals instead of silently reloading.
- **Standardized all modals**: All modals now use DaisyUI's native `modal` component with centered positioning, dark backdrop, and consistent close behavior.
- **Cover ordering now prioritizes matched/official covers**: When scraping, the cover that matched via hash is shown first. For metadata matches, official ComicVine covers are prioritized over user-uploaded variants.
- **Force-tag now properly applies DataManager rules**: Previously, clicking "Re-tag" on the comic detail page would not apply rules if the comic was not in `counted` state. Now it bypasses the state check and applies all matching rulesets regardless of current state.
- **Variant cover gallery no longer shows stale images after Search Alt Covers**: Page image URLs now include `?v={page_count}` as a cache-busting parameter. When alt covers are inserted, `page_count` changes, causing the browser to fetch fresh images instead of serving cached story pages.


