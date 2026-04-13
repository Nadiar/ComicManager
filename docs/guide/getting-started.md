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
| `UNTAGGED_DIR` | Host path for incoming comics. Default: `./untagged`. |
| `LIBRARY_DIR` | Host path for your organised library. Default: `./Comics`. |

---

## 3. Create required directories

```bash
mkdir -p untagged Comics data/postgres data/redis data/covers data/static data/logs
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

## 5. Run migrations

```bash
docker compose exec web python manage.py migrate
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

1. Drop `.cbz`, `.cbr`, or `.zip` files into your `UNTAGGED_DIR` folder.
2. From the Dashboard, click **Scan Untagged**.
3. Comics appear in the **New** state and the pipeline begins.

::: tip
Watch the progress toasts in the bottom-right corner for live status on any background task.
:::

---

## Updating

```bash
docker compose pull
docker compose up -d
docker compose exec web python manage.py migrate
```

---

## Development mode

Clone the repo and start normally. The `docker-compose.override.yml` is loaded automatically and:

- Builds the image from source instead of pulling it
- Mounts the repo into the container for hot reload via the Django dev server
- Adds a `css` container running the Tailwind watcher

```bash
git clone https://gitea.baerentsen.space/FrederikBaerentsen/ComicManager.git
cd ComicManager
docker compose up -d
```