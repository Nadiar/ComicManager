# Deduplication: Keeping Your Collection Clean

ComicManager identifies and resolves duplicate comics in your collection using image hashing (pHash/ahash) and metadata matching. This is your final quality control before organization.

![Deduplication Overview](/dupe.png)

## Why Image Hashing?

Duplicates are a common problem in digital comic collections. You might have:
- The same issue with different filenames (e.g., `Batman 001.cbz` and `Batman (2011) #1.cbz`).
- The same issue with different metadata.
- A physical comic and a digital copy of the same issue. *(Note: ComicManager explicitly allows one physical and one digital copy of the exact same issue without treating them as duplicates).*

Standard metadata-based duplicate detection (like checking Series + Number) isn't enough. It can't distinguish between a main cover and a variant cover, or even between a high-quality scan and a low-quality one.

That's why ComicManager primarily uses Image Hashing (pHash/ahash). By looking at the *actual cover image*, we can find near-identical images even if the file is completely different. This is a "fingerprinting" technique that is extremely accurate.

---

## How it Works

1.  **Duplicate Scanning**: During the **Formatted** state, ComicManager runs a multi-layered duplicate scan against your entire library.
2.  **Grouping**: Grouped duplicates are presented in the **Deduplicated** state for review.

### Duplicate Methods

ComicManager groups duplicates using four methods, which you can filter by using the tabs on the Duplicate Review page:
- **CV ID**: Finds comics linked to the exact same ComicVine issue ID.
- **Metadata**: Finds comics with the same series, volume, and issue number.
- **Cover Hash**: Finds comics with visually identical cover images using pHash (even if resized or slightly different scans).
- **Filename**: Catches OS-generated duplicate files (e.g., `file_1.cbz`, `file (1).cbz`).

One digital and one physical copy of the same comic is explicitly **not** a duplicate. Cover Hash and Filename detection only apply to digital comics.

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
          │              (skips if already grouped by CV ID)         │
          ├─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┤
          │  Cover Hash  pHash Hamming distance ≤ 5 (configurable)   │
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
             ┌──────────────────┐      ┌──────────────────────┐
             │  Duplicate Group │      │  No duplicate found  │
             │  -> Review Queue │      │  -> STATE_ORGANIZED  │
             └──────────────────┘      └──────────────────────┘
```

### Why deduplicate after formatting?

We want to make sure the metadata and format are correct before we resolve duplicates. This allows you to:
- Compare a "Main Series" issue with a "Trade Paperback" version.
- Choose which version to keep based on the most complete metadata.

---

## Resolving Duplicates

Each duplicate group shows a side-by-side comparison of metadata and cover thumbnails. For each comic in the group you can take one of four actions:

- **Keep**: Marks this comic as the winner and advances it to the next pipeline stage (Organize). Other comics in the group remain pending until you resolve them.
- **Delete**: Hard deletes the comic — the file is removed from disk and the database record is gone permanently. Empty parent folders are cleaned up automatically.
- **Keep & Del Rest**: One-click resolution. Keeps the selected comic and hard deletes all others in the group.
- **Re-queue**: Sends the comic back to the Import stage and clears its ComicVine data so it can be re-scraped from scratch. Use this if you suspect a bad match caused the false duplicate.
- **Keep All**: Marks all comics in the group as intentional — they all advance to Organize. Use this when the detection was a false positive.

Every resolution decision is recorded in the `DuplicateResolution` audit log, viewable at `/duplicates/history/`.