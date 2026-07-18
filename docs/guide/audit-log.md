# Audit Log & Rollback

ComicManager keeps a detailed log of all actions to help you track changes and review mistakes.

## Audit Log Features

All actions are recorded in the **Audit Log**. This includes both batch operations (Scrape All, Tag All, etc.) and single-comic scrapes triggered from the comic list or detail page:
- **Action Type**: See which batch operation was performed (e.g. `scrape_all`, `organize_all`, `audit_metadata`).
- **Comic Info**: Identify each comic by name and UUID. You can click the Info button to open the comic detail page directly.
- **State Transition**: Track changes from one workflow state to another.
- **Diff Changes**: See exactly which metadata fields were modified (e.g. proposed values vs finalized values, old path vs new path).
- **Error Tracking**: Organize failures (e.g., file could not be moved) and Write failures (e.g., XML could not be saved or validation failed) are logged here as `organize_error` and `write_error` with a red badge, allowing you to quickly spot pipeline failures.

## Rollback Actions

If a batch action fails or produces unwanted results, use the **Rollback** feature. Each log entry shows context-appropriate rollback buttons:

| Button | Resets to state | What it clears |
|--------|----------------|----------------|
| **To New** | New (phase 1) | ComicVine IDs, scrape score, scrape source, scrape flags (`scrape_no_match`, `scrape_error`, `scrape_error_detail`, `metadata_mismatch`) |
| **To Scrape** | Scrape (phase 2) | Same as To New. Use this when you want to re-scrape without losing the accepted proposed values |
| **To Tagging** | Tagging (phase 4) | Format only. ComicVine metadata is preserved; use this to re-run tagging rules after editing a ruleset |

## Accessing the Log

The Audit Log is available from three places:

- **Sidebar and top navigation**: Click **Audit Log** in the left sidebar or the top nav bar.
- **Settings menu**: Navigate directly to `/settings/log/`.
- **Comic detail page**: Open any comic and click the **Pipeline history** tab to see only the audit entries for that specific comic.

Filter by action type (e.g., Scrape, Tag, Format, Errors).

The log is stored physically in `data/logs/batch_actions.jsonl`, keeping it completely independent of your primary PostgreSQL database, ensuring that heavy batch activity doesn't bloat your database.

## Per-Comic Pipeline History

The **Pipeline history** tab on any comic detail page shows a chronological log of every action that has been run on that comic: scrapes, tag passes, state transitions, organize moves, and write operations. Each entry shows the action type, timestamp, and a diff of what changed.

The same rollback buttons available in the global log (**To New**, **To Scrape**, **To Tagging**) also appear on each entry here. This lets you roll back a specific action directly from the comic detail page without navigating to the global log.

This is the fastest way to answer "what happened to this comic?" without filtering the global log.

## Import Errors Log

Errors that occur during the CLI import command (`import_library`, `scan_untagged`) are written to a separate persistent log file at `data/logs/import_errors.log` on the host. This includes messages like "Invalid or corrupted CBZ file" or "No ComicInfo.xml in: X.cbz" that would otherwise only be visible in the terminal during a large import run.

Check this file after any large import to review files that could not be processed without having to keep the terminal open the entire time.

## Understanding the Diff

Each log entry shows a **before/after diff** of the fields that changed. For example:

- A scrape entry shows the fields that changed: `series`, `publisher`, `cv_issue`, and `cv_volume` when values differed before and after the match. If the scrape failed, the entry shows `result: null -> no_match`. When the failure was caused by a Layer 3 cover hash rejection, a `reason` field is also included (e.g. `reason: null -> cover hash mismatch (phash dist 42, ahash dist 38)`).
- An organize entry shows `file: ["/comics/untagged/Batman #1.cbz", "/comics/library/DC Comics/Batman (2011)/Batman #001.cbz"]`: the old path and the new path as a two-element array.
- A write entry shows which ComicInfo.xml fields were embedded.
- A `convert_zip` entry shows the old `.zip` path and the new `.cbz` path.

For `organize_error` and `write_error` entries (shown with a red badge), the diff contains the error message returned by the file system or XML writer. Use this to diagnose why a file could not be moved or written. Common causes include permission errors, disk-full conditions, or path length limits on the host filesystem.
