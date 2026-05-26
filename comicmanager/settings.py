import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
DEBUG = os.environ.get("DEBUG", "False") == "True"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "channels",
    "django_celery_beat",
    "django_celery_results",
    "django_htmx",
    # Local apps
    "apps.core",
    "apps.scraper",
    "apps.tagging",
    "apps.format",
    "apps.organizer",
    "apps.duplicates",
    "apps.writer",
    "apps.physical",
    "apps.dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "comicmanager.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.active_tasks",
                "apps.core.context_processors.user_preferences",
                "apps.core.context_processors.scraper_settings",
                "apps.core.context_processors.nav_settings",
            ],
        },
    },
]

WSGI_APPLICATION = "comicmanager.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "comicmanager",
        "USER": "comicmanager",
        "PASSWORD": os.environ.get("DB_PASSWORD", "comicmanager"),
        "HOST": "db",
        "PORT": "5432",
    }
}

ASGI_APPLICATION = "comicmanager.asgi.application"

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")],
        },
    },
}

# Celery
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = "django-db"
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_QUEUES = {
    "import": {},
    "scrape": {},
    "organize": {},
    "write": {},
}
CELERY_RESULT_EXTENDED = True

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Container-side paths — these are fixed by the Docker volume mounts.
# UNTAGGED_DIR / LIBRARY_DIR in .env are HOST paths used only by docker-compose
# for the volume mapping; they must not be used here.
UNTAGGED_DIR = "/comics/untagged"
LIBRARY_DIR = "/comics/library"
CV_DB_PATH = "/cv_db/comicvine.db"
CV_MCL_PATH = "/cv_db/latest.mcl"
INDUCKS_DB_PATH = "/cv_db/inducks.db"
COVER_CACHE_DIR = os.environ.get("COVER_CACHE_DIR", "/app/cover_cache")
AUDIT_LOG_PATH = os.environ.get("AUDIT_LOG_PATH", "/app/logs/batch_actions.jsonl")

# Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "apps.duplicates": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "apps.organizer": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "apps.scraper": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
