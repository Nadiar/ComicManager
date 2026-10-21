# Flags

Flags are markers attached to a comic that signal something worth your attention. They live in a JSON field on the `Comic` model and can be set or cleared at any point, often automatically and sometimes manually. They do not block pipeline steps, with one exception: the **batch auto-scrape** skips any comic that carries any flag. This prevents the scraper from hammering a comic that already has a known problem.

Some flags can be **accepted**, which permanently suppresses them for that comic so future audit runs won't re-set them. Accepted flags can be revoked from the comic detail page.

---

## Quick Reference

| Flag | Severity | Set by | Cleared by | Accepts |
|------|----------|--------|------------|---------|
| `corrupted_archive` | error | Import scan or detail page view | Successful rezip or conversion | No |
| `file_missing` | error | Untagged scan or Path Audit: the file is no longer on disk | A scan or audit that finds the file again, Relink, or Remove | No |
| `low_page_count` | error | Import scan | Manually | No |
| `is_pdf` | warn | Import scan | Manually | No |
| `no_series` | warn | Import scan | Manually | No |
| `cover_only` | error | Import scan | Manually | No |
| `needs_conversion` | info | Import scan: CBR, CB7, or a RAR or 7-Zip archive named `.cbz` or `.zip` | Conversion to CBZ | No |
| `is_zip` | info | Import scan: a real ZIP archive named `.zip` | File renamed from `.zip` to `.cbz` | No |
| `scrape_no_match` | warn | Batch scrape finds no match | Successful scrape | No |
| `scrape_error` | error | Scraper throws an exception | Successful scrape | No |
| `scrape_error_detail` | n/a | Cover hash rejection (value, not boolean) | Successful scrape | No |
| `scrape_skipped` | info | User toggle on detail page | Same toggle / successful scrape | No |
| `unknown_publisher` | warn | Successful scrape, publisher not in any ruleset | Scrape or tagging recheck | No |
| `missing_count` | warn | Scrape: CV has no issue count for the volume | Count populated by audit or rescrape | Yes |
| `missing_format` | warn | Formatting: no signals to determine format | Format detected or set manually | No |
| `count_mismatch` | warn | Count audit: issues in same volume disagree | All issues in volume agree | Yes |
| `count_updated` | warn | Sibling issue scraped with a different count | Comic is re-written | No |
| `metadata_mismatch` | warn | Metadata audit: series name doesn't match CV volume | Next audit run or successful rescrape | No |
| `format_mismatch_in_volume` | warn | Format audit: issues in same volume have different formats | All issues in volume agree | Yes |
| `cv_volume_conflict` | warn | Format audit: same series+volume+format, different CV volume IDs | All issues point to the same CV volume | Yes |

---

## Import Flags

These evaluate immediately when a file is scanned: `import_library`, `scan_untagged`, or when a comic is accepted from the New stage. They reflect the file itself before any scraping has occurred.

```
              ┌────────────────────────────────┐
              │  File scanned / accepted       │
              └────────────────┬───────────────┘
                               │
       ┌───────────────────────┼────────────────────────────┐
       │                       │                            │
       ▼                       ▼                            ▼
 Can CBZ open?          Page count < min          File format / extension
       │                (default: 5)                        │
       │ no                    │ yes                        ├── pdf ──▶ is_pdf
       ▼                       ▼                            │
 corrupted_archive       low_page_count                     ├── cbr / cb7 ──▶ needs_conversion
                                                            │
                                                            └── .zip ──▶ is_zip

                               │
                               ▼
                 (same scan, two more independent checks)
                               │
       ┌───────────────────────┴────────────────────────────┐
       │                                                     │
       ▼                                                     ▼
  Series parsed?                          Page count ≤ 3 AND "cover" in filename?
       │ no                                                  │ yes
       ▼                                                     ▼
  no_series                                             cover_only
```

