# Quick Start

The setup consists of five containers:

| Container | Image | Role |
|-----------|-------|------|
| `web` | comicmanager | Django app served by Daphne. Handles all web requests. |
| `worker` | comicmanager | Celery worker. Runs background tasks: import, scrape, organize, write. |
| `beat` | comicmanager | Celery Beat scheduler. Triggers periodic tasks like metadata audits. |
| `db` | postgres:18 | PostgreSQL database. Stores all comic records, settings, and audit logs. |
| `redis` | redis:7 | Message broker for Celery and cache for API rate limiting. |

All three ComicManager containers use the same image, just running different commands.

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

Or with curl:

```bash
curl -O https://gitea.baerentsen.space/FrederikBaerentsen/ComicManager/raw/branch/master/docker-compose.yml
curl -O https://gitea.baerentsen.space/FrederikBaerentsen/ComicManager/raw/branch/master/.env.sample
cp .env.sample .env
```

Open `.env` and set at minimum `DB_PASSWORD` and `SECRET_KEY`. To reach the UI from another device, also add that device's host or IP to `ALLOWED_HOSTS`.

---

## 3. Create required directories

```bash
mkdir -p untagged Comics data/postgres18 data/redis data/covers data/logs
```

If you have a local `comicvine.db`, `latest.mcl`, or `inducks.db`, place them in `data/` and uncomment the relevant lines in `docker-compose.yml`. Without them, scraping falls back to the ComicVine API. See [Scraping: Data Sources](/guide/scraping#data-sources).

---

## 4. Pull and start

```bash
docker compose pull
docker compose up -d
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

Go to **Settings** to configure your ComicVine API key and library paths.

---

## Updating

```bash
docker compose pull
docker compose up -d
```

Migrations run automatically on restart.
