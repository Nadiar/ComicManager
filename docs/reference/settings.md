# Settings Reference

ComicManager settings are stored in the database and can be edited through the web interface (`/settings/`).

Most global settings (database passwords, ports, directory mappings) are configured via the `.env` file and `docker-compose.yml`. The values below are the runtime settings you configure in the UI.

---

## Scraping

Configure how ComicManager interacts with external metadata sources.

| Setting | Default | Description |
|---------|---------|-------------|
| `cv_api_key` | _(empty)_ | Your ComicVine API key. Required if you are not using a local `comicvine.db`. Get one at comicvine.gamespot.com/api/ |
| `scrape_api_fallback` | `false` | When `comicvine.db` is present but returns no match, also try the ComicVine API. Uses your API budget (3 calls per comic). |
| `scrape_0day_hours` | `24` | Window (in hours) used by the **Last Xh** button on the dashboard New Comics card. Clicking that button runs the full pipeline only on comics imported within this window. Useful for processing today's new arrivals without touching the backlog. |
| `scrape_hash_threshold` | `8` | Maximum Hamming distance for a pHash cover match to be accepted. Lower = stricter. Range: 0 (exact) to ~20 (loose). |
| `scrape_publisher_allow` | _(empty)_ | Comma-separated publisher names. When set, auto-match only accepts matches whose publisher contains one of these (e.g. `DC, Marvel, Image`). Leave blank to allow all. See [Publisher filtering](/guide/scraping#publisher-filtering). |
| `scrape_publisher_block` | _(empty)_ | Comma-separated publisher names auto-match must never pick (e.g. `Panini, Editorial Televisa`). Applied after the allow list. See [Publisher filtering](/guide/scraping#publisher-filtering). |
| `scrape_keep_publisher` | `false` | Keep the publisher a comic already has (e.g. `DC` from ComicRack) instead of replacing it with ComicVine's or Inducks' name (`DC Comics`). Comics without a publisher still get the scraped one. |
| `flag_unknown_publisher` | `true` | After a scrape, add the `unknown_publisher` flag when no enabled tagging ruleset covers the comic's publisher. Turn off if you don't keep a ruleset for every publisher; a re-scrape then clears the flag. |
| `scrape_insert_covers` | `true` | Insert variant covers immediately when scraping a single comic manually. If disabled, cover URLs are saved and inserted at Write time instead. |
| `batch_insert_covers` | `false` | Insert variant covers immediately during a batch scrape (both auto and "Confirm each" modes). Slow at scale. Each CBZ is extracted and recompressed. If disabled, cover URLs are saved and inserted at Write time instead. |
| `pipeline_insert_covers` | `false` | Insert variant covers immediately when the pipeline runs its scrape step. If disabled, cover URLs are saved and inserted at Write time instead. |
| `inducks_enabled` | `false` | Show the INDUCKS search option in the scrape modal (for Disney/European comics). |
| `inducks_username` | _(empty)_ | Currently unused. Reserved for future use. |
| `inducks_password` | _(empty)_ | Currently unused. Reserved for future use. |
| `inducks_country_lock` | _(empty)_ | Force a single country code (e.g. `dk`). Leave blank to show a dropdown instead. |
| `inducks_country_codes` | `dk,de,nl,se,no,fi,us,it,fr,br` | Comma-separated list of country codes shown in the INDUCKS country dropdown. |

---

## Import

Control how new comics are flagged during the import phase.

| Setting | Default | Description |
|---------|---------|-------------|
| `min_page_count` | `5` | Comics with fewer pages than this threshold are flagged with `low_page_count` for review. |
| `cover_page_threshold` | `3` | Comics at or below this page count AND with "cover" in the filename are flagged as cover-only files. |

---

## Library

Define your library's structure and file paths. Note: the actual directory paths are set via Docker volume mounts. These settings tell ComicManager where to look inside the container.

| Setting | Default | Description |
|---------|---------|-------------|
| `untagged_dir` | `/comics/untagged` | Drop folder where new digital comics are placed for import. Maps to `./untagged` on the host. |
| `library_dir` | `/comics/library` | Root of your organized library. Maps to `./Comics` on the host. |
| `cv_db_path` | `/cv_db/comicvine.db` | Path to the local ComicVine SQLite index. Maps to `./data/comicvine.db` on the host. |
| `cv_mcl_path` | `/cv_db/latest.mcl` | Path to the ComicVine MCL file (semicolon-delimited volume/issue index). |
| `inducks_db_path` | `/cv_db/inducks.db` | Path to the INDUCKS SQLite database. |

---

## Format Detection

Control how the Formatter categorizes series based on their issue counts.

| Setting | Default | Description |
|---------|---------|-------------|
| `one_shot_max_count` | `1` | Series with a total count at or below this value are categorized as One-Shot. |
| `limited_series_max_count` | `15` | Series with a count above One-Shot max but at or below this value are categorized as Limited Series. Series with a count above this are categorized as Main Series. |

**Example with defaults:**
- Count = 1 -> One-Shot
- Count 2-15 -> Limited Series
- Count 16+ -> Main Series

---

## Deduplication

Control how duplicate detection works.

| Setting | Default | Description |
|---------|---------|-------------|
| `duplicate_phash_distance` | `5` | Maximum pHash Hamming distance for two covers to be considered duplicates. `0` = identical pixels only; higher values catch more near-duplicates. Default `5` is a good balance for most collections. |

---

## Appearance

Customize the user interface behavior.

| Setting | Default | Description |
|---------|---------|-------------|
| `owner_name` | _(empty)_ | Your first name. Used in the dashboard greeting. |
| `show_series_completion` | `true` | Show a series/volume completion progress bar on comic detail pages. |
| `hide_zero_maintenance_rows` | `false` | Hide rows with a count of 0 in the Review & Maintenance card on the dashboard. |
| `filter_rail_default` | `false` | Show the filter rail sidebar on the comics list page by default. When disabled you can still open it on demand with the Filter button. |
| `show_au_scan` | `true` | Show the AU Scan link in the sidebar and top navigation. Disable if you do not use the Alternate Universe folder feature. |

::: tip Display preferences
Theme, color scheme, nav layout, table density, and the dashboard card toggles (the "This Week" activity chart and the priority banner) are configured per-user in **Settings** (`/settings/`), not here. See [Appearance & Display Settings](/guide/appearance).
:::

---

## System / Infrastructure

The Settings UI shows a live **System Status** readout that confirms whether the following files are present and accessible:

- **ComicVine DB**: `data/comicvine.db` or `latest.mcl`
- **I.N.D.U.C.K.S. DB**: `data/inducks.db`

If these files are missing, scraping will fall back to live ComicVine API calls (slower, subject to rate limits).

---

## Task Health

The **Task Health** section (also on the Settings page) lets you detect and recover from two kinds of background-task problems: stuck tasks and corrupt results.

**Check tasks** scans the database for both and lists what it finds. Each entry shows the task name, status, and how long ago it was last seen.

### Stuck tasks

A task becomes stuck when a worker is killed mid-execution or a container is restarted while a task is running. The task leaves a `PROGRESS` record in the database with no live worker behind it. The progress toast in the UI keeps showing because it polls that stale record.

The check lists any task not in a terminal state (`SUCCESS`, `FAILURE`, or `REVOKED`). **Force stop all** marks those tasks as `FAILURE` in the database and sends a cooperative cancel signal to each task ID. Once cleared, the progress toast dismisses on the next poll.

### Corrupt results

A corrupt result is a finished task whose stored outcome can no longer be read. This happens when a task fails with an exception that could not be serialized cleanly, leaving a result record the task system cannot decode. Polling such a task would otherwise return a server error every time, with no way for you to clear it.

The check lists any failed task whose stored result fails to decode. **Delete corrupt results** removes those broken records from the database so progress polling stops failing for them. The underlying task is already finished, so nothing is interrupted.

::: tip When to use this
If a progress toast is stuck after restarting the worker container, open Settings and use Task Health to clear it. If a task page returns a server error every time it polls for progress, that task has a corrupt result: run Check tasks and use Delete corrupt results to clear it. Purging the Celery queue (`celery purge`) only clears tasks waiting to start, so it does not affect tasks already picked up by a worker.
:::
