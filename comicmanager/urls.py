from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.dashboard.urls")),
    path("comics/", include("apps.core.urls")),
    path("scraper/", include("apps.scraper.urls")),
    path("tagging/", include("apps.tagging.urls")),
    path("organizer/", include("apps.organizer.urls")),
    path("duplicates/", include("apps.duplicates.urls")),
    path("physical/", include("apps.physical.urls")),
    path("settings/", include("apps.core.settings_urls")),
]
