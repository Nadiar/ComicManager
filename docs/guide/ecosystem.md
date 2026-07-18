# The Comic Ecosystem

ComicManager is one part of a three-tool ecosystem for managing, serving, and tracking a large comic collection. Each tool handles a distinct responsibility, and they share files through Docker volumes rather than tight coupling.

| Tool | Role |
|------|------|
| **ComicManager** | Process, tag, and organize raw comic files into a clean library |
| **ComicOPDS** | Serve the library to OPDS reader apps (Panels, KyBook, etc.) |
| **ComicTracker** | Track reading progress, rate comics, and get next-issue suggestions |

---

## How the Tools Connect

```
                     ┌─────────────────┐
  Drop .cbz files    │  ComicManager   │   Processes metadata,
  into /untagged  →  │  (Pipeline)     │ → organizes files into
                     └─────────────────┘   /Comics library
                              │
                              │ writes CBZ + ComicInfo.xml
                              ▼
                     ┌─────────────────┐
                     │  /Comics        │  (shared library folder)
                     └─────────────────┘
                        │           │
          reads library │           │ reads CBZ files
                        ▼           ▼
             ┌──────────────┐  ┌──────────────┐
             │  ComicOPDS   │  │ ComicTracker │
             │  (OPDS feed) │  │ (progress    │
             └──────────────┘  │  tracking)   │
                    │          └──────────────┘
         library.db │
         pages/     │ (shared data folder)
                    ▼
             ┌──────────────┐
             │  ComicTracker│  also reads library.db
             │  (watcher)   │  and pages/ from ComicOPDS
             └──────────────┘
```

The two key shared resources are:

- `/Comics`: the organized library folder. ComicManager writes here. ComicOPDS and ComicTracker both read from here.
- `comicopds/data/`: ComicOPDS's data folder. It contains `library.db` (the indexed catalog) and `pages/` (cached page images from OPDS streaming). ComicTracker mounts this folder read-only to know what is in your library and to detect reading progress when you stream pages.

---

## Complete Docker Compose Setup

The recommended approach is to run all three tools on the same host and wire them together via shared volume paths. Below is a complete `compose.yaml` you can use as a starting point.

```yaml
services:

  # ── ComicManager ──────────────────────────────────────────────────────────
  db:
    image: postgres:18-alpine
    user: "${UID}:${GID}"
    restart: unless-stopped
    environment:
      POSTGRES_DB: comicmanager
      POSTGRES_USER: comicmanager
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - ./comicmanager/data/postgres18:/var/lib/postgresql

  redis:
    image: redis:7-alpine
    user: "${UID}:${GID}"
    restart: unless-stopped
    volumes:
      - ./comicmanager/data/redis:/data
    command: redis-server --save 60 1 --loglevel warning

  comicmanager:
    image: gitea.baerentsen.space/frederikbaerentsen/comicmanager:latest
    user: "${UID}:${GID}"
    restart: unless-stopped
    command: daphne -b 0.0.0.0 -p 8000 comicmanager.asgi:application
    ports:
      - "8381:8000"
    env_file: comicmanager/.env
    volumes:
      - ./untagged:/comics/untagged          # drop new files here
      - ./Comics:/comics/library             # organized library output
      - ./comicmanager/data/static:/app/static
      - ./comicmanager/data/covers:/app/cover_cache
      - ./comicmanager/data/logs:/app/logs
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started

  comicmanager-worker:
    image: gitea.baerentsen.space/frederikbaerentsen/comicmanager:latest
    user: "${UID}:${GID}"
    restart: unless-stopped
    command: >
      celery -A comicmanager worker
        --loglevel=info
        --queues=serial,import,scrape,organize,write
        --concurrency=1
    env_file: comicmanager/.env
    volumes:
      - ./untagged:/comics/untagged
      - ./Comics:/comics/library
      - ./comicmanager/data/logs:/app/logs
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started

  comicmanager-beat:
    image: gitea.baerentsen.space/frederikbaerentsen/comicmanager:latest
    user: "${UID}:${GID}"
    restart: unless-stopped
    command: >
      celery -A comicmanager beat
        --loglevel=info
        --scheduler django_celery_beat.schedulers:DatabaseScheduler
    env_file: comicmanager/.env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started

  # ── ComicOPDS ──────────────────────────────────────────────────────────────
  comicopds:
    image: gitea.baerentsen.space/frederikbaerentsen/comicopds:latest
    restart: unless-stopped
    ports:
      - "8382:8080"
    environment:
      CONTENT_BASE_DIR: /library
      SERVER_BASE: "http://YOUR_SERVER_IP:8382"   # replace with your IP or domain
      DISABLE_AUTH: "true"
      ENABLE_WATCH: "true"
      AUTO_INDEX_ON_START: "true"
      PRECACHE_THUMBS: "true"
    volumes:
      - ./Comics:/library:ro                 # same library folder ComicManager writes to
      - ./comicopds/data:/data               # library.db and pages/ live here

  # ── ComicTracker ──────────────────────────────────────────────────────────
  comictracker:
    image: gitea.baerentsen.space/frederikbaerentsen/comictracker:latest
    restart: unless-stopped
    ports:
      - "8383:8000"
    environment:
      - PUID=${UID:-1000}
      - PGID=${GID:-1000}
      - LIBRARY_DB_PATH=/data/opds/library.db
      - PAGES_DIR=/data/opds/pages
      - TRACKER_DB_PATH=/app/data/tracker.db
      - COMIC_LIBRARY_PATH=/library
      - THUMBS_PATH=/app/data/thumbs
    volumes:
      - ./comicopds/data:/data/opds:ro       # read ComicOPDS index and cached pages
      - ./Comics:/library:ro                 # read raw CBZ files for cover extraction
      - ./comictracker/data:/app/data        # tracker.db and thumbnails
```

