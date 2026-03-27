# Physical Comics

ComicManager is designed to handle both digital and physical comic book collections, allowing you to manage your entire library in one place.

## Managing Physical Records

While digital comics are imported automatically from the filesystem, physical comics are added to the system manually (or via bulk import).
- **No File Path**: Physical comics do not have a corresponding file on disk.
- **Medium Badge**: Clearly identified in the UI with a "Physical" badge.
- **Shared Metadata**: Physical comics share the same metadata fields as digital ones (Series, Number, Volume, Publisher, etc.).
- **Storage Location**: You can specify exactly where your physical comic is kept (e.g. "Longbox 12", "Display Shelf", "Graded Case A") using the dedicated `storage_location` text field.

## Workflow for Physical Comics

Physical comics follow a slightly different path through the pipeline:
1. **Manual Entry**: Create a new record with `medium=physical`.
2. **Scraping**: Match with ComicVine metadata using the same search tools as digital comics.
3. **Variant Covers & Caching**: When matched, ComicManager automatically downloads the main cover and any variant covers from ComicVine and stores them in your local cover cache. You can use the **Variant Gallery** on the detail page to select which cover you actually own.
4. **Tagging**: Apply DataManager rules to categorize and group series.
5. **No Organizing/Writing**: Since there are no files, physical comics skip the file movement and XML writing stages.

## Benefits of Tracking Physical Comics

- **Unified Collection**: Search across your entire library (digital + physical) from one dashboard.
- **Missing Issues**: Track series completion even if you own some issues physically and others digitally.

---

## Bulk CSV Import

For large physical collections, you can import many comics at once via a CSV file from the **Physical Comics** page.

### CSV Format

The file must be UTF-8 encoded, standard comma-separated values.

| Column | Required | Description |
|--------|----------|-------------|
| `series` | Yes | Series name. Rows without this are skipped. |
| `number` | No | Issue number |
| `volume` | No | Volume number (integer) |
| `year` | No | Publication year (integer) |
| `publisher` | No | Publisher name |
| `format` | No | Format type (e.g. `Main Series`, `TPB`, `One-Shot`) |
| `title` | No | Issue title |
| `notes` | No | Notes |
| `storage_location` | No | Where the physical issue is stored (e.g. `Longbox 12`, `Display Shelf`) |

Column headers are case-insensitive. `Storage Location` (with a space) also works for `storage_location`.

### Example CSV

```csv
series,number,year,publisher,storage_location
Batman,1,2011,DC Comics,Longbox 1
Batman,2,2011,DC Comics,Longbox 1
Amazing Spider-Man,700,2013,Marvel,Longbox 2
Saga,1,2012,Image Comics,Longbox 3
The Sandman,,1989,DC Comics/Vertigo,Display Shelf
```