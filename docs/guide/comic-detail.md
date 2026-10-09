# Comic Detail Page

Every comic in the library has a detail page at `/comics/<id>/`. It is the central hub for reviewing metadata, running pipeline actions, inspecting file state, and navigating to related comics.

## Layout Overview

The page is split into three zones:

1. **Hero row**: cover image, core metadata, and variant covers
2. **Right column**: action buttons, flags, and character/team chips
3. **Tabs**: metadata comparison, credits, pipeline history, raw XML, and extended comic metadata

![Comic detail page](/comic_details.png)

---

## Hero Row

### Cover

The cover image is extracted from the CBZ file or served from the cover cache. Below it are up to three quick-access buttons:

- **Read**: opens the CBZ in the built-in reader
- **Download**: downloads the raw CBZ file
- **View on ComicVine**: direct link to ComicVine. Only shown when the comic has a ComicVine match.

Variant or alternate covers (when present) are displayed in a horizontal strip below the main cover row.

### Metadata

Next to the cover, the metadata column shows:

- **Breadcrumb**: publisher › series, linking to filtered list views
- **Title block**: series name, issue number, and full title
- **Chips**: format badge, state badge, medium badge, and any notable flags
- **Info grid**: volume, year, count (of issues in the series), and import date
- **Series completion bar**: a progress bar showing how many issues in the series are present in the library (can be disabled in Settings)
- **File info**: file path, file size, page count, and file format; a coloured status indicator shows whether the file is at its expected organized path

---

## Right Column

### Actions

The actions card contains buttons for every pipeline operation that can be run on a single comic. The button spins with a loading indicator while the task is running and shows the result inline.

| Button | What it does |
|--------|-------------|
| **Run Pipeline** | Runs the whole pipeline on this comic (accept, scrape, tag, format, deduplicate, move, write) and shows the outcome of each step in a window. CBZ files only. |
| **Edit** | Opens the full metadata edit form |
| **Scrape** | Opens the scrape modal to find and apply ComicVine metadata |
| **Tag** | Applies DataManager tagging rules to this comic |
| **Format** | Runs format detection (Main Series, TPB, One-Shot, etc.) |
| **Deduplicate** | Checks this comic for duplicates in the library. Only acts on a comic waiting in the Deduplicate stage. |
| **Move** | Organizes the file to its target folder path |
| **Write** | Writes the current metadata to `ComicInfo.xml` inside the CBZ |
| **Manage Pages** | Opens the [page manager](/guide/page-manager) for reordering, deleting or adding pages |
| **Refresh File Info** | Re-reads file size, page count, and cover hashes from disk. If any values changed the page reloads automatically. The button label reflects the hash outcome: **Up to date** (CBZ, hashes current), **No cover image** (CBZ but cover could not be read), or **No hashes (format)** (PDF, CBR, and other non-CBZ formats do not support cover hashing). |
| **Refresh Credits** | Re-fetches credits from ComicVine |
| **Search Alt Covers** | Searches ComicVine for alternate cover images |
| **Compare All Sources** | Opens a side-by-side comparison of all available scrape sources |
| **Export as JSON** | Downloads the comic's full metadata as a JSON file |
| **Delete Comic** | Permanently removes the comic from the database and deletes the file from disk |
| **Upload Cover** | Physical comics only: upload a cover image |

::: tip Re-running a step from the detail page
**Tag**, **Format**, **Move**, and **Write** here re-run that step on demand, *regardless* of the comic's current pipeline state, so you can redo any step on a single comic without sending it back through the workflow. The matching buttons in the comic list only act on comics actually waiting at that stage. Hover any button for a reminder of what it does.
:::

### Flags

The flags card shows any active quality issues detected on this comic, for example `low_page_count`, `is_pdf`, `count_mismatch`, or `corrupted_archive`. A green "clean" badge is shown when no flags are active. See [Flags](/guide/flags) for what each flag means and how it clears.

If the CBZ cannot be opened (`corrupted_archive`), a banner at the top of the page offers **Try Rezip**. It recovers the pages that can still be read, and converts a RAR or 7-Zip archive that was named `.cbz` into a real CBZ.

### Characters & Teams

When the comic has character or team data, a card shows three sections:

- **Main Character**: the primary character or team designated by the DataManager tagging rules. Clicking the chip searches `/comics/?char_q=<name>&char_main_only=1`, returning only comics where this character is the main focus.
- **Characters**: all characters listed in the `characters` field. Each chip links to `/comics/?char_q=<name>&char_main_only=0`, which matches any comic where the name appears in any character, team, or main character field.
- **Teams**: same as Characters but drawn from the `teams` field, with the same link behaviour.

---

## Tabs

### Metadata Comparison

Compares the values currently stored in the database against what is written inside the `ComicInfo.xml` in the CBZ file. Fields that differ are highlighted. This tab is the default when a digital comic has a readable CBZ.

### Credits

A formatted view of all credit fields: writer, penciller, inker, colorist, letterer, cover artist, and editor.

### Pipeline History

A log of every pipeline action that has been run on this comic, loaded from the audit log. Shows the action, timestamp, and any field changes made. Loaded lazily on first click.

### Comic Metadata

Extended metadata fields that are not shown in the main hero area: genre, tags, locations, characters, teams, series group, scan information, notes, summary, and any custom values stored in the `custom_values` JSON field.

### Raw XML

The raw `ComicInfo.xml` text currently written inside the CBZ file, shown as-is. Useful for debugging what is actually on disk versus what the database holds.
