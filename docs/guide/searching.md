# Searching, Filtering, and Sorting

The `/comics` list supports powerful search, filter, sort, and view controls. All controls persist in the URL so you can bookmark or share any view.

## View Modes

The toolbar shows four view mode buttons. Click any to switch; the page reloads via HTMX without a full page refresh.

| Mode | Description |
|------|-------------|
| **Table** | A dense, scrollable table with all configured columns visible. Best for bulk review and sorting. |
| **Hybrid** | One cover thumbnail per row on the left, metadata columns to the right. Balances density and visual recognition. |
| **Grid** | Large cover tiles arranged in a grid. Good for visual browsing. Supports bulk selection. |
| **Compact** | A condensed single-line table with fewer columns. Useful on smaller screens or when you want maximum rows per page. |

![Table view](/comic_overview.png)

![Hybrid view](/comics_overview_hybrid.png)

![Grid view](/comics_overview_grid.png)

![Compact view](/comics_overview_compact.png)

The column set shown in Table, Hybrid, and Compact modes is customizable via the **Columns** dropdown in the toolbar. Drag column headers to reorder them; the order is preserved in the URL.

The dropdown has three save actions at the bottom:

| Button | What it does |
|--------|-------------|
| **Save temp** | Applies the current selection to the URL without persisting it. The column set reverts to the saved default next time you open the view fresh. |
| **Save for current view** | Persists the column set for this specific view (pipeline state, flag, or smart list) so it is restored on future visits. |
| **Reset to default** | Removes any saved or temporary column customization and restores the system default column set. |

## Search

The search box queries across all meaningful text fields simultaneously:

- Series, title, publisher, issue number
- Writer, penciller, inker, colorist, letterer, cover artist, editor
- Characters, teams, genre, notes

### Smart Search Tokens

You can narrow results further by embedding structured tokens anywhere in the search query. Tokens are extracted and applied as AND filters on top of the text search.

| Token | Filters on | Example |
|-------|-----------|---------|
| `#N` | Issue number (exact) | `#10`, `#10.1` |
| `(YYYY)` | Publication year | `(2011)`, `(1940)` |
| `VYYY` | Volume number | `V2022`, `V2012` |

Tokens can be combined freely with each other and with regular text:

```
Batgirl #10
```
Returns all Batgirl comics with issue number 10.

```
Batman (1940)
```
Returns Batman comics from the 1940 volume year.

```
Batman V2017 #15 (2016)
```
Returns Batman Volume 2017, issue 15, year 2016.

```
#10
```
Returns every comic with issue number 10 (no text filter applied).

```
Grant Morrison V2000
```
Returns comics with "Grant Morrison" in any credit field, filtered to volume 2000.

::: tip
Tokens are case-insensitive. `v2`, `V2`, and `V2` all work the same way.
:::

## Character Search

The `char_q` filter narrows comics by character or team name. You can reach it directly via URL:

| URL | What it returns |
|-----|----------------|
| `/comics/?char_q=Batman&char_main_only=1` | Comics where Batman is the designated main character or team (solo books, not crossovers) |
| `/comics/?char_q=Batman&char_main_only=0` | All comics where Batman appears in any character, team, or main character field |

On the comic detail page, every chip in the **Characters & Teams** card is a link that runs the appropriate query automatically — clicking a main character chip uses `char_main_only=1`, clicking a character or team chip uses `char_main_only=0`.

---

## Column Filter Row

Click the **funnel icon** button in the toolbar to reveal a filter input directly beneath each column header. Each input narrows the list to rows that contain your text in that column, and multiple column filters stack as AND conditions.

- Filters apply live with a 300 ms debounce — no need to press Enter.
- All active filters are included in the URL, so filtered views are bookmarkable and shareable.
- Clicking the funnel button again hides the row; the filters remain active in the URL until you clear the inputs or navigate away.
- The filter row appears in **Table** and **Compact** view modes only. Hybrid and Grid views have no column headers.

Columns that store computed or timestamp values (Imported, Updated, Last Written, ComicVine IDs) do not show a filter input.

---

## Filter Rail

Filters are grouped in a collapsible **filter rail** on the left side of the comic list. Click the **Filter** button in the toolbar to show or hide it. You can make the rail open by default via the `filter_rail_default` setting (see [Settings Reference](/reference/settings)).

Available filters:

- **Publisher**
- **State**
- **Format**
- **Flags**

Active filters are shown as badges below the filter bar. Click the **Reset** button to remove all filters and return to the unfiltered list.

## Sorting

### Sort dropdown

The sort dropdown provides quick access to the most common sort fields. Use the **Order** dropdown (A->Z / Z->A) to toggle direction.

### Column header clicks

Click any column header to sort by that column. Clicking the same header again reverses the direction. An arrow indicator (↑ / ↓) shows the active sort column and direction.

All columns in the table are sortable, including credits and custom metadata columns. Columns with nullable numeric values (e.g. Pages, Year) always sort `NULL` values to the bottom in both directions.

### Sort behaviour for Pages

Comics with no page count recorded are always placed at the end of the results, regardless of sort direction. This avoids unscraped or physical comics flooding the top of a descending sort.

---

## Right-Click Context Menu

Right-clicking any comic row or grid tile opens a context menu with quick actions for that comic. The available actions mirror the inline row buttons (open detail, scrape, tag, format, organize, write, delete) so you can act on a comic without leaving your scroll position.

The context menu is available in all four view modes.

---

## Inline Editing (New State)

On the `/comics/?state=new` list, several fields are editable directly in the table without navigating to the detail page. Click any cell in these columns to edit it in place:

- Proposed Series
- Proposed Number
- Proposed Volume
- Publisher
- Format

Press **Enter** or click away to save. This is the fastest way to fix bad filename parses before scraping.
