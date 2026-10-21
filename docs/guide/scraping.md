# Scraping with ComicVine and I.N.D.U.C.K.S.

Scraping is **Phase 2** of the pipeline. It takes a comic that has been imported and links it to an external database to retrieve metadata: series info, issue title, full creator credits, character lists, summaries, and cover images.

After a successful scrape, the comic advances to the **Tagging** phase regardless of source.

## Data Sources

ComicManager supports multiple operating modes depending on what files you have available. Check your current mode under **Settings → Scraping**.

| Feature | Mode 1: Full DB | Mode 2: API Only | Mode 3: INDUCKS |
|---------|:-:|:-:|:-:|
| Cover hash matching | Yes (local) | No | No |
| Metadata matching | Yes (local) | Yes (API) | Yes (local) |
| ComicVine API fallback | Optional | Yes (required) | No |
| Series Audit | Yes | With `latest.mcl` | No |
| Variant cover fetching | Yes | Yes | No |
| Batch scraping | Yes | Yes | Manual only |
| Required file | `comicvine.db` | API key in Settings | `inducks.db` |

### Mode 1: ComicVine Full DB (Recommended)

![Scraping using `comicvine.db` with automatic cover matching](/scrape_db.png)

Place `comicvine.db` (a SQLite export of the ComicVine index) at `data/comicvine.db`. This is the fastest and most accurate mode because:

- Cover image hashing runs entirely locally, with no API calls needed for matching
- Metadata lookups are *almost* instant SQLite queries
- The API is only used as a last resort fallback

