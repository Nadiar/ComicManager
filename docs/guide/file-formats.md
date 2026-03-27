# File Format Handling

ComicManager supports several comic archive formats. Some formats require conversion before the pipeline can process them.

---

## Supported Formats

| Extension | Handling |
|-----------|----------|
| `.cbz` | Native format. No conversion needed |
| `.cbr` | Flagged for conversion on import. Convert via the Review Queue or dashboard |
| `.cb7` | Flagged for conversion on import. Convert via the Review Queue or dashboard |
| `.zip` | Flagged for manual one-click conversion (see below) |
| `.pdf` | Flagged for review. PDFs cannot be processed through the standard pipeline |

---

## ZIP to CBZ Conversion

ZIP and CBZ are identical archive formats. A `.zip` file is a valid comic archive that just needs to be renamed.

### How it works

When a `.zip` file is scanned into the library, ComicManager:

1. Imports it normally (page count measured, filename parsed).
2. Sets the `is_zip` flag.
3. Adds it to the **Review & Maintenance Queue** under the **Active Review** tab.

The `is_zip` flag does not block the comic from progressing through the pipeline on its own, but the file must be renamed to `.cbz` before it reaches the Write phase, since `.zip` is not a standard comic container.

### Converting a single ZIP file

On the comic's detail page (or in the Review Queue row), click **Convert to CBZ**. The file is renamed in place. No extraction or repacking happens. ComicManager updates the `file_path`, `file_format`, and clears the `is_zip` flag automatically.

The conversion is logged to the Batch Audit Log with action type `convert_zip`, including the old and new file paths.

### Bulk conversion

To convert all flagged ZIP files at once, go to the **Review Queue** and use the **Convert All ZIPs** bulk action. A background Celery task processes each file in sequence.

If a conversion fails (e.g. the target `.cbz` path already exists, or a permission error), that file is skipped and an error is recorded in the task result. Other files in the batch continue processing.

::: tip
If the bulk task is interrupted, you can safely re-run it. Already-converted files are no longer flagged with `is_zip` and will be skipped.
:::

---

## CBR / CB7 Automatic Conversion

CBR (RAR archive) and CB7 (7-Zip archive) files are not automatically converted. When scanned, they are flagged with `needs_conversion` and placed in the **Review Queue**.

From there you can convert them individually via the **Convert to CBZ** button on the comic detail page, or convert all flagged files at once using **Convert All CBR/CB7** from the dashboard.

---

## PDF Files

PDF files are not supported by the standard pipeline. When a `.pdf` file is scanned, the `is_pdf` flag is set and the comic appears in the Review Queue. These files must be deleted or converted externally before ComicManager can process them.
