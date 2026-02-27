# ComicManager

Web-based comic library manager built to replace the ComicRack workflow. Handles 40,000+ digital and physical comics through an 8-phase processing pipeline — from raw CBZ files to a fully organized, tagged, and metadata-enriched library.

## Features

- **8-phase workflow pipeline**: Ingest → Scrape → Count → Tag → Format → Deduplicate → Organize → Write
- **ComicVine matching**: pHash cover matching, fuzzy metadata matching, and live API fallback against a local ComicVine SQLite index
- **4-way metadata comparison**: Compare data across PostgreSQL, ComicInfo.xml, local ComicVine DB, and live CV API side-by-side
- **DataManager tagging**: Publisher-based rules engine for SeriesGroup, MainCharacterOrTeam, and other fields (replaces ComicRack's binary dataman.dat)
- **Format detection**: Auto-classifies comics as Main Series, Limited Series, One-Shot, TPB, Omnibus, Annual, etc.
- **Duplicate detection**: By ComicVine ID, series+number, and perceptual hash — with digital+physical same-ID explicitly excluded
- **Library Organizer**: Template-based folder organization with variable substitution and profile-based exclude rules
- **ComicInfo.xml writer**: Generates and embeds metadata into CBZ files
- **Smart Lists**: Saved queries with filters, sorting, optional ComicVine volume linking for missing issue detection
- **Physical comics**: First-class support — same workflow pipeline without file operations
- **Server-side pagination**: Handles 40k+ comic libraries without browser crashes

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Django 5.x, Python 3.12 |
| Database | PostgreSQL 16 |
| Task Queue | Celery + Redis |
| Frontend | Django Templates, HTMX, DaisyUI v5, Tailwind CSS v4 |
| Deployment | Docker Compose |

## Quick Start

Everything runs in Docker. No local Python, Node, or database setup needed.

```bash
# 1. Clone and configure
git clone <repo-url> && cd ComicManager
cp .env.example .env
# Edit .env — set DB_PASSWORD at minimum

# 2. Create data directories
mkdir -p data/postgres data/redis

# 3. Build and initialize
docker compose build
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py createsuperuser

# 4. Start all services
docker compose up -d

# App runs at http://localhost:8000
```

### Importing an existing library

```bash
# Import comics from the organized library folder (reads ComicInfo.xml from each CBZ)
docker compose exec web python manage.py import_library /comics/library

# Enrich with ComicRack's master database (optional)
docker compose exec web python manage.py import_library /comics/library --comicdb /path/to/ComicDb.xml

# Scan the untagged drop folder for new comics
docker compose exec web python manage.py scan_untagged
```

## Development

The `docker-compose.override.yml` is picked up automatically and provides:
- Source code mounted into containers — Python/template changes reload instantly
- Django dev server with `DEBUG=True`
- Tailwind CSS watcher that rebuilds on template changes
- No image rebuild needed for code changes

```bash
# View logs
docker compose logs -f web
docker compose logs -f worker

# Django shell
docker compose exec web python manage.py shell

# Run migrations after model changes
docker compose run --rm web python manage.py makemigrations
docker compose run --rm web python manage.py migrate

# Rebuild after requirements.txt or package.json changes
docker compose build && docker compose up -d
```

## Project Structure

```
ComicManager/
├── apps/
│   ├── core/           # Comic model, settings, state machine, views
│   ├── dashboard/      # Smart lists, pipeline overview, review queues
│   ├── scraper/        # ComicVine matching (pHash, fuzzy, API)
│   ├── tagging/        # Publisher rules engine (DataManager)
│   ├── format/         # Format detection (TPB, Main Series, etc.)
│   ├── organizer/      # Library Organizer: template engine + file moves
│   ├── duplicates/     # Duplicate detection and resolution
│   ├── writer/         # ComicInfo.xml generation and writing
│   └── physical/       # Physical comic entry and CSV import
├── comicmanager/       # Django project config (settings, urls, celery)
├── templates/          # Django HTML templates (DaisyUI v5)
├── static/css/         # input.css → main.css (built by Tailwind)
├── docker-compose.yml          # Production config
├── docker-compose.override.yml # Dev config (auto-loaded)
└── Dockerfile
```

## Volume Mounts

| Host Path | Container Path | Purpose |
|-----------|----------------|---------|
| `./untagged` | `/comics/untagged` | Drop folder for new comics |
| `./Comics` | `/comics/library` | Organized library output |
| `./data/comicvine.db` | `/cv_db/comicvine.db` | Local ComicVine SQLite index (read-only) |
| `./data/postgres` | `/var/lib/postgresql/data` | PostgreSQL data |
| `./data/redis` | `/data` | Redis persistence |

## Workflow Pipeline

Comics progress through 8 states. Each transition is triggered manually via the UI or in batch.

```
new → imported → counted → tagged → formatted → deduplicated → organized → written
```

| # | State | Action | Description |
|---|-------|--------|-------------|
| 1 | new → imported | Accept | Copy proposed values parsed from filename |
| 2 | imported → counted | Scrape | Match against ComicVine + set issue count |
| 3 | counted → tagged | Tag | Apply DataManager publisher rules |
| 4 | tagged → formatted | Format | Detect format (Main Series, TPB, One-Shot, etc.) |
| 5 | formatted → deduplicated | Deduplicate | Run duplicate detection |
| 6 | deduplicated → organized | Organize | Move files into library folder structure |
| 7 | organized → written | Write | Embed ComicInfo.xml into CBZ file |

## Configuration

### Environment Variables (`.env`)

| Variable | Description | Default |
|----------|-------------|---------|
| `DB_PASSWORD` | PostgreSQL password | *(required)* |
| `SECRET_KEY` | Django secret key | *(required for production)* |
| `UID` / `GID` | Host user/group IDs for file permissions | `1000` |
| `PORT` | Web server port | `8000` |

### Application Settings (`/settings/`)

Runtime settings configurable via the web UI:
- **ComicVine API Key** — For API fallback when local DB has no match
- Other settings as added

## Smart Lists

Smart lists are saved filter queries accessible at `/dashboard/smartlists/`. Each list is defined by one or more filters (field + lookup + value), all combined with AND logic.

### Filter lookup reference

| Lookup | Meaning |
|--------|---------|
| `equals` | Exact match |
| `not equals` | Exclude exact match |
| `contains` | Case-insensitive substring match |
| `not contains` | Exclude substring match |
| `is empty` | Field is null / key does not exist |
| `is not empty` | Field is not null / key exists |
| `greater than` / `less than` / `at least` / `at most` | Numeric comparison |

### Flag fields

Flags are stored as a JSON object on each comic (e.g. `{"low_page_count": true, "scrape_no_match": true}`). A flag is either present (set to `true`) or absent — flags are never set to `false`.

Use the `flags__<flag_name>` syntax in the field dropdown:

| Field | Lookup | Value | Finds |
|-------|--------|-------|-------|
| `flags__low_page_count` | `equals` | `true` | Digital comics with fewer pages than the configured threshold |
| `flags__is_pdf` | `equals` | `true` | PDF files flagged for manual review |
| `flags__no_series` | `equals` | `true` | Comics where no series name could be parsed from the filename |
| `flags__cover_only` | `equals` | `true` | Files with 3 or fewer pages and "cover" in the filename |
| `flags__needs_conversion` | `equals` | `true` | CBR/CB7 files that need converting to CBZ |
| `flags__missing_count` | `equals` | `true` | Comics where the issue count (`count` field) could not be populated from ComicVine |
| `flags__count_mismatch` | `equals` | `true` | Comics sharing a ComicVine volume where issue counts differ |
| `flags__scrape_no_match` | `equals` | `true` | Comics that went through scraping but no ComicVine match was found |
| `flags__scrape_error` | `equals` | `true` | Comics where scraping failed with an exception (API error, timeout, etc.) |

To find comics **without** a flag (i.e. the flag was never set), use `is empty` instead:

| Field | Lookup | Value | Finds |
|-------|--------|-------|-------|
| `flags__scrape_no_match` | `is empty` | `true` | Comics where the no-match flag does not exist |

### Proposed fields (STATE_NEW comics)

Comics in the `new` state have not yet had their metadata confirmed. Their parsed filename values sit in `proposed_*` fields:

| Field | Finds |
|-------|-------|
| `proposed_series` `is empty` | Comics where no series name could be parsed from the filename |
| `proposed_series` `contains` `Batman` | New comics whose filename contains "Batman" |
| `proposed_year` `equals` `2024` | New comics parsed as year 2024 |

### ComicVine custom values

| Field | Lookup | Value | Finds |
|-------|--------|-------|-------|
| `custom_values__comicvine_issue` | `is empty` | `true` | Comics with no ComicVine issue ID matched |
| `custom_values__comicvine_volume` | `equals` | `140426` | All comics belonging to a specific CV volume |
| `custom_values__scrape_source` | `equals` | `local_db` | Comics scraped from the local SQLite index |

### Workflow tracking fields

| Field | Lookup | Value | Finds |
|-------|--------|-------|-------|
| `needs_reorganize` | `equals` | `true` | Organized comics whose expected path no longer matches their current location |
| `needs_reformat` | `equals` | `true` | Comics whose count changed and may need a different format classification |
| `last_written` | `is empty` | `true` | Comics in `written` state that have never had ComicInfo.xml written |

## Key URLs

| Route | Description |
|-------|-------------|
| `/` | Dashboard with pipeline overview and smart lists |
| `/comics/` | Full comic list with search, filter, sort, pagination |
| `/comics/?state=imported` | Comics filtered by workflow state |
| `/comics/<uuid>/` | Comic detail with metadata comparison |
| `/comics/<uuid>/edit/` | Edit comic metadata |
| `/scraper/` | Scraper overview and batch operations |
| `/organizer/profiles/` | Library Organizer profile management |
| `/dashboard/smartlists/` | Smart list management |
| `/settings/` | Application settings |
