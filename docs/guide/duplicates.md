# Deduplication: Keeping Your Collection Clean

ComicManager identifies and resolves duplicate comics in your collection using image hashing (pHash/ahash) and metadata matching. This is your final quality control before organization.

![Deduplication Overview](/dupe.png)

## Why Image Hashing?

Duplicates are a common problem in digital comic collections. You might have:
- The same issue with different filenames (e.g., `Batman 001.cbz` and `Batman (2011) #1.cbz`).
- The same issue with different metadata.
- A physical comic and a digital copy of the same issue. *(Note: ComicManager explicitly allows one physical and one digital copy of the exact same issue without treating them as duplicates).*

Standard metadata-based duplicate detection (like checking Series + Number) is not enough. It cannot distinguish between a main cover and a variant cover, or between a high-quality scan and a low-quality one.

That is why ComicManager primarily uses Image Hashing (pHash/ahash). By looking at the *actual cover image*, we can find near-identical images even if the file is completely different. This is a "fingerprinting" technique that is extremely accurate.

---

## How it Works

1.  **Duplicate Scanning**: During the **Formatted** state, ComicManager runs a multi-layered duplicate scan against your entire library.
2.  **Orphan Attachment**: After the main scan, any comic that still has no group is compared against members of existing pending groups. This catches comics that were processed in a later batch than their duplicate partners.
3.  **Consolidation**: Groups that share members are merged into one. A set of comics matched by both CV ID and pHash will appear as a single group, not two separate ones. The group with the most members survives; ties are broken by method priority (CV ID > Metadata > Cover Hash > Filename).
4.  **Grouping**: Grouped duplicates are presented in the **Deduplicated** state for review.

### Duplicate Methods

ComicManager groups duplicates using four methods, which you can filter by using the tabs on the Duplicate Review page.

One digital and one physical copy of the same comic is explicitly **not** a duplicate. Cover Hash and Filename detection only apply to digital comics.

#### CV ID

Matches comics that share the exact same ComicVine issue ID (`comicvine_issue` custom value). This is the most reliable method: if two files were both scraped and matched to the same CV issue, they are almost certainly duplicates.

The one exception is a digital+physical pair for the same issue. That combination is intentional and is excluded from grouping.

#### Series / Number (Metadata)

Matches comics with the same series name (case-insensitive), issue number (leading zeros stripped), and volume year. This catches unscraped or mis-tagged duplicates that have no CV ID yet.

Groups already covered by CV ID matching are skipped to avoid double-reporting.

Two additional filters prevent false positives:

- **Digital/physical exclusion**: a single digital + single physical copy is not a duplicate.
- **Page-count ratio check**: if the largest page count in the group is more than 3x the smallest, the group is skipped. This prevents a TPB (e.g. 120 pages) from being matched against a single issue (e.g. 24 pages) that share the same series, number, and year.

#### Cover Hash

Matches comics whose cover images are visually near-identical, measured by the Hamming distance between their pHash fingerprints. The default threshold is a distance of 5 bits, adjustable via **Settings > Deduplication > Cover Hash max distance**. Two covers can be resized, re-encoded, or slightly different scans and still match.

Only digital comics with a computed pHash are considered. Groups are built using a union-find algorithm so that transitively similar covers end up in the same group.

The distance for each member is shown in the review table. Lower is more similar; 0 means bit-for-bit identical.

#### Filename

Catches OS-generated duplicate files produced when a file is copied and the OS appends a suffix to avoid a name collision:

| OS | Example |
|----|---------|
| Linux | `Comic #001_1.cbz`, `Comic #001_2.cbz` |
| Windows | `Comic #001 (1).cbz`, `Comic #001 (2).cbz` |

The suffix is stripped and the canonical base name is used as the grouping key. At least one file in the group must carry the suffix. Two different comics that happen to live in the same folder are not grouped.

