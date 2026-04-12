# Workflow Pipeline

The core of ComicManager is its structured 8-stage pipeline. Instead of a single "Scan and Tag" operation, we break the process into discrete, verifiable phases.

![Workflow Overview](/pipeline.png)

## The Review & Maintenance Queue

Throughout the pipeline, ComicManager continually audits your comics for issues, mismatches, or missing data. Instead of stopping the entire batch process, problem comics are flagged and sent to the **Review & Maintenance Queue** on your Dashboard.

This queue consists of two tabs:

### Active Review
Issues that block a comic from properly proceeding through the pipeline.
- **Missing Series / Parse errors:** Filename couldn't be parsed.
- **ZIP Files:** Files with a `.zip` extension that need a one-click rename to `.cbz` before the Write phase.
- **Low Page Count / PDFs / Standalone Covers:** Flagged for deletion or manual confirmation.
- **Scrape Errors:** Matches couldn't be found on ComicVine or API errors occurred.
- **Metadata Mismatches:** Local metadata conflicts with ComicVine volume information.
- **Missing Format / Conflicts:** Missing format, or comics in the same volume have conflicting formats.
- **Corrupted Archives:** The CBZ file cannot be read or unzipped. Use **Try Rezip** to attempt recovery. See [Archive Repair](./archive-repair.md).

### Maintenance
Issues that affect comics already deep in the pipeline (or fully written) that need your attention.
- **Duplicates:** Potential duplicates detected by ComicVine ID, Series/Number match, or cover image hashing.
- **Needs Re-organize:** Metadata was updated, meaning the current file path is now incorrect.
- **Needs Re-format:** The issue count for the volume changed, so count-based formatting (e.g., One-Shot vs. Limited Series) needs recalculation.
- **Stale Metadata / Missing ComicInfo:** The database has newer information than what is currently written inside the CBZ file.

## Detailed Pipeline Phases

### Phase 1: New
When a file is first scanned, we don't assume anything. We use regex-based filename parsing to extract a *proposed* series, number, volume, and year.
- **Purpose**: Identify the comic well enough to find it on ComicVine.
- **Action**: Review and edit proposed values inline. This is your first line of defense against messy filenames.

### Phase 2: Scrape
Once the file is recognized and its internal metadata (page count, file size) is extracted, it is matched against ComicVine (or I.N.D.U.C.K.S.) to fetch series, issue count, credits, and cover data. ComicVine scrapes also populate the total issue count, which is used by later pipeline stages for format detection.

::: info I.N.D.U.C.K.S. comics
INDUCKS does not track total issue counts.
:::

- **Purpose**: Link the file to a metadata source.
- **Action**: Run **Scrape All** to match comics automatically, or use the manual scrape modal for individual issues.

### Phase 3: Tagging
This is where you apply your personal preferences. DataManager rules allow you to set "Series Groups" (e.g., "Batman Family"), "Main Character or Team," and standardize publisher names.
- **Purpose**: Apply your personal collection standard on top of the scraped metadata.
- **Action**: Run **Tag All** to apply your configured rules.

### Phase 4: Add Formats
Is this a One-Shot? A Trade Paperback? A Limited Series? The format phase uses a combination of title keywords, metadata, and issue count rules to categorize the comic.
- **Purpose**: Prepare for final organization by determining the type of comic.
- **Action**: Run **Format All** to detect formats automatically.

### Phase 5: Deduplicate
Duplicates are the enemy of a clean library. ComicManager detects them three ways: matching **ComicVine ID**, matching **Series and Number**, and **cover image hashing (pHash)** which catches duplicates even when filenames or metadata differ.
- **Purpose**: Ensure every issue in your library is unique.
- **Action**: Run **Deduplicate All** to scan for duplicates and resolve them in the duplicate review UI.

### Phase 6: Move Files
The file is moved from the `untagged` directory into your library. The destination path is built using your **Organization Profile** (e.g., `Publisher/Series (Year)/Series #Issue.cbz`).
- **Purpose**: Place the file in its final, standardized location.
- **Action**: Run **Move All** to move files into the library folder.

### Phase 7: Write to CBZ
The final active step is writing the `ComicInfo.xml` metadata *inside* the CBZ file. This ensures that even if you move the file to another application (like ComicRack or Panels), your metadata travels with it.
- **Purpose**: Permanent, portable metadata integrity.
- **Action**: Run **Write All** to embed metadata into the file itself.

### Phase 8: All Comics
The comic is fully processed and written. This view shows your entire library. If metadata is updated after writing, use the Maintenance queue to re-organize or re-write stale files.
- **Purpose**: Overview of the complete library and ongoing sync tasks.
- **Status**: Your comic is fully processed.

## Run Full Pipeline

For CBZ files where you want everything done in one go, the **Run Full Pipeline** button skips the manual step-by-step process and runs all 8 phases automatically.

### Where to find it

- **Per-row button**: On the New phase comic list, each CBZ row shows a **Run Pipeline** button next to Accept. Only CBZ files show this button; CBR and other formats do not.
- **Bulk button**: The **Run Pipeline (All)** toolbar button on the New phase list runs the pipeline across every eligible CBZ in the table at once.

### What it does

For each comic, the pipeline runs these steps in order:

1. **Accept**: copies proposed values (series, number, volume, year) to confirmed fields.
2. **Scrape**: matches against ComicVine to fetch full metadata and cover.
3. **Tag**: applies your DataManager rules (series group, main character, publisher standardization, etc.).
4. **Format**: detects the format (One-Shot, TPB, Omnibus, etc.).
5. **Deduplicate**: checks for duplicates. Stops here if a duplicate is found.
6. **Organize**: moves the file into the library using your Organization Profile.
7. **Write**: embeds ComicInfo.xml into the CBZ file. Comic is now Done.

### Results modal

After the pipeline finishes, a results modal opens:

- **Single comic**: shows a detailed breakdown of each step; the ComicVine match (with cover), tag rule changes, format detection patterns, and old/new file path.
- **Bulk run**: shows a summary table with one row per comic and the outcome (Written, Duplicate, Error).

Comics identified as duplicates show a "View Original" link. Successfully processed comics show a "View Comic" link. Dismissing the modal reloads the page so the processed comics are removed from the New list.

### Limitations

- Only CBZ files are supported. CBR and CB7 files must be converted first (use the Convert button in the row), then run the pipeline.
- The scrape step requires a ComicVine match. If no match is found the pipeline stops and marks the comic as an error.
- If a comic is flagged as a duplicate it stops at the deduplication step and is not moved or written.

## Bulk Actions

Every comic list view (pipeline stages, flag views, and smart lists) has a **Bulk Action** dropdown in the toolbar. It applies an action to exactly the comics currently visible in the table, respecting any active search terms, filters, and sort order.

### Available actions

| Action | What it does |
|--------|-------------|
| **Scrape** | Runs the ComicVine (or I.N.D.U.C.K.S.) scrape on each comic |
| **Tag / Re-tag** | Applies your DataManager rulesets |
| **Detect Format** | Re-runs format detection |
| **Organize** | Moves each comic to its library path |
| **Force Write** | Embeds ComicInfo.xml even if validation would normally block it |
| **Suppress Flag** | Marks the active flag as accepted (available on `?flag=X` views only) |

### How it works

Bulk Action dispatches a Celery background task and uses the same progress toast, cancellation button, and audit log as the dashboard batch buttons. The task re-runs the same filter query the page used, so what you see is exactly what gets processed. If the task encounters a disk-full error or permission error it stops after the current comic and reports how many were processed.
