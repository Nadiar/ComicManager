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