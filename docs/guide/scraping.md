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
- The API is only used as a last resort, and only when **API fallback** is turned on in **Settings → Scraping**

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
ComicVine enforces a 200 calls/hour limit. ComicManager tracks usage in Redis. When the budget runs out, a batch scrape stops and reports how many comics it got through, and a single scrape gets no match with the budget as the reason. API calls are spaced at least 1.1 seconds apart across the whole app (web and worker share the spacing through Redis).
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

ComicManager matches a comic against ComicVine in up to three layers and stops at the first one that finds a match. This is the automatic match used by batch scraping, **Run Pipeline**, a comic's automatic scrape and `manage.py scrape`. Picking an issue by hand in the scrape window skips it. The dry run preview runs only Layers 1 and 2, without the API.

```
                 ┌─────────────────────────────────┐
                 │ Automatic match                 │
                 │ the comic's series, number and  │
                 │ year (parsed from the filename  │
                 │ when the fields are empty)      │
                 └────────────────┬────────────────┘
                                  │
            ┌─────────────────────┴──────────────────────┐
   comicvine.db readable                         no comicvine.db
            │                                            │
            ▼                                            │
┌───────────────────────────────┐                        │
│ Layer 1: Cover Hash Match     │                        │
├───────────────────────────────┤                        │
│ Hash the file's cover (pHash  │                        │
│ and aHash). Take up to 10 DB  │                        │
│ covers whose pHash OR aHash   │                        │
│ distance is within the        │                        │
│ threshold (8), closest first, │                        │
│ and score each one. The best  │                        │
│ score wins, then the closest  │                        │
│ date, then the closest cover  │                        │
└───────────────┬───────────────┘                        │
        ┌───────┴──────────┐                             │
  best score > 0     no file, no cover                   │
        │            close enough, or                    │
        ▼            every score is 0                    │
    ┌───────┐              │                             │
    │ MATCH │              ▼                             │
    └───────┘  ┌───────────────────────────────┐         │
               │ Layer 2: Metadata Match       │         │
               ├───────────────────────────────┤         │
               │ Issues with the number in     │         │
               │ volumes named like the series │         │
               │ (any case; if none: names     │         │
               │ that contain it), closest     │         │
               │ year first, excluded          │         │
               │ publishers dropped. Take the  │         │
               │ first with a close cover (sum │         │
               │ <= 28), else the first if its │         │
               │ year is within 2 (no year:    │         │
               │ only one volume has #N)       │         │
               └───────────────┬───────────────┘         │
                       ┌───────┴────────┐                │
                   a result           none               │
                       │                │                │
                       ▼                ▼                │
                   ┌───────┐  ┌───────────────────┐      │
                   │ MATCH │  │ API fallback on?  │      │
                   └───────┘  │ Settings>Scraping │      │
                              └─────────┬─────────┘      │
                               ┌────────┴────────┐       │
                              no                yes      │
                               │                 │       │
                               ▼                 ▼       ▼
                    ┌─────────────────┐  ┌───────────────────────────┐
                    │ NO MATCH        │  │ Layer 3: ComicVine API    │
                    │ reason: API     │  ├───────────────────────────┤
                    │ fallback is off │  │ Needs an API key and 3    │
                    └─────────────────┘  │ calls left this hour      │
                                         │ 1. /search volumes by     │
                                         │    series name (30), rank │
                                         │    them (see Layer 3)     │
                                         │ 2. /issues: the number in │
                                         │    the best 3 volumes,    │
                                         │    one at a time          │
                                         │ 3. only if 2. gave no     │
                                         │    match and there is a   │
                                         │    number: /search issues │
                                         │    "series number", up to │
                                         │    3 results with the     │
                                         │    same number, score 3+  │
                                         └─────────────┬─────────────┘
                                                       │ each issue found,
                                                       │ in that order
                                                       ▼
                                         ┌───────────────────────────┐
                                         │ Cover check: ComicVine's  │
                                         │ cover vs the comic's      │
                                         │ pHash and aHash           │
                                         └─────────────┬─────────────┘
                                    ┌──────────────────┴─────────────┐
                       pHash + aHash distance <= 28,           sum above 28
                         or nothing to compare                       │
                                    │                                │
                                    ▼                                ▼
                      ┌───────────────────────────┐  ┌────────────────────────┐
                      │ 4. /issue/4000-{id}:      │  │ try the next issue;    │
                      │    details and credits    │  │ none left: NO MATCH,   │
                      └─────────────┬─────────────┘  │ the reason names the   │
                                    ▼                │ volumes and covers     │
                                ┌───────┐            │ that were tried        │
                                │ MATCH │            └────────────────────────┘
                                └───────┘
```

When nothing matches, the comic gets the `scrape_no_match` flag and stays in Scrape. The reason is saved in `flags.scrape_error_detail` and shown in the scrape result message (`No match found: ...`), in the error list of a batch scrape, and as `reason` in the comic's Audit Log entry. For example:

