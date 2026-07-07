# Workflow Pipeline

The core of ComicManager is its structured 8-stage pipeline. Instead of a single "Scan and Tag" operation, we break the process into discrete, verifiable phases.

![Workflow Overview](/pipeline.png)

## Detailed Pipeline Phases

| Phase | Name | Purpose | Action button |
|-------|------|---------|---------------|
| 1 | New | Parse filename, review proposed values | Accept / Accept All |
| 2 | Scrape | Match against ComicVine or I.N.D.U.C.K.S. to fetch metadata | Scrape All |
| 3 | Tagging | Apply tagging rules (series group, publisher, main character) | Tag All |
| 4 | Add Formats | Categorize as Main Series, TPB, One-Shot, etc. | Format All |
| 5 | Deduplicate | Detect duplicates by CV ID, metadata, or cover hash | Deduplicate All |
| 6 | Move Files | Move file to organized library path | Organize All |
| 7 | Write to CBZ | Embed `ComicInfo.xml` inside the archive | Write All |
| 8 | Done | Fully processed. | n/a |

### Phase 1: New

![In-line edit of values](/stage_new.png)

When a file is first scanned, regex parsing extracts a proposed series, number, volume, and year without assuming anything about the filename. Review and edit these values inline before moving on. Accurate proposed values make ComicVine matching more reliable. Use the **Scan for Comics** button to import new files placed in the untagged drop folder since the last scan.

### How proposed values are found

Filenames are parsed with a fixed sequence of regex steps, each one consuming the part of the string it matched before the next step runs (`apps/core/management/commands/scan_untagged.py::parse_filename`):

```
  Filename
     |
     v
  1. Extract year
     r'\((\d{4})\)'                          e.g. "(2024)" -> year=2024
     |
     v
  2. Strip all (...) groups
     r'\s*\([^)]*\)'                         removes year, "Digital", scanner tags, etc.
     |
     v
  3. Extract volume
     r'\b[vV](?:ol(?:ume)?\.?\s*)?(\d+)\b'   e.g. "v2", "Vol. 3", "Volume 4"
     |
     v
  4. Extract issue number (first pattern that matches)
     a. r'#(\d+(?:\.\d+)?)'                  hash format: "#001", "#12.1"
     b. r'\s+(\d{2,4})\s*$'                  trailing 2-4 digit number: "006"
     c. r'\s+(\d+(?:\.\d+)?)\s*$'            trailing single digit or decimal: "5", "1.5"
     |
     v
  5. Whatever remains, trimmed, is the series name
     r'\s+' -> single space, r'\s*-\s*$' -> drop a trailing dash
```

**Example:** `Batman Beyond - Neo-Gothic 006 (2024) (Digital)`

| Step | Regex | Result |
|------|-------|--------|
| 1. Year | `\((\d{4})\)` | `(2024)` found, year = 2024 |
| 2. Strip parens | `\s*\([^)]*\)` | `Batman Beyond - Neo-Gothic 006` |
| 3. Volume | `\b[vV](?:ol(?:ume)?\.?\s*)?(\d+)\b` | no match, volume = None |
| 4. Number | `\s+(\d{2,4})\s*$` (no `#`, so this pattern fires) | trailing `006` matches, number = "6" |
| 5. Series | remainder, trimmed | `Batman Beyond - Neo-Gothic` |

**Example:** `Amazing Spider-Man v2 #001 (1999)`

| Step | Regex | Result |
|------|-------|--------|
| 1. Year | `\((\d{4})\)` | `(1999)` found, year = 1999 |
| 2. Strip parens | `\s*\([^)]*\)` | `Amazing Spider-Man v2 #001` |
| 3. Volume | `\b[vV](?:ol(?:ume)?\.?\s*)?(\d+)\b` | `v2` matches, volume = 2 |
| 4. Number | `#(\d+(?:\.\d+)?)` | `#001` matches, number = "1" |
| 5. Series | remainder, trimmed | `Amazing Spider-Man` |

**Example:** `X-Men (2021) 001`

| Step | Regex | Result |
|------|-------|--------|
| 1. Year | `\((\d{4})\)` | `(2021)` found, year = 2021 |
| 2. Strip parens | `\s*\([^)]*\)` | `X-Men 001` |
| 3. Volume | `\b[vV](?:ol(?:ume)?\.?\s*)?(\d+)\b` | no match, volume = None |
| 4. Number | `\s+(\d{2,4})\s*$` (no `#`, so this pattern fires) | trailing `001` matches, number = "1" |
| 5. Series | remainder, trimmed | `X-Men` |

### Phase 2: Scrape

![Scrape window with auto matching](/scrape_db.png)

Once the proposed values are confirmed, ComicManager matches the file against ComicVine (or I.N.D.U.C.K.S.) to pull in full metadata: series, issue count, credits, and cover image. The total issue count from this step feeds directly into format detection later in the pipeline. Run **Scrape All** to process the queue automatically, or open the scrape modal on any individual comic to review and confirm a match manually.

::: info Note
INDUCKS does not track total issue counts.
:::

