# Smart Lists

Smart Lists are saved, named queries that allow you to filter your collection based on any criteria.

## Dynamic Filtering

Create Smart Lists to keep track of specific parts of your collection:
- **By Publisher**: "All DC Comics", "Marvel Ongoing".
- **By Format**: "One-Shots", "TPBs".
- **By State**: "Comics with Scrape Errors", "Unorganized Comics".
- **Custom Filters**: Build complex queries with multiple criteria (e.g., "Batman Series with > 100 issues").

## Creating a Smart List

1. Go to `/smartlists/` and click **New Smart List**.
2. Add filter criteria (field, lookup, and value). You can filter on almost any field, including custom values and dates.
3. Use **Add OR Group** to create a sub-group where any condition can match (e.g. format is One-Shot OR TPB). Top-level filters are always combined with AND.
4. Choose sorting options (ascending/descending).
5. Select which columns to display in the list view.
6. Optionally set an **Icon** to visually distinguish the list in the sidebar and index page.
7. Optionally link a **ComicVine Volume** to enable the Missing Issues comparison for this list (see below).

## Filter Fields

You can filter on any of the following fields:

### Core Metadata

| Field | Description |
|-------|-------------|
| `Series` | Series name |
| `Title` | Issue title |
| `Number` | Issue number |
| `Volume` | Volume number |
| `Publisher` | Publisher name |
| `Year` | Publication year |
| `Month` | Publication month |
| `Day` | Publication day |
| `Count` | Total issue count |
| `Pages` | Page count |
| `Format` | Format type (Main Series, TPB, One-Shot, etc.) |
| `State` | Current pipeline state |
| `Medium` | Digital or Physical |
| `File Format` | File extension (cbz, cbr, pdf, etc.) |
| `Writer` | Writer credits |
| `Penciller` | Penciller credits |
| `Characters` | Character appearances |
| `Genre` | Genre |
| `Series Group` | Series group set by tagging rules |
| `Main Character / Team` | Primary character or team |
| `File Path` | Full file path |

### Proposed Values (New State)

These fields hold the filename-parsed values before scraping:

| Field | Description |
|-------|-------------|
| `Proposed Series` | Series parsed from filename |
| `Proposed Number` | Issue number parsed from filename |
| `Proposed Volume` | Volume parsed from filename |
| `Proposed Year` | Year parsed from filename |

### Workflow Tracking

| Field | Description |
|-------|-------------|
| `Needs Reorganize` | Whether the comic's path needs updating |
| `Needs Reformat` | Whether the format needs recalculating |
| `Last Written` | When ComicInfo.xml was last written to disk |
| `Import Date` | When the comic was first imported |

### Flags

Filter by any pipeline flag. Use the exact flag key shown:

| Field | Description |
|-------|-------------|
| `Flag: Corrupted Archive` | CBZ file cannot be read |
| `Flag: Low Page Count` | Fewer pages than the threshold |
| `Flag: PDF` | PDF file (not processable) |
| `Flag: No Series` | Series could not be parsed from filename |
| `Flag: Cover Only` | Standalone cover file |
| `Flag: Needs Conversion` | CBR or CB7 file requiring conversion |
| `Flag: ZIP File` | `.zip` file needing a rename to `.cbz` |
| `Flag: Missing Count` | Issue count could not be found |
| `Flag: Count Mismatch` | Comics in the same volume disagree on count |
| `Flag: No Scrape Match` | Scraper found no viable match |
| `Flag: Scrape Error` | Technical scrape error occurred |
| `Flag: Scrape Skipped` | Comic intentionally excluded from batch scraping |
| `Flag: Unknown Publisher` | Publisher not covered by any enabled ruleset |

Flag fields use the "equals" lookup. Set value to `true` to match flagged comics and `false` to match unflagged ones. Or use "is not empty" (no value needed) to match any comic that has the flag set.

### ComicVine Custom Values

| Field | Description |
|-------|-------------|
| `CV Volume ID` | ComicVine volume ID |
| `CV Issue ID` | ComicVine issue ID |
| `CV Issue Count` | Total issue count from ComicVine |
| `Scrape Source` | Match type used (phash, metadata, api, inducks, etc.) |
| `Scrape Score` | Match quality score |

### DataManager Custom Values

| Field | Description |
|-------|-------------|
| `DataManager Processed` | Whether DataManager rules have been applied |
| `Original Format` | Original format from source data |
| `Leading Numbers` | DataManager custom field |
| `First Series` | First series in a multi-series story |
| `Second Series` | Second series reference |
| `IsStarWars` | Star Wars classification marker |
| `Has Alt Covers` | Whether variant covers have been fetched |

---

## Filter Lookups

