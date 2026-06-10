# Workflow Pipeline

The core of ComicManager is its structured 8-stage pipeline. Instead of a single "Scan and Tag" operation, we break the process into discrete, verifiable phases.

![Workflow Overview](/pipeline.png)

## Dashboard

The dashboard shows a summary of your collection, the Review & Maintenance queue, and the pipeline overview. The pipeline section has three display variants you can switch between using the buttons at the top:

| Variant | Description |
|---------|-------------|
| **Segments** | A horizontal bar chart where each pipeline state is a proportional segment. Clicking a segment navigates to that state's comic list. |
| **Flow** | A node-based diagram with animated connectors showing how comics are progressing through each state. |
| **None** | Hides the pipeline chart entirely, leaving more screen space for the stat tiles and maintenance queue. |

The selected variant is saved to your display preferences and persists across sessions.

![Segments Pipeline](/pipeline_segments.png)

![Flow Pipeline](/pipeline_flow.png)


## Needs Your Attention

The **Needs your attention** card on the dashboard shows all flagged issues and maintenance items. It has three display styles you can switch between in **Settings > Display**:

| Style | Description |
|-------|-------------|
| **List** | A compact table with one row per issue type. Default. |
| **Grid** | A card grid where each issue type gets its own tile with a description and action button. |
| **Triage** | A ranked list ordered by urgency. Each item is numbered so you know exactly what to tackle first. |

![List](/needs_list.png)

![Grid](/needs_grid.png)

![Triage](/needs_triage.png)

### Triage ranking

In Triage mode, items are sorted by two keys, in order:

1. **Severity**: errors first, then warnings, then info items.
2. **Count descending**: within each severity tier, the issue type with the most affected comics ranks higher.

This gives the item most worth fixing right now the top position. The rank number shown in the circle reflects this combined priority score, not just count or severity alone.

### Maintenance items

Maintenance items (duplicates, stale metadata, re-organize needs, etc.) are lower-priority than active issues because they do not block the pipeline. They are hidden by default to keep the attention card focused.

Click the **+ N maintenance** button in the card header to reveal them inline, blending with the current display style:
- In **Grid**: maintenance items appear as additional tiles in the same grid.
- In **Triage**: they append below all active ranked items, continuing the numbering sequence. Active items retain their positions whether maintenance is shown or hidden.
- In **List**: they appear as additional rows at the end of the table.

Click **&minus; hide maintenance** to collapse them again.

![Needs Your Attention with maintenance expanded](/needs_expand.png)

![Dashboard editorial view](/overview_editorial.png)

![Dashboard minimal view](/overview_minimal.png)

## Weekly Summary Card

The **This Week** card on the dashboard shows a bar chart of import and pipeline activity over the past 14 days. Each bar represents one day; hovering shows the count. This gives a quick sense of recent throughput without opening the audit log.

![This Week card](/this_week.png)

The card can be shown or hidden via the checkbox in **Settings → Dashboard → Visible sections**.

## Priority Banner

When one pipeline stage holds a significantly larger backlog than the others, the dashboard shows a **priority banner** at the top of the pipeline section. It names the bottleneck stage and provides a direct action button so you can clear it without manually scanning the pipeline overview.

The banner can be shown or hidden via the checkbox in **Settings → Dashboard → Visible sections**.

![Priority banner](/start_here.png)

## The Review & Maintenance Queue

Throughout the pipeline, ComicManager continually audits your comics for issues, mismatches, or missing data. Instead of stopping the entire batch process, problem comics are flagged and sent to the **Needs your attention** card on your Dashboard.

The attention card covers two categories:

### Active Review
Issues that block a comic from properly proceeding through the pipeline.
- **Missing Series / Parse errors:** Filename couldn't be parsed.
- **ZIP Files:** Files with a `.zip` extension that need a one-click rename to `.cbz` before the Write phase.
- **Needs Conversion (CBR/CB7):** Non-native archives that must be converted to CBZ.
- **Low Page Count / PDFs / Cover Only:** Flagged for deletion or manual confirmation.
- **Scrape Errors:** Matches couldn't be found on ComicVine or API errors occurred.
- **Metadata Mismatches:** Local metadata conflicts with ComicVine volume information.
- **Missing Format / Conflicts:** Missing format, or comics in the same volume have conflicting formats.
- **Corrupted Archives:** The CBZ file cannot be read or unzipped. Use **Try Rezip** to attempt recovery.

