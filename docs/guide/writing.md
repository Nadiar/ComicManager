# Writing Files: Metadata Portability

The **Writing** stage saves the final, metadata-enriched, standardized `ComicInfo.xml` inside your comic files. This is the final "Seal of Approval" for your collection.

## Why Write?

Why bother writing metadata *inside* your files? Why not just keep it in your database?

The answer is **Portability**. Your comic collection is a digital library that you might want to:
- Use in other comic readers (like ComicRack, Panels, or Chunky).
- Re-import into a new instance of ComicManager or another application.

By embedding a standardized **`ComicInfo.xml`** file inside your digital comic files, you ensure that your metadata (series names, issue numbers, creators, and summaries) is portable and permanent.

---

## Batch Writing with Confidence

Running **Write All** in the dashboard starts a Celery task that handles the XML insertion in the background.

- **Non-Destructive Writing**: ComicManager adds or updates the `ComicInfo.xml` file inside your CBZ/CBR without modifying your story pages.
- **Required Field Validation**: ComicManager enforces data integrity before writing. It will block a write and log an error if essential fields are missing. Required fields are `series`, `publisher`, and `number` (unless the format is a numberless type like TPB, Omnibus, or Graphic Novel). I.N.D.U.C.K.S. story-only comics are exempt from the `number` and `publisher` requirements since those fields are legitimately absent for standalone stories.
- **Error Logging**: Any failure during the write process (corrupted file, failed validation) is safely logged to the **Batch Audit Log** as a `write_error`.
- **Progress Tracking**: Real-time progress bars and toast notifications keep you informed about the status of your batch writing.

---

## Stale Metadata and Maintenance

After a comic has been written, you might continue to edit its metadata in ComicManager (e.g. correcting a typo, changing a genre tag).

ComicManager tracks exactly when `ComicInfo.xml` was last written using a `last_written` timestamp. If you make a metadata edit, the database is updated immediately, but the file is not.
- **Stale Metadata Widget**: Comics whose database `updated_at` time is newer than their `last_written` time are automatically surfaced in the Maintenance tab of your dashboard.
- **Missing ComicInfo.xml Widget**: Surface comics that are in the Written state but somehow lost their internal XML (or had it manually removed).

This lets you comfortably edit data knowing that you can just click **Write Stale** later to sync all changes back into the physical files at once.

## ComicInfo.xml Advanced Features

- **Summary Formatting**: ComicManager preserves paragraph breaks and removes messy HTML tags from your summaries, ensuring they are readable in any comic reader.
- **Custom Values**: Any metadata not covered by standard `ComicInfo.xml` fields (story arcs, scrape source, ComicVine IDs, DataManager flags) is stored in a `<CustomValues>` block inside the XML.
- **ComicVine reference**: If the Notes field is empty, ComicManager writes a short reference like `Scraped metadata from ComicVine [CVDB12345].` so the source match is traceable from any reader.
