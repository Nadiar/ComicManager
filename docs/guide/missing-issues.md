# Series Audit

The Series Audit compares your library against ComicVine's complete issue list for a volume, showing exactly which issues you own and which you are missing.

![Missing Issues Comparison](/series_audit.png)

## How It Works

Series Audit requires a local ComicVine data source (either `comicvine.db` or `latest.mcl`). It queries that source for the full issue list of a volume, then cross-references your library by matching `comicvine_volume` and `comicvine_issue` IDs stored in each comic's custom values.

**Data source precedence:**

1. `comicvine.db`: Full metadata including cover images, titles, and cover dates.
2. `latest.mcl`: Issue IDs and numbers only, no cover images.
3. Neither available: the audit page shows an unavailability notice.

## Accessing Series Audit

**From a comic detail page:** Open any scraped comic and click the **Detials** button under **Series Completion**. The audit loads for the ComicVine volume linked to that comic.

**By URL:** Navigate to `/comics/<pk>/series-audit/` for a comic-anchored view, or `/comics/series-audit/volume/<cv_volume_id>/` to open the audit by ComicVine volume ID directly.

## What the Audit Shows

- **Completion percentage**: How many issues from the ComicVine volume you own, shown as a progress bar and a fraction (e.g. 42 / 60).
- **Owned issues**: Displayed with their cover image and a link to the comic detail page in your library.
- **Missing issues**: Displayed with the ComicVine cover (or a placeholder if using MCL), with a link to the issue's ComicVine page.
- **Filter tabs**: Toggle between **All**, **Owned**, and **Missing** to focus on what you need.

## Series Completion Widget

![](/series_audit3.png)

A compact version of the audit appears as a progress bar on the comic detail page. It loads via HTMX and shows the owned/missing split for the volume at a glance. This widget can be disabled under **Settings**.

## Character Audit

The **Character Audit** search at `/comics/series-audit/search/` lets you check completion status across all volumes for a given main character or team.

![](/series_audit4.png)

Enter a character name (matched against the `main_character_or_team` field) and ComicManager returns a list of all linked volumes sorted by completion percentage, from least to most complete. This gives you a quick overview of which runs in a character's history you are closest to finishing.
