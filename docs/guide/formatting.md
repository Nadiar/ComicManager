# Formatting: Categorizing Your Collection

The **Formatting** phase identifies the specific publication format for each comic based on its metadata and issue count. This is how we distinguish a single-issue comic from a collected edition.

![Formatting Column](/formats.png)

## Automated Categorization

The "Format" field is a key piece of metadata for how you'll eventually organize your files on disk. While ComicVine provides some format information, it's often incomplete or inconsistent. ComicManager uses a combination of **keyword matching** and **issue count rules** to automatically categorize your collection.

ComicManager can automatically assign any of these eight formats:

- **Director's Cut**: Series or title contains "Director's Cut".
- **Black & White**: Series or title contains "Black & White" or "B&W".
- **Omnibus**: "Omnibus" appears anywhere in the series, title, or summary. Also applied when page count is 500 or more and no other collection keyword matched.
- **TPB**: "TPB" or "Trade Paperback" in the series or title. Also applied when page count is 80 or more and the summary describes a collected issue range (e.g. "Collects #1-5", "#2-#8").
- **Annual**: Series or title contains "Annual".
- **One-Shot**: A standalone single-issue series (`count = 1`).
- **Limited Series**: A series with a known, finite run (`count 2–15`), where issue numbers are also in a low range.
- **Main Series**: An ongoing publication with 16 or more issues (`count > 15`), or a continuation/renumbered series where `count ≤ 15` but issue numbers are higher than 15.

The count thresholds for One-Shot, Limited Series, and Main Series are configurable under **Settings**.

If none of these rules produce a match the comic gets a `missing_format` flag and lands in the Review Queue for manual classification.

### Decision order

Rules are evaluated in priority order. The first match wins.

```
            ┌────────────────────────────────────────────────────┐
            │               Comic metadata                       │
            │   series · title · summary · count · page_count    │
            │                                                    │
            └──────────────────┬─────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ "Director's Cut" in series or title? ───────── YES ──▶  Director's Cut    │
├────────────────────────────────────────────────────────────────────────────┤
│ "Black & White" / "B&W" in series or title? ── YES ──▶  Black & White     │
├────────────────────────────────────────────────────────────────────────────┤
│ "Omnibus" in series, title, or summary? ────── YES ──▶  Omnibus           │
├────────────────────────────────────────────────────────────────────────────┤
│ "TPB" / "Trade Paperback" in series or title?  YES ──▶  TPB               │
├────────────────────────────────────────────────────────────────────────────┤
│ page_count ≥ 80 AND summary has issue range? ─ YES ──▶  TPB               │
├────────────────────────────────────────────────────────────────────────────┤
│ page_count ≥ 500? ──────────────────────────── YES ──▶  Omnibus           │
├────────────────────────────────────────────────────────────────────────────┤
│ "Annual" in series or title? ───────────────── YES ──▶  Annual            │
├────────────────────────────────────────────────────────────────────────────┤
│ count not set? ─────────────────────────────── YES ──▶  (no result)       │
│                                                          missing_format    │
├────────────────────────────────────────────────────────────────────────────┤
│ count ≤ 1? ─────────────────────────────────── YES ──▶  One-Shot          │
├────────────────────────────────────────────────────────────────────────────┤
│ count ≤ 15 AND issue number ≤ 15? ──────────── YES ──▶  Limited Series    │
├────────────────────────────────────────────────────────────────────────────┤
│ count ≤ 15 AND issue number > 15? ──────────── YES ──▶  Main Series       │
│   (continuation / renumbered series)                                       │
├────────────────────────────────────────────────────────────────────────────┤
│ count > 15 ──────────────────────────────────────────▶  Main Series       │
└────────────────────────────────────────────────────────────────────────────┘
```

"Continuation / renumbered series" means the volume has 15 or fewer issues but the issue numbers are in a high range (above 15), indicating the series continues legacy numbering from a prior volume. For example, a volume with count=11 and issues #695–705 is an ongoing series, not a limited run. Use `format_ok` on the detail page to permanently lock the format if the auto-detection is wrong for a specific comic.

"Issue range in summary" means the summary text contains a pattern like `#1-5`, `#2-#8`, or the word `Collects` (e.g. "Collects Batman #10-15"). This is the signal that the book bundles multiple individual issues rather than being a single-issue story.

### Known edge case: Omnibus in the summary

Some comics are incorrectly classified as Omnibus because their ComicVine summary mentions the word "Omnibus" incidentally. For example, an old anthology issue whose summary reads "later reprinted in the DC Omnibus". The comic itself is not an Omnibus, but the keyword match fires anyway.

If you see a regular single issue suggested as Omnibus on the Format Review page, open its detail/edit page and use the **Confirm Format** toggle to lock the correct format. Once confirmed, the comic will no longer appear on the Format Review page and its format will not be overwritten by future re-format runs.

### Why do we format after tagging?

We apply DataManager rules *before* formatting because those rules might standardize the series name or the publisher, which can improve the accuracy of the formatting logic.

---

## Flags and Re-formatting

Because formats determine how your files are organized, ComicManager checks for inconsistencies and surfaces them via flags in the **Review & Maintenance Queue**.

### `missing_format`
Set when no rule produces a result (e.g. count is not set and no keywords match). You must manually assign a format from the detail page or edit screen.

### `needs_reformat`
Automatically set when a comic's issue count changes and the current format no longer matches. For example, a comic you had as a "One-Shot" because only one issue was released but it needs to become a "Limited Series" once the next issue is out. It appears in the Maintenance tab of the dashboard. Run **Format All** to process all flagged comics in one go.

### `format_mismatch_in_volume`
Set when comics in your library share the same ComicVine Volume ID but have different format values. This usually means an issue count is wrong or a DataManager rule was misapplied. Can be permanently suppressed per-comic via "Accept Conflict".

### `cv_volume_conflict`
Set when two comics have the same Series, Volume, and Format but are linked to different ComicVine Volume IDs. This usually indicates a bad scrape where a comic was matched to the wrong series. Can also be permanently dismissed via "Accept Conflict".