### Maintenance
Issues that affect comics already deep in the pipeline (or fully written) that need your attention.
- **Duplicates:** Potential duplicates detected by ComicVine ID, Series/Number match, or cover image hashing.
- **Needs Re-organize:** Metadata was updated, meaning the current file path is now incorrect.
- **Needs Re-format:** The issue count for the volume changed, so count-based formatting (e.g., One-Shot vs. Limited Series) needs recalculation.
- **Stale Metadata / Missing ComicInfo:** The database has newer information than what is currently written inside the CBZ file.
- **Count Mismatch:** Disagreement between owned issues on the total volume count.
- **Format Mismatch:** Conflicting formats within the same ComicVine volume.
- **CV Volume Conflict:** Same series/number/format linked to different ComicVine volume IDs.

## Detailed Pipeline Phases

| Phase | Name | Purpose | Action button |
|-------|------|---------|---------------|
| 1 | New | Parse filename, review proposed values | Accept / Accept All |
| 2 | Scrape | Match against ComicVine or I.N.D.U.C.K.S. to fetch metadata | Scrape All |
| 3 | Tagging | Apply DataManager rules (series group, publisher, main character) | Tag All |
| 4 | Add Formats | Categorize as Main Series, TPB, One-Shot, etc. | Format All |
| 5 | Deduplicate | Detect duplicates by CV ID, metadata, or cover hash | Deduplicate All |
| 6 | Move Files | Move file to organized library path | Organize All |
| 7 | Write to CBZ | Embed `ComicInfo.xml` inside the archive | Write All |
| 8 | Done | Fully processed. Sync paths if files were moved externally. | Sync Paths |

### Phase 1: New
When a file is first scanned, we don't assume anything. We use regex-based filename parsing to extract a *proposed* series, number, volume, and year.
- **Purpose**: Identify the comic well enough to find it on ComicVine.
- **Action**: Review and edit proposed values inline. This is your first line of defense against messy filenames.
- **Scan for Comics**: Use the **Scan for Comics** button on this page to trigger a scan of the untagged drop folder and import any new files that have been placed there since the last scan.

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
- **Action**: Run **Organize All** to move files into the library folder.

### Phase 7: Write to CBZ
The final active step is writing the `ComicInfo.xml` metadata *inside* the CBZ file. This ensures that even if you move the file to another application (like ComicRack or Panels), your metadata travels with it.
- **Purpose**: Permanent, portable metadata integrity.
- **Action**: Run **Write All** to embed metadata into the file itself.

### Phase 8: Done
The comic is fully processed and written. This view shows your entire library. If metadata is updated after writing, use the Maintenance queue to re-organize or re-write stale files.
- **Purpose**: Overview of the complete library and ongoing sync tasks.
- **Action**: Run **Sync Paths** to scan for comics where the recorded file path no longer matches the file on disk (for example after an external move), update the database record, and remove any duplicate database entries found during the scan.
- **Status**: Your comic is fully processed.

## Run Full Pipeline

For CBZ files where you want everything done in one go, the **Run Full Pipeline** button skips the manual step-by-step process and runs all 8 phases automatically.

### Where to find it

- **Per-row button**: On the New phase comic list, each CBZ row shows a **Run Pipeline** button next to Accept. Only CBZ files show this button; CBR and other formats do not.
- **Bulk button**: The **Run Pipeline (All)** toolbar button on the New phase list runs the pipeline across every eligible CBZ in the table at once.
- **Comic detail sidebar**: The Actions card on any comic detail page has a **Run Pipeline** button. This runs the full pipeline for that single comic and opens the results modal when done.

### What it does

For each comic, the pipeline runs these steps in order:

```
  Accept proposed values
         │
         ▼
  Scrape (ComicVine match)
         │
    no match? ──▶ stop, set scrape_no_match flag
         │
         ▼
  Tag (DataManager rules)
         │
         ▼
  Detect Format
         │
         ▼
  Deduplicate
         │
   duplicate? ──▶ stop, send to Duplicate Review
         │
         ▼
  Organize (move to library)
         │
         ▼
  Write ComicInfo.xml ──▶ Done ✓
```

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
| **Delete** | Permanently deletes the selected comics and their files from disk |

### How it works

Bulk Action dispatches a Celery background task and uses the same progress toast, cancellation button, and audit log as the dashboard batch buttons. The task re-runs the same filter query the page used, so what you see is exactly what gets processed. If the task encounters a disk-full error or permission error it stops after the current comic and reports how many were processed.

### Task queuing

If you trigger a second batch action while one is still running, it is queued automatically and dispatched as soon as the first one finishes. The progress toast updates to "Starting next task…" between tasks. You do not need to wait and watch: queue up multiple actions and let them run in sequence.
