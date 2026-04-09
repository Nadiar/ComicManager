# Audit Log & Rollback

ComicManager keeps a detailed log of all batch actions to help you track changes and undo mistakes.

## Audit Log Features

All pipeline actions are recorded in the **Batch Audit Log**. This includes both batch operations (Scrape All, Tag All, etc.) and single-comic scrapes triggered from the comic list or detail page:
- **Action Type**: See which batch operation was performed (e.g. `scrape_all`, `organize_all`, `audit_metadata`).
- **Comic Info**: Identify each comic by name and UUID. You can click the Info button to open the comic detail page directly.
- **State Transition**: Track changes from one workflow state to another.
- **Diff Changes**: See exactly which metadata fields were modified (e.g. proposed values vs finalized values, old path vs new path).
- **Error Tracking**: Organize failures (e.g., file could not be moved) and Write failures (e.g., XML could not be saved or validation failed) are logged here as `organize_error` and `write_error` with a red badge, allowing you to quickly spot pipeline failures.

## Rollback Actions

If a batch action fails or produces unwanted results, use the **Rollback** feature:
- **Send Back**: Reset a comic to its previous state.
- **To Scrape**: Specifically resets a comic back to the "Imported" state and clears all applied ComicVine metadata, allowing you to run a fresh scrape on a mistaken match.
- **Clear Metadata**: Automatically clear scraped data or assigned tags upon rollback.
- **Undo State**: Revert state transitions for any single comic.

## Accessing the Log

- Find the **Batch Audit Log** in the **Settings** menu (`/settings/log/`).
- Filter by action type (e.g., Scrape, Tag, Format, Errors).
- The log is stored physically in `data/logs/batch_actions.jsonl`, keeping it completely independent of your primary PostgreSQL database, ensuring that heavy batch activity doesn't bloat your database.

## Understanding the Diff

Each log entry shows a **before/after diff** of the fields that changed. For example:

- A scrape entry shows the fields that changed: `series`, `publisher`, `cv_issue`, and `cv_volume` when values differed before and after the match. If the scrape failed, the entry shows `result: null -> no_match`. When the failure was caused by a Layer 3 cover hash rejection, a `reason` field is also included (e.g. `reason: null -> cover hash mismatch (phash dist 42, ahash dist 38)`).
- An organize entry shows `file: ["/comics/untagged/Batman #1.cbz", "/comics/library/DC Comics/Batman (2011)/Batman #001.cbz"]` — the old path and the new path as a two-element array.
- A write entry shows which ComicInfo.xml fields were embedded.
- A `convert_zip` entry shows the old `.zip` path and the new `.cbz` path.

For `organize_error` and `write_error` entries (shown with a red badge), the diff contains the error message returned by the file system or XML writer. Use this to diagnose why a file could not be moved or written — common causes include permission errors, disk-full conditions, or path length limits on the host filesystem.