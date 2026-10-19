# Getting Started

## Prerequisites

- **Docker** and **Docker Compose**
- A **ComicVine API key** if you don't have a local `comicvine.db` (see [Scraping](/guide/scraping))

---

## 1. Create a directory

```bash
mkdir comicmanager && cd comicmanager
```

---

## 2. Download the compose file and env sample

```bash
wget https://gitea.baerentsen.space/FrederikBaerentsen/ComicManager/raw/branch/master/docker-compose.yml
wget https://gitea.baerentsen.space/FrederikBaerentsen/ComicManager/raw/branch/master/.env.sample
cp .env.sample .env
```

Open `.env` and set the required variables:

| Variable | Purpose |
|----------|---------|
| `UID` / `GID` | Host user IDs so Docker writes files as you. Run `id -u` and `id -g`. |
| `SECRET_KEY` | Django secret key. Change to a long random string. |
| `DB_PASSWORD` | PostgreSQL password. |
| `PORT` | Host port for the web interface. Default: `8381`. |
| `ALLOWED_HOSTS` | Optional. Hostnames or IPs the UI may be accessed on. Add your server's address if you open ComicManager from another machine. Default: `localhost,127.0.0.1`. |
| `UNTAGGED_DIR` | Host path for incoming comics. Default: `./untagged`. |
| `LIBRARY_DIR` | Host path for your organised library. Default: `./Comics`. |
| `CACHE_URL` | Optional. Redis URL for the cache that holds the ComicVine API budget. Default: the Celery Redis server, database `1`. |

::: tip Accessing from another device
If you open ComicManager from a phone or another computer and get an `Invalid HTTP_HOST header` error, add that machine's address to `ALLOWED_HOSTS` (comma-separated) and restart the `web` container.

If your machine gets its address over DHCP, the IP can change and start rejecting requests again. Give the host a reserved or static IP, or list every address you use.
:::

---

## 3. Create required directories

```bash
mkdir -p untagged Comics data/postgres18 data/redis data/covers data/logs
```

### Optional: local database files

If you have a `comicvine.db`, `latest.mcl`, or `inducks.db`, place them in `data/` and uncomment the relevant volume mounts in `docker-compose.yml`. Without them, scraping falls back to the ComicVine API.

