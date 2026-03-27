# Settings Reference

ComicManager settings are stored in the database and can be edited through the web interface (`/settings/`).

Most global settings (database passwords, ports, directory mappings) are configured via the `.env` file and `docker-compose.yml`. The values below are the runtime settings you configure in the UI.

---

## Scraping

Configure how ComicManager interacts with external metadata sources.

| Setting | Default | Description |
|---------|---------|-------------|
| `cv_api_key` | _(empty)_ | Your ComicVine API key. Required if you are not using a local `comicvine.db`. Get one at comicvine.gamespot.com/api/ |
| `scrape_0day_hours` | `24` | Currently unused. Reserved for future use. |
| `scrape_hash_threshold` | `8` | Maximum Hamming distance for a pHash cover match to be accepted. Lower = stricter. Range: 0 (exact) to ~20 (loose). |
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
| `import_convert_cbr` | `true` | Flag CBR/CB7 files with `needs_conversion` on import so they appear in the Review Queue for conversion. |

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
- Count 2–15 -> Limited Series
- Count 16+ -> Main Series

---

## Appearance

Customize the user interface behavior.

| Setting | Default | Description |
|---------|---------|-------------|
| `show_series_completion` | `true` | Show a series/volume completion progress bar on comic detail pages. |
| `hide_zero_maintenance_rows` | `false` | Hide rows with a count of 0 in the Review & Maintenance card on the dashboard. |

---

## System / Infrastructure

The Settings UI shows a live **System Status** readout that confirms whether the following files are present and accessible:

- **ComicVine DB**: `data/comicvine.db` or `latest.mcl`
- **I.N.D.U.C.K.S. DB**: `data/inducks.db`

If these files are missing, scraping will fall back to live ComicVine API calls (slower, subject to rate limits).
