# Searching, Filtering, and Sorting

The `/comics` table supports powerful search, filter, and sort controls. All controls persist in the URL so you can bookmark or share any view.

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

The **Character** search field lets you filter comics by character or team appearances.

By default it searches both the `characters` field and the `teams` field simultaneously. Enable the **Main Only** toggle to restrict the search to `main_character_or_team`, which is the field set by DataManager rules to identify the primary focus of a series. This is useful for filtering a character's solo books without including every crossover appearance.

```
Batman [Main Only: on]
```
Returns only comics where Batman is the designated main character or team, not every comic where he appears.

---

## Filters

Use the filter dropdowns to narrow results by:

- **Publisher**: exact match against the publisher field
- **Format**: Main Series, TPB, One-Shot, Limited Series, etc.
- **Medium**: Digital or Physical

Active filters are shown as badges below the filter bar. Click the "Clear" link to remove all filters and return to the unfiltered list.

## Sorting

### Sort dropdown

The sort dropdown provides quick access to the most common sort fields. Use the **Order** dropdown (A->Z / Z->A) to toggle direction.

### Column header clicks

Click any column header to sort by that column. Clicking the same header again reverses the direction. An arrow indicator (↑ / ↓) shows the active sort column and direction.

All columns in the table are sortable, including credits and custom metadata columns. Columns with nullable numeric values (e.g. Pages, Year) always sort `NULL` values to the bottom in both directions.

### Sort behaviour for Pages

Comics with no page count recorded are always placed at the end of the results, regardless of sort direction. This avoids unscraped or physical comics flooding the top of a descending sort.
