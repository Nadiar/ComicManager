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

---

## 3. Create required directories

```bash
mkdir -p untagged Comics data/postgres data/redis data/covers data/logs
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
Watch the progress toasts in the bottom-right corner for live status on any background task.
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
| `--no-cleanup` | Skip removing database records for files that no longer exist on disk |

---

**`import_library`**: scans an existing tagged CBZ library and imports every file into the database at the Written state by reading its embedded `ComicInfo.xml`. This is the primary migration path for users coming from ComicRack or another manager:

```bash
docker compose exec web python manage.py import_library [flags]
```

| Flag | What it does |
|------|-------------|
| _(none)_ | Import all CBZ files found under the configured library path |
| `--dry-run` | Preview what would be imported without writing anything |
| `--path /comics/library` | Override the library path (default: `/comics/library`) |
| `--comicdb /path/to/ComicDb.xml` | Enrich imports with ComicRack's database (see below) |

The `--comicdb` flag accepts ComicRack's `ComicDb.xml` and enriches each imported comic with data that `ComicInfo.xml` does not carry: Tags, Teams, Locations, `MainCharacterOrTeam`, `SeriesGroup`, and `CustomValuesStore` entries. This is the only way to preserve that data on import.

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