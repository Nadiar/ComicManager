# Smart Lists

Smart Lists are saved, named queries that allow you to filter your collection based on any criteria.

## Dynamic Filtering

Create Smart Lists to keep track of specific parts of your collection:
- **By Publisher**: "All DC Comics", "Marvel Ongoing".
- **By Format**: "One-Shots", "TPBs".
- **By State**: "Comics with Scrape Errors", "Unorganized Comics".
- **Custom Filters**: Build complex queries with multiple criteria (e.g., "Batman Series with > 100 issues").

## Creating a Smart List

1. Go to the **Smart List Index** and click **New Smart List**.
2. Add filter criteria (field, lookup, and value). You can filter on almost any field, including custom values and dates.
3. Use **Add OR Group** to create a sub-group where any condition can match (e.g. format is One-Shot OR TPB). Top-level filters are always combined with AND.
4. Choose sorting options (ascending/descending).
5. Select which columns to display in the list view.
6. Enable **Show on Dashboard** to track progress at a glance.

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