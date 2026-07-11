# Physical Comics

ComicManager is designed to handle both digital and physical comic book collections, allowing you to manage your entire library in one place.

## Managing Physical Records

While digital comics are imported automatically from the filesystem, physical comics are added to the system manually (or via bulk import).
- **No File Path**: Physical comics do not have a corresponding file on disk.
- **Medium Badge**: Clearly identified in the UI with a "Physical" badge.
- **Shared Metadata**: Physical comics share the same metadata fields as digital ones (Series, Number, Volume, Publisher, etc.).
- **Storage Location**: You can specify exactly where your physical comic is kept (e.g. "Longbox 12", "Display Shelf", "Graded Case A") using the dedicated `storage_location` text field.

## Workflow for Physical Comics

Physical comics skip the file-handling stages since there is no file to move or write.

| Pipeline stage | Digital | Physical |
|----------------|:-------:|:--------:|
| New (filename parse) | Yes | No. Entry created manually |
| Scrape (ComicVine match) | Yes | Yes |
| Cover caching | In CBZ | Downloaded to cover cache |
| Variant Gallery | Yes | Yes. Select the cover you own |
| Tagging | Yes | Yes |
| Add Formats | Yes | Yes |
| Deduplicate | Yes | Yes (digital+physical pair is never a duplicate) |
| Move Files (Organize) | Yes | **Skipped** |
| Write ComicInfo.xml | Yes | **Skipped** |
| Done | Yes | Yes |

## Benefits of Tracking Physical Comics

- **Unified Collection**: Search across your entire library (digital + physical) from one dashboard.
- **Missing Issues**: Track series completion even if you own some issues physically and others digitally.

---

## Adding a Single Physical Comic

Go to **Physical Comics** and click **Add Physical Comic** (or navigate to `/physical/add/`). Fill in the series, number, year, publisher, format, and storage location fields and click **Save**. The record is created immediately with `medium = physical` and `state = scrape`, ready for ComicVine matching.

Use the manual form for one-off additions. For large collections use the bulk CSV import below.

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