| Lookup | Meaning | Needs a value? |
|--------|---------|----------------|
| `equals` | Exact match (case-insensitive) | Yes |
| `not equals` | Does not exactly match | Yes |
| `contains` | Field contains this substring | Yes |
| `not contains` | Field does not contain this substring | Yes |
| `starts with` | Field starts with this string | Yes |
| `not starts with` | Field does not start with this string | Yes |
| `ends with` | Field ends with this string | Yes |
| `not ends with` | Field does not end with this string | Yes |
| `greater than` | Numeric: strictly greater than | Yes |
| `less than` | Numeric: strictly less than | Yes |
| `at least` | Numeric: greater than or equal | Yes |
| `at most` | Numeric: less than or equal | Yes |
| `is empty` | Field is null or unset | **No** |
| `is not empty` | Field has any value | **No** |

::: tip is empty / is not empty
These two lookups do not need a value. The value input hides automatically when you select them. If you choose a lookup that needs a value but leave the value blank, a warning appears on the filter row and that filter will be dropped when you save.
:::

---

## AND vs OR Logic

Top-level filter rows are always combined with **AND** (every condition must match).

Use **Add OR Group** to create a sub-block where **any** condition in the group can match. For example:

- Format is One-Shot **OR** Format is TPB (a group with two rows)

This group itself becomes one item in the top-level AND chain.

---

## Columns

Each Smart List can have a custom set of columns shown in its detail table. Choose columns when creating or editing the list. If no columns are selected, the default column set is used.

Available columns include all core metadata fields, flag columns, and custom value columns. The column set is also overridable at runtime using the **Columns** dropdown on the list detail page without saving to the Smart List.

---

## Sort Options

Smart Lists support sorting by:

- Series, Number, Publisher, Year, State, Format, Pages, Issue Count, Updated, Import Date, Last Written

Choose ascending or descending. The sort direction can also be overridden at runtime on the list detail page.

---

## Running Actions from a Smart List

The Smart List detail page has a **Run Action** dropdown that applies a pipeline action to comics in the list:

| Action | Effect |
|--------|--------|
| Scrape | Runs CV/INDUCKS scrape on each comic |
| Tag | Applies your DataManager rulesets |
| Format | Re-runs format detection |
| Organize | Moves each comic to its library path |
| Force Write | Embeds ComicInfo.xml, bypassing validation |

### Running on a subset

Each row in the Smart List has a checkbox on the left. Check one or more rows and then trigger **Run Action** to apply the action only to the selected comics. If no rows are checked, the action runs on every comic in the list's current result set.

A **Select all** checkbox in the header selects all visible rows at once.

Actions run as background Celery tasks with the same progress toast and cancellation support as all other batch operations.

---

## Linked ComicVine Volume: Missing Issues

A Smart List can be linked to a ComicVine volume by searching for and selecting a volume in the **ComicVine Volume** field on the create/edit form. Once linked:

- A **Missing Issues** button appears on the Smart List index and detail pages.
- Clicking it opens `/smartlists/<pk>/missing/`, which shows every issue in the linked CV volume alongside your ownership status for each one.
- Issues present in your library are shown with a link to the comic detail page. Issues you do not own are shown with the CV cover and a link to the ComicVine page.

This is distinct from the per-comic **Series Audit** (which is anchored to a single comic's volume). The Smart List missing issues view is anchored to the list itself, making it useful for tracking a reading challenge, a specific run, or a pull list.

## Importing from ComicRack (CBL)

ComicRack smart lists exported as `.cbl` files can be imported directly. Click **Import CBL** on the Smart List Index page and upload the file.

Supported matchers: Publisher, Series, Title, Number, Volume, Year, Full Path, File Name, Format, Main Character/Team, Tags (mapped to Genre), Summary, and Custom Values. OR/AND groups are preserved. Unsupported matcher types are skipped with a warning shown on the edit page.

If the CBL contains filter fields that are not recognised by ComicManager (for example, custom values not in the standard list), a mapping step is shown before the Smart List is created. For each unknown field you can either choose the correct internal field from a dropdown or skip all filters that use it.

## Exporting to CBL

Any Smart List can be exported as a `.cbl` file for backup or re-import. Click **Download CBL** on the Smart List detail page.

If all filters have ComicRack-compatible equivalents, the file downloads immediately.

If any filters use fields or operators that have no CBL equivalent (such as flag filters or numeric comparisons), you are shown two download options:

- **ComicRack-safe**: standard CBL format with unsupported filters skipped. Works in ComicRack and ComicManager.
- **Complete**: all filters are preserved by embedding the full filter data in the file. Can be re-imported into ComicManager without any data loss. Not compatible with ComicRack.
