# Formatting: Categorizing Your Collection

The **Formatting** phase identifies the specific publication format for each comic based on its metadata and issue count. This is how we distinguish a single-issue comic from a collected edition.

![Formatting Column](/formats.png)

## Automated Categorization

The "Format" field is a key piece of metadata for how you'll eventually organize your files on disk. While ComicVine provides some format information, it's often incomplete or inconsistent. ComicManager uses a combination of **keyword matching** and **issue count rules** to automatically categorize your collection.

ComicManager can automatically assign any of these nine formats:

| Format | Trigger type | Signal |
|--------|-------------|--------|
| Director's Cut | Keyword | "Director's Cut" in series or title |
| Black & White | Keyword | "Black & White" or "B&W" in series or title |
| Omnibus | Keyword or page count | "Omnibus" in series, title, or summary; or page count ≥ 500 |
| TPB | Keyword or page count | "TPB" / "Trade Paperback" in series, title, or summary; or page count ≥ 80 with a collection phrase in the summary |
| Annual | Keyword | "Annual" in series or title |
| Preview | Keyword | "Preview" or "Previews" in series or title |
| One-Shot | Issue count | `count = 1` with a low issue number |
| Limited Series | Issue count | `count` between 2 and 15 with a low issue number |
| Main Series | Issue count | `count > 15`, or any count with issue numbers above 15 (continuation / renumbered series) |

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
│ "TPB" / "Trade Paperback" in series, title,                                │
│ or summary? ────────────────────────────────── YES ──▶  TPB               │
├────────────────────────────────────────────────────────────────────────────┤
│ page_count ≥ 80 AND summary has issue range? ─ YES ──▶  TPB               │
├────────────────────────────────────────────────────────────────────────────┤
│ page_count ≥ 500? ──────────────────────────── YES ──▶  Omnibus           │
├────────────────────────────────────────────────────────────────────────────┤
│ "Annual" in series or title? ───────────────── YES ──▶  Annual            │
├────────────────────────────────────────────────────────────────────────────┤
│ "Preview" / "Previews" in series or title? ─── YES ──▶  Preview           │
├────────────────────────────────────────────────────────────────────────────┤
│ count not set? ─────────────────────────────── YES ──▶  (no result)       │
│                                                          missing_format    │
├────────────────────────────────────────────────────────────────────────────┤
│ count > 15? ────────────────────────────────── YES ──▶  Main Series       │
├────────────────────────────────────────────────────────────────────────────┤
│ issue number > 15? (any count ≤ 15) ────────── YES ──▶  Main Series       │
│   (continuation / renumbered series)                                       │
├────────────────────────────────────────────────────────────────────────────┤
│ count > 1? (so 2-15, low issue number) ─────── YES ──▶  Limited Series    │
├────────────────────────────────────────────────────────────────────────────┤
│ (count = 1, low issue number) ──────────────── YES ──▶  One-Shot          │
└────────────────────────────────────────────────────────────────────────────┘
```

"Continuation / renumbered series" means the issue numbers are in a high range (above 15), regardless of the volume's issue count. This catches both limited-looking volumes (count 2-15) and single-issue entries (count=1) that continue legacy numbering from a prior volume. For example, a volume with count=11 and issues #695-705, or a single issue at #33, is an ongoing series, not a limited run or one-shot. Use `format_ok` on the detail page to permanently lock the format if the auto-detection is wrong for a specific comic.

"Issue range in summary" means the summary text contains one of these collection signals: a range like `#1-5` or `#2-#8`, the word `Collects` (e.g. "Collects Batman #10-15"), a comma-separated issue list like `#1, 2, 3, 4`, the phrase "features the following issues", or "collecting issues". Any of these indicate the book bundles multiple individual issues rather than being a single-issue story.

### Known edge case: Omnibus in the summary

Some comics are incorrectly classified as Omnibus because their ComicVine summary mentions the word "Omnibus" incidentally. For example, an old anthology issue whose summary reads "later reprinted in the Omnibus". The comic itself is not an Omnibus, but the keyword match fires anyway.