- `local comicvine.db: the closest #700 is in Batman (1940) from 2010, the comic is from 2020, and none of their covers is close to the comic's; API fallback is off (Settings > Scraping)`
- `local comicvine.db: no volume named "World War Hulk - Front Line" has #2; API fallback is off (Settings > Scraping)`
- `ComicVine API: #45 is not in Star Wars (1977); the cover does not match Star Wars (2015) #45 (cover hash mismatch (phash dist 30, ahash dist 24)); the issue search for "Star Wars 45" found no other issue with that number and a close series name`
- `ComicVine API: the budget of 200 calls per hour is used up, try again later`

### Layer 1: Cover Image Hash Match (DB mode only)

The comic's cover is read from the file and hashed (pHash and aHash), and the hashes are saved on the comic. They are compared with every cover in `comicvine.db` that has both hashes, using Hamming distance. A cover is a candidate when its pHash distance or its aHash distance is within the **Hash match threshold** (`scrape_hash_threshold`, default 8). Up to 10 candidates are kept, closest first by the sum of both distances. Comics without a file, such as physical comics, skip this layer. If the hash table in `comicvine.db` can't be read, the error goes to the container log and this layer finds nothing.

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

An issue number that is missing on either side is not compared, and a comic with neither a series nor a number scores 1. Only candidates with score > 0 are accepted. The highest-scoring candidate wins. On equal scores, the candidate whose year is closest to the comic's wins (its cover year or its volume's start year, whichever is closer), then the one whose cover month is closest to the comic's, and then the one with the lowest combined hash distance. The comic's month is its Month field, or the month of a ComicRack date such as `[October, 2015]` in its filename. Reprints often have the same cover as the issue, sometimes with a closer hash: the Planeta DeAgostini edition of `Star Wars #45` from 2019 has Marvel's 2018 cover, and their `Star Wars #8` from November 2015 has Marvel's October 2015 cover. The year picks Marvel's #45, and the month Marvel's #8. Without a year, the hash distance decides.

**Examples**, given a comic parsed as `Batman #1, 2011`:

- A candidate `Batman #1` from 2011 with no year recorded on the comic side to check: issue number matches, series matches exactly, year can't be checked → score 3, accepted.
- The same candidate, and the comic also has `2011` recorded: issue number matches, series matches exactly, year matches → score 4, accepted, wins over any lower-scoring candidate.
- A candidate `Batman and Robin #1`: issue number matches, series is a substring/partial match only → score 2, accepted, but loses to the exact-match candidate above.
- A candidate `Batman #2`: issue number does not match → score 0, discarded, regardless of how well the series name matches.
- A candidate `Spawn #1` when the comic's series is known to be `Batman`: issue number matches but the series names share no resemblance at all → score 0, discarded (a matching issue number alone is not enough; every series has a #1).

Exact series matches always outscore partial ones so a trade paperback whose title extends the single issue's name (e.g. `Batman: Batman #1` collecting `Batman #1`) can't win on a shared cover alone.