```
          ┌──────────────────────────────────────────────────────────┐
          │                     Comparison Pool                      │
          │                                                          │
          │  • Comics in STATE_DEDUPLICATED (no existing group)      │
          │  • All library comics without a group                    │
          │    (catches dupes of already-organized comics)           │
          └──────────────────────────┬───────────────────────────────┘
                                     │
                                     ▼
          ┌──────────────────────────────────────────────────────────┐
          │           Detection methods (run in parallel)            │
          ├──────────────────────────────────────────────────────────┤
          │  CV ID       same comicvine_issue value                  │
          ├─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┤
          │  Metadata    same series + number + volume               │
          │              skips if already grouped by CV ID           │
          │              skips if page-count ratio > 3x (TPB guard)  │
          ├─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┤
          │  Cover Hash  pHash Hamming distance <= 5 (configurable)  │
          ├─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┤
          │  Filename    same base filename, strip _1 / (1) suffix   │
          ├──────────────────────────────────────────────────────────┤
          │  One digital + one physical = never a duplicate.         │
          ├─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┤
          │  Cover Hash and Filename are digital-only.               │
          └──────────────────────────┬───────────────────────────────┘
                                     │
                        ┌────────────┴────────────┐
                 comic in a group?            not in any group
                        │                         │
                        ▼                         ▼
             ┌──────────────────┐      ┌──────────────────────────────┐
             │  Duplicate Group │      │     Orphan attachment pass   │
             │  -> Review Queue │      │  compare against members of  │
             └──────────────────┘      │  all existing pending groups │
                                       │  (CV ID > pHash > filename)  │
                                       └──────────────┬───────────────┘
                                                      │
                                       ┌──────────────┴───────────────┐
                                match found?                    no match
                                       │                              │
                                       ▼                              ▼
                            ┌──────────────────┐      ┌──────────────────────┐
                            │  Joined existing │      │  No duplicate found  │
                            │  Duplicate Group │      │  -> STATE_ORGANIZED  │
                            └──────────────────┘      └──────────────────────┘
```

### Why deduplicate after formatting?

We want to make sure the metadata and format are correct before we resolve duplicates. This allows you to:
- Compare a "Main Series" issue with a "Trade Paperback" version.
- Choose which version to keep based on the most complete metadata.

---

## Triggering Detection

Two buttons appear at the top of the Duplicate Review page.

**Run Detection**: The normal pipeline button. Processes only comics currently in the `Formatted` state (waiting for deduplication). Clean comics with no duplicate found are automatically advanced to `Organized`. Use this after importing and tagging a new batch.

**Scan All Comics**: A recovery tool. Scans every ungrouped digital comic regardless of its workflow state. Does not change any states. Use this when comics have already passed through the pipeline without being caught, for example after enabling duplicate detection on an existing library or after running the orphan attachment pass.

---

## Resolving Duplicates

Each duplicate group shows a side-by-side comparison of metadata and cover thumbnails. For each comic in the group you can take one of these actions:

- **Keep**: Advances this comic to Organize. If only one other comic remains pending after this, it is auto-kept too and the group resolves. With 3+ comics in a group, the group stays open so you can handle the rest individually.
- **Delete**: Hard deletes the comic. The file is removed from disk and the database record is gone permanently. Empty parent folders are cleaned up automatically.
- **Keep & Del Rest**: One-click resolution. Keeps the selected comic and hard deletes all others in the group.
- **Re-queue**: Sends the comic back to the Import stage and clears its ComicVine data so it can be re-scraped from scratch. Use this if you suspect a bad match caused the false positive.
- **Keep All**: Marks all comics in the group as intentional. They all advance to Organize. Use this when the detection was a false positive.

Every resolution decision is recorded in the `DuplicateResolution` audit log, viewable at `/duplicates/history/`.

---

## Examples

### Two copies of the same issue (2-comic group)

You have `Batman 001.cbz` and `Batman (2011) #1.cbz`. Same issue, different filenames. They land in a Cover Hash group.

1. Compare covers and metadata in the group card.
2. Click **Keep & Del Rest** on the higher-quality file. The other file is deleted from disk and the group resolves in one click.

### Accidental OS duplicate (Filename group)

You copied a file and your OS created `Batman 001_1.cbz` alongside `Batman 001.cbz`.

1. The Filename detection groups them automatically.
2. Click **Del** on `Batman 001_1.cbz`. The last remaining comic is auto-kept and the group resolves.

### Three versions: keep one, re-scrape one, delete one

You have three copies: a good scan, a low-quality scan, and one that might have been mis-tagged.

1. Click **Del** on the low-quality scan. The group refreshes with 2 remaining.
2. Click **Re-Q** on the possibly mis-tagged one. It leaves the group and goes back to Import for re-scraping.
3. The last comic is auto-kept and the group resolves.

### False positive (TPB vs single issue)

Series/Number detection matched a TPB and a single issue with the same series and number. They are not duplicates.

Click **Keep All**. Both advance to Organize and the group is marked intentional.