::: info Where to get comicvine.db
A proof-of-concept offline ComicVine database was posted here: [An offline ComicVine tagger (r/comicrackusers)](https://old.reddit.com/r/comicrackusers/comments/1q7rex8/here_it_is_an_offline_comicvine_tagger_for/)

This is a static and not an actively maintained project. To keep it up to date you need to write your own scraper against the ComicVine API. I have no affiliation with that project and cannot provide support for it. If you don't have the database, use API mode instead (Mode 2). It works fine, just slower and subject to rate limits. Do not open issues on this repository asking where to get the database.
:::

### Mode 2: ComicVine API Only (with optional MCL for Series Audit)

![Scraping using ComicVine API with automatic metadata matching](/scrape_api.png)


Without `comicvine.db`, ComicManager falls back to the ComicVine API for all matching. This covers most functionality: scraping, tagging, formatting, deduplication, and writing all work normally.

The one feature that requires an additional file is **Series Audit** (tracking which issues you own vs. are missing from a volume). For that make sure to map your local `data/latest.mcl` file in your `docker-compose.yml`. The MCL is a semicolon-delimited master comic list with volume and issue IDs, updated daily at [gitea.baerentsen.space](https://gitea.baerentsen.space/FrederikBaerentsen/ComicRack_Scripts/src/branch/master/Update%20Missing).

If neither `comicvine.db` nor `latest.mcl` is present, Series Audit is disabled with an explanatory message.

::: tip API rate limits
ComicVine enforces a 200 calls/hour limit. ComicManager tracks usage in Redis and will skip comics when the budget is exhausted. API calls are spaced at least 1.1 seconds apart across the whole app (web and worker share the spacing through Redis).
:::

To use API mode, set your **ComicVine API Key** in Settings.

::: tip Which mode am I in?
Go to **Settings** and check the **ComicVine Data Sources** section. Each data source shows its current status:

- `comicvine.db`: local SQLite index (hash + metadata matching, Series Audit)
- `latest.mcl`: volume list with issue IDs (Series Audit fallback)
- API key: ComicVine API (manual search + API-only batch scraping)

The active scraping mode is shown below, for example: `Scraping mode: Full local DB`.
:::

### Mode 3: I.N.D.U.C.K.S. (Disney/European Comics)

![Scraping using I.N.D.U.C.K.S.](/scrape_inducks.png)

::: warning 
I.N.D.U.C.K.S. support is experimental and there will be bugs as the workflow is tailored to ComicVine. 
:::

For Disney and other Duck related comics not typically well-covered by ComicVine, ComicManager integrates with the I.N.D.U.C.K.S. database.
Place `inducks.db` (generated from ISV flat files) at `data/inducks.db`.
- Searches by publication title, story title, author, and country code.
- Entirely local SQLite lookups.
- To use I.N.D.U.C.K.S. instead of ComicVine, select it in the scrape modal. (Note: batch scraping defaults to ComicVine unless specifically overridden).

## Cover Hash Computation

Before matching begins, ComicManager computes two perceptual hashes of the local cover image and stores them on the comic record. These are used for both duplicate detection and scrape matching.

**When hashes are computed:**

Hashes are computed when a comic is accepted from the New stage (via the Accept button, Accept All, or Run Full Pipeline). The first page of the CBZ is read and both a perceptual hash (pHash) and an average hash (aHash) are saved to the database.

Hash matching also saves hashes to the database as soon as they are computed during scraping, even when no candidate is found within the distance threshold or all candidates fail metadata cross-validation. This ensures hashes are always persisted after the first scrape attempt.

If hashes are missing when the CV API matching runs, they are computed on the fly at that point as a fallback.

Physical comics and comics without a readable CBZ cover will have no hashes stored, which is handled gracefully throughout the pipeline.

## How Matching Works

ComicManager uses a layered, fallback matching strategy. Each layer is tried in order until a confident match is found.

```
                    ┌──────────────┐
                    │   CBZ file   │
                    └──────┬───────┘
                           │
              ┌────────────┴─────────────┐
              │                          │
       comicvine.db present        no comicvine.db
              │                          │
              ▼                          │
   ┌──────────────────────┐              │
   │ Layer 1              │              │
   ├──────────────────────┤              │
   │ Cover Hash Match     │              │
   │ pHash + aHash vs.    │              │
   │ all DB covers        │              │
   └──────────┬───────────┘              │
              │                          │
        ┌─────┴──────┐                   │
     score > 0    no match               │
        │            │                   │
        ▼            ▼                   │
    ┌───────┐  ┌───────────────────┐     │
    │ MATCH │  │ Layer 2           │     │
    └───────┘  ├───────────────────┤     │
               │ Metadata Match    │     │
               │ Fuzzy series name │     │
               │ + number vs. DB   │     │
               └────────┬──────────┘     │
                        │                │
                  ┌─────┴──────┐         │
               score > 0    no match     │
                  │            │         └───────────────────┐
                  ▼            ▼                             │
              ┌───────┐  ┌────────────────────────────┐      |
              │ MATCH │  │ scrape_api_fallback        │      |
              └───────┘  │ enabled? (DB-only option)  │      |
                         └──────┬─────────────────────┘      |
                                │                            |
                    ┌───────────┴────────────┐               |
                   yes                       no              |
                    │                        │               |
                    │               ┌────────────────────┐   |
                    │               │  scrape_no_match   │   |
                    │               │  flag set          │   |
                    │               └────────────────────┘   |
                    │                                        |
                    └─────────────────┐       ┌──────────────┘
                                      │       |
                                      ▼       ▼
                          ┌─────────────────────────────┐
                          │ Layer 3                     │
                          ├─────────────────────────────┤
                          │ CV API Volume Search        │
                          │ 1. /search?resources=       │
                          │    volume (series name)     │
                          │ 2. /issues?filter=          │
                          │    volume:{id},             │
                          │    issue_number:{num}       │
                          │ 3. /issue/4000-{id}         │
                          │    (full details + credits) │
                          │ 4. Cover hash verification  │
                          │    Download CV cover and    │
                          │    compare vs local hash.   │
                          │    Reject if dist > 15.     │
                          └───────────┬─────────────────┘
                                      │
                         ┌────────────┴─────────────┐
                    hash agrees or               hash disagrees
                    no local hash                 (dist > 15)
                         │                           │
                         ▼                           ▼
                     ┌───────┐         ┌─────────────────────┐
                     │ MATCH │         │  scrape_no_match    │
                     └───────┘         │  reason stored in   │
                                       │  scrape_error_detail│
                                       └─────────────────────┘
```

"Hash agrees or no local hash" covers two cases that both accept the match: either the downloaded ComicVine cover's hash is within distance 15 of the comic's stored hash, or the comic has no stored hash to compare against in the first place (physical comics, unhashed archives), so verification is skipped and the match is accepted as-is.

### Layer 1: Cover Image Hash Match (DB mode only)

The stored cover hashes (computed at accept time, see above) are compared against all covers in `comicvine.db` using Hamming distance.

Why this is the most reliable method: hashes are based on the actual pixels of the cover, so they match even if the filename is completely wrong or the metadata is absent. It also means we avoid needing an LLM or OCR to extract information from the cover image. The downside is that if a cover variant looks significantly different from the one in the database, no hash match will be found. In practice this has not been a major issue.

After hash candidates are found, they are cross-validated against the comic's parsed metadata. Both checks can disqualify a candidate:

- **Issue number**: a mismatch immediately disqualifies the candidate.
- **Series name**: both sides are normalised (lowercase, punctuation stripped) and compared for exact match, substring containment, or shared first word. If both the comic's series and the candidate's series are known but share no resemblance at all, the candidate is disqualified. Issue number alone is too ambiguous (every series has a #1) to auto-apply a match.

The match is scored:

| Score | Issue number | Series name | Year | Result |
|-------|-------------|-------------|------|--------|
| 0 | Mismatch, OR both names known but no resemblance | n/a | n/a | Discarded |
| 1 | Matches | Not available to validate | Any | Accepted |
| 2 | Matches | Partial or substring match | Any | Accepted |
| 3 | Matches | Exact match | Any | Accepted |
| 3 | Matches | Partial match | Within ±2 | Accepted |
| 4 | Matches | Exact match | Within ±2 | Accepted (best) |

Only candidates with score > 0 are accepted. The highest-scoring candidate wins; ties are broken by lowest combined hash distance.

**Examples**, given a comic parsed as `Batman #1, 2011`:

- A candidate `Batman #1` from 2011 with no year recorded on the comic side to check: issue number matches, series matches exactly, year can't be checked → score 3, accepted.
- The same candidate, and the comic also has `2011` recorded: issue number matches, series matches exactly, year matches → score 4, accepted, wins over any lower-scoring candidate.
- A candidate `Batman and Robin #1`: issue number matches, series is a substring/partial match only → score 2, accepted, but loses to the exact-match candidate above.
- A candidate `Batman #2`: issue number does not match → score 0, discarded, regardless of how well the series name matches.
- A candidate `Spawn #1` when the comic's series is known to be `Batman`: issue number matches but the series names share no resemblance at all → score 0, discarded (a matching issue number alone is not enough; every series has a #1).

Exact series matches always outscore partial ones so a trade paperback whose title extends the single issue's name (e.g. `Batman: Batman #1` collecting `Batman #1`) can't win on a shared cover alone.

A candidate also scores 0 if its publisher is excluded by the allow or block lists, no matter how well the series and number line up. See [Publisher filtering](#publisher-filtering).

### Layer 2: Metadata Match (DB mode only)

If no hash match passes validation, ComicManager queries the local DB using the comic's `proposed_series` and `proposed_number`. It first attempts an exact case-insensitive series name match, then falls back to a substring query if nothing is found. Series name variations like "Batman: Year One" vs "Batman Year One" are handled by the same string normalisation used in Layer 1.

### Layer 3: API Search (API mode or DB fallback)

In API-only mode (or when the local DB has no match and the **API fallback** setting is enabled), ComicManager uses a volume-based search strategy:

1. `/search?resources=volume` searches for volumes by series name. Publisher, start year, and issue count are returned inline, so no separate `/volume` calls are needed.
2. `/issues?filter=volume:{id},issue_number:{num}` finds the specific issue within the best-scoring volume.
3. `/issue/4000-{id}` fetches full details and credits for the matched issue.
4. **Cover hash verification.** The cover URL returned by the API is downloaded and hashed. The result is compared against the comic's stored pHash and aHash using Hamming distance. If both distances are within 15 (a more lenient threshold than Layer 1 uses, to account for crop and edition differences), the match is accepted. If either distance exceeds 15, the match is rejected and `scrape_no_match` is set with a reason stored in `flags.scrape_error_detail` (e.g. `cover hash mismatch (phash dist 42, ahash dist 38)`).

Cover verification is skipped automatically when the comic has no stored hashes (physical comics, unhashed archives) or when the API returns no cover URL. In those cases the metadata match is accepted as-is.

This costs exactly **3 API calls total**: one call each to `/search`, `/issues`, and `/issue` (steps 1 through 3 above), and **0 calls to `/volume`**. The cover image download in step 4 is a plain image fetch, not an API call, and does not count against the hourly budget.

Before attempting a search, the remaining API budget is checked. If fewer than 3 calls are available, the comic is skipped rather than errored and can be retried in the next budget window.

## Publisher Filtering

ComicVine indexes every regional edition of a series, so a cover hash lookup for an American issue can just as easily return the Italian, Brazilian, or German reprint. Two settings under **Settings → Scraping** constrain which publishers auto-match is allowed to choose.

| Setting | Effect |
|---------|--------|
| `scrape_publisher_allow` | If set, only matches whose publisher contains one of these names are accepted. Blank allows everything. |
| `scrape_publisher_block` | Matches whose publisher contains one of these names are never accepted. Applied after the allow list. |

Both take a comma-separated list and compare case-insensitively as a **substring** of the publisher name, so a single entry covers a publisher's imprints. `Panini` blocks `Panini Comics`, `Panini Verlag`, and `Editorial Panini` in one go.

The two settings answer different needs and can be combined:

- **Block only**: keep matching everything except a few unwanted publishers. Set `scrape_publisher_block` to `Panini` and the rest of ComicVine stays available.
- **Allow only**: restrict the library to a known set. Set `scrape_publisher_allow` to `DC, Marvel, Image` and nothing else can be picked.
- **Both**: the allow list narrows the field first, then the block list carves out exceptions inside it.

**Matches with no publisher recorded always pass both lists.** Plenty of ComicVine volumes have no publisher set, and rejecting them would cost real matches in order to exclude a publisher that was never named.

### Where the filter applies

The lists govern automatic selection, not what you are allowed to pick by hand:

| Surface | Filtered |
|---------|----------|
| Batch scrape, pipeline scrape, `manage.py scrape` | Yes |
| Dry run preview | Yes |
| Scrape modal suggestion list | Yes |
| Scrape modal **Search API** tab | No |

The **Search API** tab stays unfiltered because typing a query there is a deliberate act. If you genuinely want the Panini edition for one comic, search for it and select it, and the excluded publisher is applied normally. The lists only stop ComicManager from reaching that conclusion on its own.

::: tip
Changes take effect within 30 seconds. The lists are cached briefly so a large batch scrape does not re-read them for every candidate.
:::

## Batch Scraping

The most common way to scrape is in bulk from the Dashboard.

1. From the Dashboard, navigate to the **Scrape** stage.
2. Click **Scrape All**.
3. A task runs in the background. The progress in the bottom-right shows live progress.

Comics with blocking flags (e.g. `is_pdf`, `low_page_count`, `needs_conversion`, `scrape_skipped`) are automatically skipped during batch scraping.

::: tip Management command
You can also trigger batch scraping from the command line:
```bash
docker compose exec web python manage.py scrape
docker compose exec web python manage.py scrape --dry-run             # preview matches without writing
docker compose exec web python manage.py scrape --limit 50            # process at most 50 comics
docker compose exec web python manage.py scrape --comic-id <uuid>     # scrape a single comic by UUID
docker compose exec web python manage.py scrape --method hash         # hash-only matching (no metadata fallback)
docker compose exec web python manage.py scrape --method metadata     # metadata-only matching (no hash)
docker compose exec web python manage.py scrape --method both         # use both methods (default)
docker compose exec web python manage.py scrape --max-distance 10     # override Hamming distance threshold
```
:::


## Single Comic Scraping

You can scrape a single comic from the comic's detail page, or directly from the comic list at `/comics/?state=scrape` using the per-row Scrape button.

1. Click **Scrape** in the actions panel or on the row.
2. The scrape modal opens and runs the matching layers automatically. The result shows the series name, issue number, publisher, ComicVine IDs, and match confidence score.
3. If the automatic match is wrong, you can search manually inside the modal using a different series name or issue number. Results are shown in batches of 3. Click **Show 3 more** to load additional results. Publisher and year for each result are fetched lazily in small batches to conserve API budget.
4. For I.N.D.U.C.K.S., switch to the INDUCKS tab in the modal and search by publication title, story title, or story code.
5. Click **Accept** to apply the match or **Reject** to discard it and leave the comic unchanged.

Re-scraping a comic that already has a match will overwrite the existing metadata after you accept.

::: tip Direct match by ComicVine ID
If you know the exact ComicVine issue ID, you can paste it directly into the manual search field in the scrape modal. Use the format `4000-XXXXXX` (e.g. `4000-123456`). ComicManager will look up that issue directly, bypassing the search and scoring layers entirely. This is the fastest way to match a comic when auto-detection fails.
:::

::: tip Direct match by I.N.D.U.C.K.S. story code
The INDUCKS tab has a separate story code field next to the general search box. If you already know the story's INDUCKS code, enter it there and press Enter to look up that exact story directly, bypassing the title/author search entirely.
:::


## Dry Run

Before running a full batch scrape, use the **Dry Run** tool at `/scraper/` to preview results without writing any changes to the database.

Click **Dry Run (N comics)**. The output streams line by line showing:
- Whether a hash match was found and which candidates passed or failed cross-validation
- Whether a metadata fallback was used
- The final match (series, issue number, publisher, CV issue ID) or `NO MATCH FOUND`
- A summary of total matched vs. failed

Dry run is the right place to debug why a specific comic is failing to match before committing a full batch scrape. It's a troubleshooting tool, not part of the regular day-to-day workflow.


## What Gets Written

The fields written to the comic depend on the scrape source.

### ComicVine Match

| Field | Value |
|-------|-------|
| `series` | ComicVine volume name |
| `number` | ComicVine issue number |
| `title` | Issue title |
| `publisher` | Publisher name |
| `count` | Total issue count in the volume |
| `volume` | Series start year |
| `year`, `month`, `day` | Parsed from the cover date, or the store date per the `scrape_date_source` setting |
| `summary` | Issue description (HTML stripped) |
| `writer`, `penciller`, `inker`, `colorist`, `letterer`, `cover_artist`, `editor` | Person credits by role |
| `characters`, `teams`, `locations` | From issue credits |
| `notes` | Internal reference noting the ComicVine issue ID used for the match |
| `web` | ComicVine detail URL |
| `custom_values.comicvine_issue` | CV issue ID |
| `custom_values.comicvine_volume` | CV volume ID |
| `custom_values.comicvine_issue_count` | Total issue count (also stored in `count`) |
| `custom_values.scrape_source` | Match type (`phash+meta`, `metadata`, `api+detail`, etc.) |
| `custom_values.scrape_score` | Hamming distance (hash) or alignment score (metadata) |
| `custom_values.StoreDate` | Store date, when `scrape_save_store_date` is on |

The comic advances to **Tagging**.

### I.N.D.U.C.K.S. Match (Issue)

When you match a comic to a specific I.N.D.U.C.K.S. issue (publication + story), the following fields are set:

| Field | Value |
|-------|-------|
| `series` | Publication title (e.g. "Anders And & Co.") |
| `number` | Issue number |
| `title` | Story title within the issue |
| `publisher` | Publisher name (if available) |
| `volume` | Year parsed from cover date |
| `year`, `month`, `day` | Parsed from cover date |
| `summary` | Story description from INDUCKS |
| `notes` | Internal reference noting the INDUCKS issue code and story code used for the match |
| `writer`, `penciller`, `inker`, `colorist`, `letterer`, `cover_artist` | Person credits by role |
| `characters` | Character appearances from INDUCKS |
| `web` | Link to the story on inducks.org |
| `custom_values.scrape_source` | `"inducks"` |
| `custom_values.inducks_issuecode` | INDUCKS issue code |
| `custom_values.inducks_publicationcode` | INDUCKS publication code |
| `custom_values.inducks_storycode` | INDUCKS story code |

The comic advances to **Tagging**. INDUCKS does not track total issue counts, so count-based features (issue count propagation, count mismatch detection) do not apply.

### I.N.D.U.C.K.S. Match (Story Code Only)

When you match a comic directly by story code without tying it to a specific issue, it is treated as a self-contained one-shot story. The same credits, characters, and dates are written as above, with these differences:

| Field | Value |
|-------|-------|
| `series` | Story title (same as `title`, treated as a self-titled one-shot) |
| `number` | Not set |
| `publisher` | Not set |
| `notes` | `Scraped metadata from I.N.D.U.C.K.S. story storycode` |
| `custom_values.inducks_issuecode` | Not set |

Because `number` and `publisher` are legitimately absent for story-only comics, write validation does not require them. `series` is the only required field.

The comic advances to **Tagging**.


## Variant Covers

After a ComicVine match is applied, ComicManager can automatically fetch all variant cover images for the issue from ComicVine and insert them into the CBZ file after the primary cover page. This tries the local `comicvine.db` first and falls back to a live API call if the covers aren't found there, the same DB-first pattern used everywhere else in scraping.
*(Note: physical comics download covers and cache them locally but do not write to files.)*

This happens only once per comic (tracked via `custom_values.HasAltCovers = "Yes"`). If variants were already inserted, re-scraping will skip this step.

The variant count is stored in `custom_values.AltCoverCount` and the total `page_count` is updated accordingly.

### Immediate vs. deferred insertion

Inserting covers during scraping is I/O-expensive: every matched CBZ must be fully extracted, the cover images downloaded, and the archive recompressed. To avoid this cost at scale, each scrape context has its own setting in **Settings > Scraping**:

| Setting | Default | When it applies |
|---------|---------|-----------------|
| `scrape_insert_covers` | `true` | Scraping a single comic manually from the UI |
| `batch_insert_covers` | `false` | Batch scrape (both auto and "Confirm each" modes) |
| `pipeline_insert_covers` | `false` | When the full pipeline runs its scrape step |

The split is deliberate: interactive scrapes insert covers by default because you're watching one comic, while batch and pipeline runs default to off so a 40,000-comic run doesn't rewrite every archive.

When a setting is **enabled**, covers are downloaded and inserted into the CBZ immediately after the match is applied.

When a setting is **disabled**, the cover URLs are saved in `custom_values.pending_alt_cover_urls` and no CBZ manipulation happens at scrape time. The **Write** step then picks them up: covers are inserted during the same CBZ pass that writes `ComicInfo.xml`, so the extraction and recompression cost is paid only once. If a comic is re-scraped before it reaches Write, the pending URLs are simply replaced with the new match's URLs.

::: warning These settings control timing, not whether covers are inserted
None of the three settings above can fully disable variant cover fetching. If a ComicVine match returns cover URLs for a digital CBZ comic that hasn't had covers inserted yet, they will always be inserted eventually, either at scrape time or at Write time. There is currently no setting to skip alt cover insertion entirely for such comics.
:::

::: tip Recommended for large batches
Keep all three settings disabled when processing large batches or omnibuses. Scraping stays fast and covers are inserted efficiently at Write time.
:::

::: info I.N.D.U.C.K.S. comics
INDUCKS-sourced comics do not support variant cover fetching. The "Find Alt Covers" action is disabled for them.
:::


## Issue Count Propagation

When a comic is scraped via ComicVine and the volume's total issue count is retrieved, ComicManager automatically updates the `count` field on **all other comics in the same CV volume** that are already in your library.

If any of those comics have a count-based format (One-Shot, Limited Series, Main Series) that would change under the new count, they are flagged with `needs_reformat` so they get re-evaluated in the Format phase.

This keeps your library internally consistent without requiring a re-scrape.

::: info I.N.D.U.C.K.S. comics
INDUCKS does not provide total issue counts. INDUCKS-sourced comics are excluded from count propagation and count mismatch detection entirely.
:::

## Handling Failed Matches & Review Flags

Failed scrapes are surfaced in the **Review Queue** on the Dashboard via specific flags:

### `scrape_no_match`
Set when the scraper finds no viable candidate, or when Layer 3 finds a metadata match but the cover hash comparison rejects it.

Check `flags.scrape_error_detail` on the comic (visible on the detail page and in the audit log) for the rejection reason. A value like `cover hash mismatch (phash dist 42, ahash dist 38)` means a metadata match was found but the API cover did not visually match the local file. This usually means the wrong volume was selected (e.g. a reprint series with the same name and issue number). Try re-scraping and selecting a different volume manually via the scrape modal.

For plain no-match cases, edit `proposed_series` and `proposed_number` on the comic's edit page to fix a bad filename parse, then re-scrape. Or manually search via the scrape modal. If it is a self-published one-shot, clear the flag manually to move it forward.

### `scrape_error`
Set when a technical error occurs: network timeout, API error, or a corrupted cover image. The detail is stored in `flags.scrape_error_detail`.
**Resolution:** For API errors, try again later. For corrupted archives, check the `corrupted_archive` flag and optionally "Try Rezip".

### `metadata_mismatch`
Set by a background audit task when `ComicInfo.xml` is already embedded in the CBZ but its metadata conflicts with what was parsed from the filename, or when the linked CV volume name doesn't match the local series name.
**Resolution:** Use the "To Scrape" rollback button in the Audit Log or re-scrape manually.

### `scrape_skipped`
If you intentionally skip a comic (via the detail actions menu) so that it doesn't get swept up in batch actions, it will be flagged here.


## API Rate Limits

ComicVine's API enforces a limit of approximately 200 calls per hour. The rate limit is enforced per IP address, not just per API key. Switching to a different API key does not reset the limit if you are on the same IP.

ComicManager tracks this with a rolling Redis counter per endpoint path. Each path (`/search`, `/volume`, `/issues`, `/issue`) has its own budget tracked independently. Usage is visible under **Settings** in the ComicVine Data Sources section.

Approximate call costs per operation:

| Operation | /search | /volume | /issues | /issue |
|-----------|---------|---------|---------|--------|
| Auto scrape (Layer 3) | 1 | 0 | 1 | 1 |
| Manual search (first 3 results) | 1 | up to 3 | 0 | 0 |
| Manual search (each "Show 3 more") | 0 | up to 3 | 0 | 0 |
| Apply manual selection | 0 | 0 | 0 | 1 |

::: warning Rate limit details
The figures above are approximate based on observed behaviour. The actual limits and enforcement rules are defined by ComicVine. Check [https://comicvine.gamespot.com/api/](https://comicvine.gamespot.com/api/) for authoritative information, especially if you are being rate limited unexpectedly.
:::

When the budget is exhausted, comics are skipped (not errored) and can be re-scraped in the next budget window. A warning is logged to the Celery worker log and the UI.

::: tip Conserving budget
Use the local `comicvine.db` whenever possible. Hash and metadata matching against the local DB costs zero API calls. The API is only used as a fallback when the local DB has no result.
:::