A candidate also scores 0 if its publisher is excluded by the allow or block lists, no matter how well the series and number line up. See [Publisher filtering](#publisher-filtering).

### Layer 2: Metadata Match (DB mode only)

If no hash candidate scores above 0, ComicManager looks the comic up in `comicvine.db` by name. This needs a series. The series, number and year are the comic's own, or the ones parsed from the filename when those fields are empty.

1. It finds the issues with the comic's number (as written or without leading zeros) in volumes whose name equals the series, ignoring case. Only if there are none, it uses volumes whose name contains the series. Names are compared as written, so `Batman: Year One` does not find `Batman Year One`.
2. The issues are sorted by year, closest to the comic's year first. An issue's year is its cover year or its volume's start year, whichever is closer, because a filename like `X-Men (2021) 001` gives the volume's year. Ties go to the volume with the most issues, and comics without a year keep that order. Matches from excluded publishers are removed (see [Publisher Filtering](#publisher-filtering)).
3. The first issue whose cover is close to the comic's wins: the pHash and aHash distances to its cover in `comicvine.db` add up to 28 or less, the same rule as the API cover check. A close cover wins even over a closer year.
4. If no cover is close, the first issue is taken when its year is within 2 of the comic's. Layer 1 has already compared covers, so the right issue often has another cover here, such as a variant or a different scan, and the year decides. A comic without a year only gets a match when a single volume has that number.

Otherwise the comic gets no match from this layer, with the reason, for example `the closest #700 is in Batman (1940) from 2010, the comic is from 2020, and none of their covers is close to the comic's`. This keeps `Batman #100` from 2020 from matching the 1940 run, which has the most issues.

### Layer 3: API Search (API mode or DB fallback)

In API-only mode, or when Layers 1 and 2 found nothing and **API fallback** (`scrape_api_fallback`) is on, ComicManager asks the ComicVine API. This needs an API key in Settings and a series.

1. `/search?resources=volume` searches volumes by series name. It returns up to 30 volumes with publisher, start year and issue count, so no `/volume` calls are needed. Volumes that score 0 (name too different, publisher excluded) are dropped, and the rest are ranked:
    - A volume that started more than a year after the comic's year goes last.
    - A volume with fewer issues than the comic's number goes after the volumes with enough. It is kept, because volumes with legacy numbering, like Amazing Spider-Man #800 in the 2015 volume, hold numbers above their issue count. ComicVine also lists many regional reprints with only a few issues, which this moves out of the way.
    - Within those groups: the highest score first, then the start year closest to the comic's year, then ComicVine's own order.
2. `/issues?filter=volume:{id},issue_number:{num}` looks the number up in the best-ranked volume, then in the next one, up to 3 volumes. A comic without a number is only looked up when the best volume is a one-shot, as #1.
3. If none of the volumes gave a match and the comic has a number: `/search?resources=issue` with "series number", the same search as the scrape window's **Search API** tab. Issues already checked are skipped. The rest need the same number and a score of 3 or more (an exact series name, or a partial one with a year within 2), and up to 3 of them are checked, best score first. These results carry no publisher, so it is taken from the volume search when the issue's volume was among those results, and the publisher lists apply to it.
4. **Cover check.** Every issue found in step 2 or 3 is checked before anything else is fetched. ComicVine's cover is downloaded and hashed, and compared with the comic's pHash and aHash. The two distances must add up to 28 or less; otherwise the next issue is tried. This is more lenient than Layer 1, to allow for crop and edition differences. Measured on about 1,500 comics from a real library, it accepts 95% of the right issues. The few wrong issues it accepts are almost all reprints with the same cover. Requiring each distance to be within 15, as before, accepted 92%, and missed right issues where one hash was close and the other just over, such as pHash 16 and aHash 5. The check is skipped, and the issue accepted, when the comic has no cover hashes and none can be made from its file (physical comics, unreadable archives), when ComicVine has no cover image, or when the download fails.
5. `/issue/4000-{id}` fetches the full details and credits of the first issue that passes. The match type is `api+volume+detail` when it came from step 2 and `api+search+detail` when it came from step 3. If the details can't be fetched, the comic gets no match.

**API calls:** a comic found in the first volume costs 3 calls: `/search`, `/issues` and `/issue`. Each further volume costs one more, and the issue search one more, so a comic costs at most 6. The cover download is a plain image fetch, not an API call, and does not count against the hourly budget of 200 calls. The volume search only starts with at least 3 calls left in the hour, and every further lookup needs 2 left; otherwise the comic gets no match with the budget as the reason. A batch scrape in API-only mode stops as soon as fewer than 3 calls are left and reports how many comics it got through.

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

## In-Store Dates

ComicVine gives each issue a cover date and, for many issues, an in-store date: the day it went on sale. Scraping fills Year, Month and Day from the cover date. Marvel and DC cover dates run about two to three months ahead of the in-store date, so an issue that came out this week can have a date two months from now, and "recently released" views in Komga and other readers that use these fields put it in the wrong place.

The setting **Use in-store date for** (`scrape_store_date_publishers`) under **Settings → Scraping** takes a comma-separated list of publishers. Comics matched to one of them get Year, Month and Day from the in-store date instead. Names are compared like the publisher lists: case-insensitively, as part of the publisher name, so `Marvel` also covers `Marvel Knights`.

- Every scrape uses it: batch, pipeline, the scrape window and `manage.py scrape`.
- When ComicVine has no in-store date for an issue, the cover date is used. Many older issues have none.
- With a local comicvine.db, the in-store date is read from it. In API mode it comes with the issue details, so it costs no extra API calls.
- Matching is not affected. Picking a match still compares the comic's year with the cover date.

Comics scraped before their publisher was added to the list keep their cover date. `apply_store_dates` sets the in-store date on them, read from the local comicvine.db. In API mode, scrape them again instead.

```bash
docker compose exec web python manage.py apply_store_dates --dry-run
docker compose exec web python manage.py apply_store_dates
```

Only comics with a ComicVine issue ID from a listed publisher are changed, and issues without an in-store date keep their date. Comics that ComicManager already wrote show as **Stale Metadata** on the dashboard; **Write Stale** puts the new dates into their files. Removing a publisher from the list does not change comics back: scrape them again to get the cover date.

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
2. The scrape modal opens and runs the matching layers automatically. Candidates are listed in the order Layer 1 picks them: score, then closest year and month, then closest cover. The result shows the series name, issue number, publisher, ComicVine IDs, and match confidence score. If looking up local matches fails (for example with a damaged `comicvine.db`), the modal shows the reason and still offers the manual search.
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
- Whether a hash match was found and which candidates passed or failed cross-validation, with each passing candidate's score, cover date and hash distance
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
| `year`, `month`, `day` | Parsed from the cover date, or from the in-store date for publishers in the in-store date list (see [In-Store Dates](#in-store-dates)) |
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