### Directory Layout

Running this compose file expects the following folder structure on your host:

```
/your/stack/
├── docker-compose.yml
├── untagged/                  # drop new comics here
├── Comics/                    # organized library (shared between all three)
├── comicmanager/
│   ├── .env                   # ComicManager environment file
│   └── data/
│       ├── postgres/
│       ├── redis/
│       ├── static/
│       ├── covers/
│       └── logs/
├── comicopds/
│   └── data/                  # library.db + pages/ (shared with ComicTracker)
└── comictracker/
    └── data/                  # tracker.db + thumbnails
```

---

## Typical Day-to-Day Flow

### Adding new comics

1. Drop `.cbz` or `.cbr` files into the `untagged/` folder.
2. In ComicManager, click **Scan Untagged**.
3. Run the pipeline: **Scrape All** then **Tag All** then **Format All** then **Write All**, or use **Run Full Pipeline** on each comic.
4. Once a comic reaches the **Done** state, its CBZ file is in the `Comics/` library with a fully embedded `ComicInfo.xml`.
5. ComicOPDS picks up the new file automatically if `ENABLE_WATCH` is on, or on the next re-index.

### Reading a comic

1. Open your OPDS reader app (e.g. Panels on iOS) and point it at `http://YOUR_SERVER_IP:8382/`.
2. Browse or search your library and open a comic.
3. As you read, the app streams pages through the OPDS PSE endpoint. ComicOPDS caches the pages in `comicopds/data/pages/`.
4. ComicTracker's file watcher detects the cached pages and automatically moves the comic to **Reading** status. After 3 cached pages, it starts tracking progress.

### Tracking and finishing

1. Open ComicTracker at `http://YOUR_SERVER_IP:8383/`.
2. Your currently reading comics appear on the dashboard with progress bars.
3. When you finish a comic, click **Finish** and give it a star rating.
4. ComicTracker suggests the next sequential issue in the series so you can start immediately.

---

## Port Reference

| Service | Default Port | Purpose |
|---------|-------------|---------|
| ComicManager | `8381` | Pipeline UI and management |
| ComicOPDS | `8382` | OPDS feed + dashboard |
| ComicTracker | `8383` | Reading progress tracker |

---

## Responsibility Matrix

| Responsibility | ComicManager | ComicOPDS | ComicTracker |
|----------------|:---:|:---:|:---:|
| Import and tag comic files | Yes | No | No |
| Organize and rename files | Yes | No | No |
| Write metadata into CBZ | Yes | No | No |
| Serve comics via OPDS | No | Yes | No |
| Cache page images for streaming | No | Yes | No |
| Track reading progress | No | No | Yes |
| Rate comics and suggest next issue | No | No | Yes |
| Modify files on disk | Yes | No | No |

Each tool reads and writes only within its own domain. This means any one of them can be updated or replaced without affecting the others.
