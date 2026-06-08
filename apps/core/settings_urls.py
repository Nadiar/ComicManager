from django.urls import path
from . import settings_views

app_name = "settings"

urlpatterns = [
    path("", settings_views.settings_index, name="index"),
    path("update/", settings_views.settings_update, name="update"),
    path("log/", settings_views.settings_log, name="log"),
    path("preferences/", settings_views.update_preferences, name="update_preferences"),
    path("dashboard/", settings_views.settings_dashboard, name="dashboard"),
    path("tasks/check/", settings_views.task_health_check, name="task_health_check"),
    path("tasks/clear/", settings_views.task_health_clear, name="task_health_clear"),
]
