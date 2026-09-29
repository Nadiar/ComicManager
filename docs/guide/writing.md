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

Running **Write All** in the dashboard starts a task that handles the XML insertion in the background.

- **Non-Destructive Writing**: ComicManager adds or updates the `ComicInfo.xml` file inside your CBZ/CBR without modifying your story pages.
- **Required Field Validation**: ComicManager enforces data integrity before writing. It will block a write and log an error if essential fields are missing. Required fields are `series`, `publisher`, and `number` (unless the format is a numberless type like TPB, Omnibus, Graphic Novel, Hard Cover, or Absolute Edition). I.N.D.U.C.K.S. story-only comics are exempt from the `number` and `publisher` requirements since those fields are legitimately absent for standalone stories.
- **Error Logging**: Any failure during the write process (corrupted file, failed validation) is safely logged to the **Audit Log** as a `write_error`.
- **Progress Tracking**: Real-time progress bars and toast notifications keep you informed about the status of your batch writing.

---

## In-Place Writing and Performance

When ComicManager writes `ComicInfo.xml`, it patches **only** the metadata entry inside the archive. Your page images are never read, decompressed, or recompressed. This is why writing metadata into a multi-gigabyte omnibus takes a fraction of a second instead of several minutes, and it is what makes **Write All** and **Write Stale** practical across tens of thousands of files.

How the write is applied depends on the filesystem your library lives on. ComicManager detects this automatically and there is nothing to configure.

### On copy-on-write filesystems (btrfs, XFS)

On a copy-on-write filesystem, ComicManager makes an instant, space-free clone of the archive, patches the clone, and then atomically swaps it into place. The clone shares the original's data blocks, so even a 2 GB file is cloned with no real copying.

This path is **crash-safe**: the patched clone is flushed to disk before the swap, so if the machine loses power or the process is killed at any point during the write, you are always left with either the complete old file or the complete new file. The original is never in a half-written state.

### On other filesystems (ext4 and similar)

On filesystems without copy-on-write support, a cheap clone is not available, so ComicManager patches the archive in place. This is still fast, because it only rewrites the small `ComicInfo.xml` entry and the archive's index, not the page images. ComicManager deliberately avoids copying the whole file, which on a large archive would mean gigabytes of needless disk I/O on every write.

An in-place write is **not atomic**: the new metadata entry is written over the old archive index, and the new index is only written at the end. If the machine loses power, the disk fills up, or the process is hard-killed in between, the archive cannot be opened.

To make that recoverable, ComicManager first saves the archive's index to a small hidden file next to the comic (named `.<file name>.cm-index`) and flushes it to disk. Once the write has finished and is flushed, the backup is deleted. If a write is interrupted, the backup stays, and the original archive is restored exactly:

- automatically, the next time that comic is written, or
- when you click **Rezip** on a comic flagged as a corrupted archive.

The backup holds only the index, usually a few kilobytes. Measured on a 2 GB omnibus on an SSD, the backup added about 6 ms to a write, while copying the whole file took over 4 seconds (longer on a hard disk).

---

## Stale Metadata and Maintenance

After a comic has been written, you might continue to edit its metadata in ComicManager (e.g. correcting a typo, changing a genre tag).

ComicManager tracks exactly when `ComicInfo.xml` was last written using a `last_written` timestamp. If you make a metadata edit, the database is updated immediately, but the file is not.
- **Stale Metadata Widget**: Comics whose database `updated_at` time is newer than their `last_written` time are automatically surfaced in the Maintenance tab of your dashboard.
- **Missing ComicInfo.xml Widget**: Surface comics that are in the Written state but somehow lost their internal XML (or had it manually removed).

This lets you comfortably edit data knowing that you can just click **Write Stale** later to sync all changes back into the physical files at once.

### Write Count-Updated

When a new scrape brings back a different issue count for a volume, already-written comics in that volume are flagged `count_updated`. The **Write Count-Updated** action (`/comics/rewrite-updated/`) rewrites only the issue count field in their `ComicInfo.xml` without touching anything else. This is faster and safer than a full re-write. The flag clears as soon as the write succeeds. The action is available from the Maintenance section of the dashboard.

### Write Missing ComicInfo

Comics in the Written state that have somehow lost their `ComicInfo.xml` (for example, if the file was replaced externally) are surfaced by the **Missing ComicInfo** widget in the Maintenance tab. Click **Write Missing** to trigger `/comics/write-missing/`, which writes `ComicInfo.xml` into every comic in this state that is missing it. No metadata changes are made; only the XML file is (re)created.

## ComicInfo.xml Advanced Features

- **Summary Formatting**: ComicManager preserves paragraph breaks and removes messy HTML tags from your summaries, ensuring they are readable in any comic reader.
- **Custom Values**: Any metadata not covered by standard `ComicInfo.xml` fields (story arcs, scrape source, ComicVine IDs, DataManager flags) is stored in a `<CustomValues>` block inside the XML.
- **ComicVine reference**: If the Notes field is empty, ComicManager writes a short reference like `Scraped metadata from ComicVine [CVDB12345].` so the source match is traceable from any reader. This mirrors the convention ComicRack's ComicVine scraper uses to record the same match, so the reference works in either application.
