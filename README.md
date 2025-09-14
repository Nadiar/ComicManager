# ComicManager

Web-based replacement for the ComicRack workflow. Django + PostgreSQL + Celery, served via Docker Compose.

## Dev Quickstart

Everything runs in Docker. You don't need Python, Node, or anything else installed locally.

```bash
# 1. Copy and fill in the env file
cp .env.example .env
# Edit .env — set DB_PASSWORD and SECRET_KEY at minimum

# 2. Create required data directories
mkdir -p data/postgres data/redis data/static

# 3. Build the dev image (only needed once, or after requirements/package.json changes)
docker compose build

# 4. Run migrations
docker compose run --rm web python manage.py migrate

# 5. Create your admin user
docker compose run --rm web python manage.py createsuperuser

# 6. Start everything
docker compose up -d

# App is now running at http://localhost:8000
```

The `docker-compose.override.yml` file is picked up automatically in dev. It:
- Mounts your local source code into the container (changes reload instantly)
- Runs Django's dev server with DEBUG=True
- Starts a Node container that watches and rebuilds CSS on template changes
- No image rebuild needed when editing Python, templates, or CSS

## Updating after code changes

**Python / templates / CSS** — no action needed, changes reload automatically.

**After adding a new model or changing models:**
```bash
docker compose run --rm web python manage.py makemigrations
docker compose run --rm web python manage.py migrate
```

**After changing requirements.txt or package.json:**
```bash
docker compose build
docker compose up -d
```

## Useful commands

```bash
# View logs
docker compose logs -f web
docker compose logs -f worker

# Django shell
docker compose exec web python manage.py shell

# Run a management command
docker compose exec web python manage.py <command>

# Stop everything
docker compose down
```

## Project Structure

```
comicmanager/
├── apps/
│   ├── core/           # Comic model, Setting model, state machine
│   ├── dashboard/      # Smart list views, pipeline overview
│   ├── scraper/        # ComicVine matching (local SQLite + API)
│   ├── tagging/        # Publisher rules, DataManager logic
│   ├── format/         # Format detection and tagging
│   ├── organizer/      # Library Organizer: template engine + file moves
│   ├── duplicates/     # Duplicate detection and resolution
│   ├── writer/         # ComicInfo.xml writer
│   └── physical/       # Physical comic entry and CSV import
├── comicmanager/       # Django project: settings, urls, celery
├── templates/          # Django HTML templates (DaisyUI v4)
├── static/css/         # input.css (source) → main.css (built)
├── docker-compose.yml          # Production
├── docker-compose.override.yml # Dev (auto-loaded)
└── Dockerfile
```

## Volume mounts

| Path (container) | Purpose |
|---|---|
| `/comics/untagged` | Drop folder — new comics go here |
| `/comics/library` | Organized library — Library Organizer writes here |
| `/cv_db/comicvine.db` | Local ComicVine SQLite index (read-only) |

Map these to your actual folders in `.env` or via the Settings UI once running.