### Phase 3: Tagging

![Example of tagging rules](/tags.png)

Tagging rules let you apply your personal collection standard on top of the scraped metadata: assigning series groups (e.g. "Batman Family"), setting the main character or team, and standardizing publisher names. Run **Tag All** to apply your configured rulesets to every comic in this state.

### Phase 4: Add Formats

![Overview of formats ready to be applied](/formats.png)

The format phase categorizes each comic as a Main Series issue, Trade Paperback, One-Shot, Limited Series, or other format, using a combination of title keywords, metadata, and issue count rules. Run **Format All** to detect formats automatically.

### Phase 5: Deduplicate

![Deduplication](/dupe.png)

ComicManager detects duplicates three ways: matching ComicVine ID, matching series and number, and cover image hashing, which catches duplicates even when filenames or metadata differ. Run **Deduplicate All** to scan for duplicates and review them in the duplicate UI.

### Phase 6: Move Files

The file is moved from the untagged drop folder into your organized library. The destination path is built from your **Organization Profile** (e.g. `Publisher/Series (Year)/Series #Issue.cbz`). Run **Organize All** to move files into the library.

### Phase 7: Write to CBZ

The final active step embeds a `ComicInfo.xml` file inside the CBZ archive, making metadata portable across any application that reads it (ComicRack, Panels, etc.). Run **Write All** to embed metadata into every file in this state.

### Phase 8: Done

This view shows your entire written library. If metadata was updated after writing, the Maintenance queue surfaces comics that need re-organizing or re-writing. See [Syncing Library Paths](/guide/organizing#syncing-library-paths) for reconciling records where the stored file path no longer matches the file on disk, for example after an external move. That logic exists and works, but is not yet wired to a button in this view.

## Run Full Pipeline

For CBZ files where you want everything done in one go, the **Run** button skips the manual step-by-step process and runs all 8 phases automatically.

### Where to find it

- **Per-row button**: On the New phase comic list, each CBZ row shows a **Run** button next to Accept. Only CBZ files show this button; CBR and other formats do not.
- **Bulk button**: The **Run Pipeline** toolbar button on the New phase list runs the pipeline across every eligible CBZ in the table at once.
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
        Tag 
         │
         ▼
      Format
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
3. **Tag**: applies your tagging rules (series group, main character, publisher standardization, etc.).
4. **Format**: detects the format (One-Shot, TPB, Omnibus, etc.).
5. **Deduplicate**: checks for duplicates. Stops here if a duplicate is found.
6. **Organize**: moves the file into the library using your Organization Profile.
7. **Write**: embeds ComicInfo.xml into the CBZ file. Comic is now Done.

### Results modal

![Results of a **Run Pipeline**](/results_modal.png)

After a single-comic pipeline run finishes, a results modal opens with a detailed breakdown of each step: the ComicVine match (with cover), tag rule changes, format detection patterns, and old/new file path. A duplicate comic shows a "View Original" link; a successfully processed comic shows a "View Comic" link. Dismissing the modal reloads the page so the processed comic is removed from the New list.

Bulk pipeline runs (the toolbar button, or running on more than one comic) do not open this modal. Progress and the final count are shown in the task toast instead.

### Limitations

- Only CBZ files are supported. CBR and CB7 files must be converted first (use the Convert button), then run the pipeline.
- The scrape step requires a ComicVine match. If no match is found the pipeline stops and marks the comic as an error.
- If a comic is flagged as a duplicate it stops at the deduplication step and is not moved or written.

## Bulk Actions

Every comic list view (pipeline stages, flag views, and smart lists) has a **Bulk Action** dropdown in the toolbar. It applies an action to exactly the comics currently visible in the table, respecting any active search terms, filters, and sort order.

### Available actions

| Action | What it does |
|--------|-------------|
| **Scrape** | Runs the ComicVine (or I.N.D.U.C.K.S.) scrape on each comic |
| **Tag / Re-tag** | Applies your tagging rulesets |
| **Detect Format** | Re-runs format detection |
| **Organize** | Moves each comic to its library path |
| **Force Write** | Embeds ComicInfo.xml even if validation would normally block it |
| **Suppress Flag** | Marks the active flag as accepted (available on `?flag=X` views only) |
| **Delete** | Permanently deletes the selected comics and their files from disk |

### How it works

Bulk Action dispatches a background task and uses the same progressbar, cancellation button, and audit log as the dashboard batch buttons. The task re-runs the same filter query the page used, so what you see is exactly what gets processed. If the task encounters a disk-full error or permission error it stops after the current comic and reports how many were processed.

### Task queuing

If you trigger another batch action while one is running, it joins a queue and runs after the current one finishes. Everything runs one at a time, in the order you triggered it.

The queue lives on the server, not in your browser, so it is durable: it survives navigating to another page or closing the browser. The running task's progress and the list of what is queued behind it appear in the toast on any device you open the app on, and update live as tasks finish. You can cancel any queued item individually from the toast, or cancel the running task to stop it after the current comic and drop the rest.