If you see a regular single issue suggested as Omnibus on the Format Review page, open its detail/edit page and use the **Confirm Format** toggle to lock the correct format. Once confirmed, the comic will no longer appear on the Format Review page and its format will not be overwritten by future re-format runs.

### Why do we format after tagging?

We apply tagging rules *before* formatting because those rules might standardize the series name or the publisher, which can improve the accuracy of the formatting logic.

---

## Flags and Re-formatting

Because formats determine how your files are organized, ComicManager checks for inconsistencies and surfaces them via flags in the **Review & Maintenance Queue**.

### `missing_format`
Set when no rule produces a result (e.g. count is not set and no keywords match). You must manually assign a format from the detail page or edit screen.

### `needs_reformat`
Automatically set when a comic's issue count changes and the current format no longer matches. For example, a comic you had as a "One-Shot" because only one issue was released but it needs to become a "Limited Series" once the next issue is out. It appears in the Maintenance tab of the dashboard. Run **Format All** to process all flagged comics in one go.

### Confirming a Format (`format_ok`)

If auto-detection produces the wrong result for a specific comic, open its detail page and use the **Confirm Format** toggle. This sets `format_ok = True` on the comic, which:

- Excludes the comic from the **Format Review** page so it no longer appears as a suggestion.
- Prevents future re-format runs from overwriting the format you chose.
- Suppresses the `format_mismatch_in_volume` flag for that comic.

When you resolve a duplicate group and keep one comic, `format_ok` is also set automatically on the kept comic so it is not re-evaluated as part of a conflict.

### `format_mismatch_in_volume`
Set when comics in your library share the same ComicVine Volume ID but have different format values. This usually means an issue count is wrong or a DataManager rule was misapplied. Can be permanently suppressed per-comic via "Accept Conflict" or by using **Confirm Format** on the detail page.

### `cv_volume_conflict`
Set when two comics have the same Series, Volume, and Format but are linked to different ComicVine Volume IDs. This usually indicates a bad scrape where a comic was matched to the wrong series. Can also be permanently dismissed via "Accept Conflict".

---

## Format Review Page

The **Format Review** page (`/comics/format/`) groups your comics by detected format. Each group shows a count badge and an **Accept All** button that confirms every comic in that group in one click. Expanding a group shows the individual comics so you can confirm or override them one at a time.

Comics flagged `needs_reformat` appear in a dedicated group at the top with a per-row **Accept Re-format** button.

### Detect Format Conflicts

Click **Detect Format Conflicts** to sweep the entire library and set `format_mismatch_in_volume` and `cv_volume_conflict` flags across all comics where the format or ComicVine volume assignment is inconsistent within a volume. Run this after any bulk re-scrape or tagging pass.

### Detect Format Upgrades

Click **Detect Format Upgrades** to re-run format detection on every already-formatted comic and flag any whose auto-detected result differs from the value currently stored. Comics where the result changed are flagged `needs_reformat` and appear in the Format Review page for your review. Use this after adjusting the One-Shot or Limited Series count thresholds in Settings, or after a bulk re-scrape that updated issue counts.

---

## Manually Assignable Formats

The formats listed above are the ones the auto-detector can produce. The following formats can be assigned manually from the comic detail or edit page but are never output by auto-detection:

| Format | Description | Exempt from `number` validation |
|--------|-------------|:---:|
| `Hard Cover` | Hardcover collected edition | Yes |
| `Absolute Edition` | Oversized deluxe hardcover | Yes |
| `Graphic Novel` | Original graphic novel (not a reprint collection) | Yes |
| `HC` | Abbreviation for Hard Cover | Yes |
| `Special` | One-off special outside main series numbering | No |
| `Giant-Size` | Giant-sized special format issue | No |
| `King-Size` | King-sized special format issue | No |
| `Deluxe` | Deluxe edition | No |

Formats exempt from `number` validation will not be blocked at the Write phase if the `number` field is empty. This matters for collected editions that have no meaningful issue number. See [Writing Files](/guide/writing) for validation details.

Once assigned manually, use **Confirm Format** on the detail page to lock the format so future re-format runs do not overwrite it.
