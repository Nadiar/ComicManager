# Dashboard

The dashboard shows a summary of your collection, the Review & Maintenance queue, and the pipeline overview. The pipeline section has three display variants you can switch between in the settings:

| Variant | Description |
|---------|-------------|
| **Segments** | A horizontal bar chart where each pipeline state is a proportional segment. Clicking a segment navigates to that state's comic list. |
| **Flow** | A scaled node-based diagram with connectors. Clicking a circle navigates to that state's comic list. |
| **None** | Hides the pipeline chart entirely. |

The selected variant is saved to your display preferences and persists across sessions.

![Segments Pipeline](/pipeline_segments.png)

![Flow Pipeline](/pipeline_flow.png)


## Needs Your Attention

The **Needs your attention** card on the dashboard shows all flagged issues and maintenance items. It has three display styles you can switch between in **Settings > Display**:

| Style | Description |
|-------|-------------|
| **List** | A compact table with one row per issue type. Default. |
| **Grid** | A card grid where each issue type gets its own tile with a description and action button. |
| **Triage** | A ranked list ordered by urgency. Each item is numbered so you know exactly what to tackle first. |

![List](/needs_list.png)

![Grid](/needs_grid.png)

![Triage](/needs_triage.png)

### Triage ranking

In Triage mode, items are sorted by two keys, in order:

1. **Severity**: errors first, then warnings, then info items.
2. **Count descending**: within each severity tier, the issue type with the most affected comics ranks higher.

This gives the item most worth fixing right now the top position. The rank number shown in the circle reflects this combined priority score, not just count or severity alone.

### Maintenance items

Maintenance items (duplicates, stale metadata, re-organize needs, etc.) are lower-priority than active issues because they do not block the pipeline. They are hidden by default to keep the attention card focused.

Click the **+ N maintenance** button in the card header to reveal them inline, blending with the current display style:
- In **Grid**: maintenance items appear as additional tiles in the same grid.
- In **Triage**: they append below all active ranked items, continuing the numbering sequence. Active items retain their positions whether maintenance is shown or hidden.
- In **List**: they appear as additional rows at the end of the table.

Click **&minus; hide maintenance** to collapse them again.

![Needs Your Attention with maintenance expanded](/needs_expand.png)

## Weekly Summary Card

The **This Week** card on the dashboard shows a bar chart of import and pipeline activity over the past 14 days. Each bar represents one day; hovering shows the count. This gives a quick sense of recent throughput without opening the audit log.

![This Week card](/weekly.png)

The card can be shown or hidden via the checkbox in **Settings → Dashboard → Visible sections**.

## Priority Banner

When one pipeline stage holds a significantly larger backlog than the others, the dashboard shows a **priority banner** at the top of the pipeline section. It names the bottleneck stage and provides a direct action button so you can clear it without manually scanning the pipeline overview.

The banner can be shown or hidden via the checkbox in **Settings → Dashboard → Visible sections**.

![Priority banner](/start_here.png)

## The Review & Maintenance Queue

Throughout the pipeline, ComicManager continually audits your comics for issues, mismatches, or missing data. Instead of stopping the entire batch process, problem comics are flagged and sent to the **Needs your attention** card on your Dashboard.

The attention card covers two categories:

### Active Review

Issues that block a comic from properly proceeding through the pipeline.
- **Missing Series / Parse errors:** Filename couldn't be parsed.
- **ZIP Files:** Files with a `.zip` extension that need a one-click rename to `.cbz` before the Write phase.
- **Needs Conversion (CBR/CB7):** Non-native archives that must be converted to CBZ, including RAR or 7-Zip archives that were named `.cbz` or `.zip`.
- **Low Page Count / PDFs / Cover Only:** Flagged for deletion or manual confirmation.
- **Scrape Errors:** Matches couldn't be found on ComicVine or API errors occurred.
- **Metadata Mismatches:** Local metadata conflicts with ComicVine volume information.
- **Missing Format / Conflicts:** Missing format, or comics in the same volume have conflicting formats.
- **Corrupted Archives:** The CBZ file cannot be read or unzipped. Use **Try Rezip** to attempt recovery.
- **File Missing:** The comic's file is no longer on disk; its record and metadata were kept. See [`file_missing`](/guide/flags#file-missing).

### Maintenance
Issues that affect comics already deep in the pipeline (or fully written) that need your attention.
- **Duplicates:** Potential duplicates detected by ComicVine ID, Series/Number match, or cover image hashing.
- **Needs Re-organize:** Metadata was updated, meaning the current file path is now incorrect.
- **Needs Re-format:** The issue count for the volume changed, so count-based formatting (e.g., One-Shot vs. Limited Series) needs recalculation.
- **Stale Metadata / Missing ComicInfo:** The database has newer information than what is currently written inside the CBZ file.
- **Count Mismatch:** Disagreement between owned issues on the total volume count.
- **Format Mismatch:** Conflicting formats within the same ComicVine volume.
- **CV Volume Conflict:** Same series/number/format linked to different ComicVine volume IDs.
