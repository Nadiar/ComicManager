from django.urls import path
from . import settings_views

app_name = "settings"

urlpatterns = [
    path("", settings_views.settings_index, name="index"),
    path("update/", settings_views.settings_update, name="update"),
    path("log/", settings_views.settings_log, name="log"),
]