See [Scraping: Data Sources](/guide/scraping#data-sources) for details.

---

## 4. Pull and start

```bash
docker compose pull
docker compose up -d
```

Check that all containers are healthy:

```bash
docker compose ps
```

---

## 5. Watch the first start

Database migrations and static files are applied automatically when the `web` container starts. Watch the progress with:

```bash
docker compose logs -f web
```

---

## 6. Open the app

Visit `http://localhost:8381` (or the port you set in `.env`). No login required.

Go to **Settings** and configure at minimum:

- **ComicVine API Key** if you are using API-only mode
- **Low Page Count Threshold** (default 5)
- **One-Shot / Limited Series thresholds** used by the Format phase

---

## 7. Your first import

1. Drop `.cbz`, `.cbr`, `.cb7`, or `.pdf` files into your `UNTAGGED_DIR` folder.
2. From the Dashboard, click **Scan Untagged**.
3. Comics appear in the **New** state and the pipeline begins.

::: tip
Watch the progress in the bottom-right corner for live status on any background task.
:::

### CLI import commands

**`scan_untagged`**: scans the untagged drop folder and imports new files into the New state:

```bash
docker compose exec web python manage.py scan_untagged [flags]
```

| Flag | What it does |
|------|-------------|
| _(none)_ | Scan the configured untagged folder and import any new files |
| `--dry-run` | Preview what would be imported without writing anything |
| `--path /alt/path` | Override the scan folder (default: `/comics/untagged`) |
| `--no-cleanup` | Skip the missing-file check (see below) |

When a file in the untagged folder disappears, the scan only deletes the database record if the comic is still in the **New** state. Comics further along keep their record and metadata and get the `file_missing` flag, which clears itself when the file is back. If the untagged folder is empty or most of its files are missing (for example, the disk is not mounted), the scan changes nothing and reports why. The scan result shows how many comics were imported, removed, flagged File Missing or found again.

---

**`import_library`**: scans an existing tagged CBZ library and imports every file into the database at the **Write to CBZ** state by reading its embedded `ComicInfo.xml`. This is the primary migration path for users coming from ComicRack or another manager. Note this is not the same as **Done**: Done is a separate, later state that a comic only reaches if it goes through the Write action again (for example via Run Pipeline).

```bash
docker compose exec web python manage.py import_library [flags]
```

| Flag | What it does |
|------|-------------|
| _(none)_ | Import all CBZ files (`.cbz` or `.CBZ`) found under the configured library path |
| `--dry-run` | Preview what would be imported without writing anything |
| `--path /comics/library` | Override the library path (default: `/comics/library`) |
| `--comicdb /path/to/ComicDb.xml` | Enrich imports with ComicRack's database (see below) |

The `--comicdb` flag accepts ComicRack's `ComicDb.xml` and enriches each imported comic with data that `ComicInfo.xml` does not carry: Tags, Teams, Locations, `MainCharacterOrTeam`, `SeriesGroup`, and `CustomValuesStore` entries. This is the only way to preserve that data on import. Entries are matched by relative file path, so it's safe to test against a small library subset (a couple of comics) with your full `ComicDb.xml`. Only the comics actually present in the scanned folder are enriched; everything else in the file is simply ignored.

With `--comicdb`, files that have no `ComicInfo.xml` at all are imported from their `ComicDb.xml` entry (series, number, volume, publisher, credits, and so on) instead of being skipped. ComicRack keeps that metadata in its database, so files it never wrote tags into can still be imported. Run **Write All** afterwards to embed the metadata in the files.

**`convert_misnamed_archives`**: finds files named `.cbz` that are really RAR or 7-Zip archives and converts them into real CBZ files in place. `import_library` skips these files and points to this command.

```bash
docker compose exec web python manage.py convert_misnamed_archives --dry-run
docker compose exec web python manage.py convert_misnamed_archives
```

| Flag | What it does |
|------|-------------|
| _(none)_ | Convert every misnamed archive under the library path |
| `--dry-run` | Only list the misnamed archives |
| `--path /comics/untagged` | Search another folder (default: `/comics/library`) |

Each file is extracted and repacked into a hidden temporary file next to it, and only replaces the original once it is complete and contains pages. If extraction fails (for example, a damaged archive), the original is left unchanged and the error is reported. Afterwards, run `import_library` (with `--comicdb` if the files have no `ComicInfo.xml`) to add the converted files.

**`backfill_imprint`**: fills in the Imprint of comics imported before 1.1.1. Those versions dropped the `<Imprint>` element on import, and **Write to CBZ** then replaces the file's `ComicInfo.xml` without it. Run this command before writing those comics. It reads `<Imprint>` from each comic's `ComicInfo.xml` and sets it on comics that have no imprint yet. The files are only read, and a comic that already has an imprint is never changed.

```bash
docker compose exec web python manage.py backfill_imprint --dry-run
docker compose exec web python manage.py backfill_imprint
```

| Flag | What it does |
|------|-------------|
| _(none)_ | Set the imprint on every comic without one whose `ComicInfo.xml` has an `<Imprint>` |
| `--dry-run` | Only list the imprints that would be set |

Imported comics that get an imprint are marked **Needs Re-organize**, as after editing the publisher. If an organizer profile uses `{<imprint>}`, check the new paths on the Path Audit page before running **Re-organize**.

---

## Updating

```bash
docker compose pull
docker compose up -d
```

Migrations run automatically on restart.

---

## Development mode

Clone the repo and start with the dev compose file. Plain `docker compose up` runs the production setup (it pulls the published image), so development needs `docker-compose.dev.yml` passed explicitly. It:

- Builds the image from source instead of pulling it
- Mounts the repo into the container for hot reload via the Django dev server
- Adds a `css` container running the Tailwind watcher

```bash
git clone https://gitea.baerentsen.space/FrederikBaerentsen/ComicManager.git
cd ComicManager
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

To save typing, set `COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml` in your `.env` so plain `docker compose` commands use both files.

---

## Troubleshooting

### Worker security warning on startup

The `worker` container may log warnings like:

```
SecurityWarning: An entry for the specified gid or egid was not found.
SecurityWarning: You're running the worker with superuser privileges
```

This is a false positive. Celery cannot resolve the numeric `GID` to a name because Alpine-based containers have a minimal `/etc/group`. The worker is running as the uid/gid you set in `.env` not as root. The warnings are safe to ignore.

### Redis memory overcommit warning

The `redis` container may log:

```
WARNING Memory overcommit must be enabled! Without it, a background save or
replication may fail under low memory condition.
```

This is a kernel setting on the Docker host, not something a container can change. Fixing it is entirely optional: ComicManager only keeps transient data in Redis (task queue, cache, API rate counters), so nothing important is lost even if a background save fails. The app runs fine with the warning present, just like the Celery warning above.

If you want to silence it anyway, run this on the host:

```bash
sudo sysctl vm.overcommit_memory=1
```

To persist it across reboots, add `vm.overcommit_memory = 1` to `/etc/sysctl.conf`.