`corrupted_archive` and `low_page_count` are the ones that need action before the comic can progress usefully. A corrupted archive has a **Try Rezip** button on the detail page that tries to recover whatever pages can be extracted and re-save them as a valid CBZ. A low page count might be a truncated download, a preview file, or a single cover image. Check the file before deciding whether to keep it.

`needs_conversion` and `is_zip` are housekeeping: CBR and CB7 files can't be read for cover hashes or page counts, and ZIP is just a naming issue. Both have one-click fixes from the detail page, and batch conversion is available from the dashboard.

A file whose extension does not match its content is judged by the content: a `.cbz` or `.zip` that is really a RAR or 7-Zip archive gets `needs_conversion` instead of `corrupted_archive` or `is_zip`, and **Convert** turns it into a real CBZ. See [File Format Handling](/guide/file-formats#rar-or-7-zip-archives-named-cbz-or-zip).

`is_pdf`, `no_series`, and `cover_only` don't have automated fixes. They stay until you manually resolve the underlying issue and clear the flag.

---

## File Flags

### `file_missing`

The comic is in the database but its file is no longer on disk, for example because it was deleted or moved outside ComicManager. The record and all its metadata are kept.

- **Scan for New** sets it on comics in the untagged folder that are past the New stage. Untouched New comics whose file is gone are removed instead. If the untagged folder is empty or most of its files are missing (for example, the disk is not mounted), the scan changes nothing.
- **Path Audit** sets it on comics in the Write to CBZ or Done stage and lists them in the Missing files table instead of offering a move.

The flag clears itself when a scan or audit finds the file again. On the Path Audit page, **Relink** looks for the file in the library, and **Remove** deletes only the database record.

---

## Scrape Flags

Every time a scrape runs, batch or manual, it first clears `scrape_no_match`, `scrape_error`, `scrape_error_detail`, `metadata_mismatch`, and `scrape_skipped` from the previous attempt. Then the new attempt runs and may set new ones.

```
              ┌────────────────────────────────────────────┐
              │  Batch (auto) scrape only: comics flagged  │
              │  scrape_skipped are excluded from the      │
              │  queryset before the run starts            │
              └──────────────────┬─────────────────────────┘
                                 │
              ┌──────────────────▼──────────────────┐
              │  Scrape triggered (batch or manual) │
              └──────────────────┬──────────────────┘
                                 │
              ┌──────────────────▼─────────────┐
              │  Clear previous scrape flags   │
              └──────────────────┬─────────────┘
                                 │
           ┌─────────────────────┴─┐
      match found?             exception?
       │      │                    │
      yes     └───▶ no             ▼
       │            │        scrape_error (err)
       │            │
       │     auto (not manual)?
       │            │
       │           yes
       │            ▼
       │     scrape_no_match (warn)
       │     + scrape_error_detail if
       │       cover hash was the reason
       │
       ▼
  Apply match
       │
       ├── publisher in a ruleset? ──no──▶ unknown_publisher (warn)
       │
       └── CV issue count known? ──no──▶ missing_count (warn)
```

`scrape_no_match` is the most common flag you'll see. It means the scraper worked fine but couldn't find a confident match after trying all layers. The comic is not permanently broken. Use the manual search modal to pick the right issue yourself, and the flag clears on apply.

`scrape_error` means something actually went wrong (timeout, bad API response, disk error). Worth checking the audit log for the exception message before retrying.

`scrape_error_detail` is a string, not a boolean. It stores the specific reason the last attempt failed, typically something like `cover hash mismatch (phash dist 42, ahash dist 38)` when the API found a metadata match but the cover image didn't agree. It's surfaced on the detail page next to `scrape_no_match`.

`scrape_skipped` is a manual override. Use it for comics where you know ComicVine has no entry (magazines, custom comics, regional publications) and you don't want them clogging up the no-match queue. A successful scrape clears it.

`unknown_publisher` appears after a successful scrape when the publisher returned by ComicVine isn't covered by any enabled ruleset. The comic tags and formats normally, but the tagging rules won't apply to it. The fix is to add a Publisher rule to the relevant ruleset. The flag will clear on the next scrape or tagging pass for that comic. If you don't keep a ruleset for every publisher, turn off **Flag publishers not in a ruleset** (`flag_unknown_publisher`) in Settings → Scraping; the flag is then no longer added, and a re-scrape clears it.

`missing_count` appears when ComicVine has no issue count recorded for the volume. It doesn't block the pipeline but it does affect format detection, which needs a count to distinguish One-Shot from Limited Series from Main Series.

Two actions are available from the dashboard to populate counts:

- **Populate Issue Counts** (`/comics/populate-counts/`): queries ComicVine for the current issue count on every comic flagged `missing_count` and updates those records. Use this for a targeted fix after CV has published the count for a volume.
- **Populate All Counts** (`/comics/populate-counts-all/`): queries ComicVine for the current count on every comic in your library, regardless of whether they carry the flag. Use this for a full library refresh after a bulk re-scrape or when counts are suspected to be stale across many volumes.

---

## Format Flags

### `missing_format`

Appears after the Formatting step when no format could be determined. This almost always happens together with `missing_count`: without knowing how many issues a volume has, the count-based format rules (One-Shot, Limited Series, Main Series) can't fire, and if there are no other signals (page count, description keywords), the format stays empty.

The fix is usually to resolve `missing_count` first, then re-run formatting.

---

## Audit Flags

These are set by background tasks that sweep the entire library and compare comics against each other. They can only detect problems that are visible in aggregate. A single comic in isolation looks fine, but once you see it alongside its siblings, something is off.

```
                         ┌──────────────────────┐
                         │   Audit task runs    │
                         └──────────┬───────────┘
                                    │
          ┌─────────────────────────┼──────────────────────────┐
          │                         │                          │
          ▼                         ▼                          ▼
    Count Audit               Format Audit              Metadata Audit
          │                         │                          │
    ┌─────┴──────┐            ┌─────┴──────┐                   │
    │            │            │            │                   │
    ▼            ▼            ▼            ▼                   ▼
count_       count_      format_mis-   cv_volume_          metadata_
mismatch     updated     match_in_     conflict           mismatch
                         volume
```

**`count_mismatch`** fires when issues linked to the same CV volume disagree on their count field. This happens when some issues were scraped before ComicVine updated the volume's issue total. Running **Populate Issue Counts** pulls the current count from CV and reconciles them, which clears the flag. You can accept it per-comic for ongoing series where the count legitimately changes over time and the discrepancy doesn't bother you.

**`count_updated`** is set on already-written comics when a new scrape brings back a different count for the volume. The flag re-queues those comics for a targeted re-write. The **Write Count-Updated** batch task handles exactly this, rewriting only their `ComicInfo.xml` without touching anything else. It clears as soon as the write succeeds.

**`metadata_mismatch`** fires when a comic's `series` field has no substring relationship to the name of the CV volume it's linked to. The check is fuzzy: "Batman: Year One" vs "Batman: Dark Victory" both contain "Batman" so no flag, but "Superman" linked to a "Wonder Woman" volume would fire. When you see this, the comic was almost certainly matched to the wrong volume and needs a re-scrape. A successful scrape clears it automatically.

**`format_mismatch_in_volume`** fires when issues linked to the same CV volume carry different format values, for example some say "Main Series" and others say "TPB." This usually means at least one issue was matched to the wrong volume (a TPB and its single issues should not share a volume ID). Review the offending comics and re-scrape any that look wrong. You can accept it per-comic for edge cases where the mismatch is intentional.

**`cv_volume_conflict`** fires when comics that share the same `(series, volume year, format)` combination are linked to different CV volume IDs. Same diagnosis as `format_mismatch_in_volume` but the other direction: the series grouping in ComicManager agrees, but ComicVine disagrees. One or more matches are pointing to the wrong volume. Accept per-comic for cases where separate CV volumes genuinely exist for different regional editions that you're treating as one series.
