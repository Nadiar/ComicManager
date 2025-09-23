from django.urls import path
from . import views

app_name = "duplicates"

urlpatterns = [
    path("", views.duplicate_review, name="review"),
    path("detect/", views.run_detection, name="detect"),
    path("scan-all/", views.scan_all, name="scan_all"),
    path("history/", views.resolution_history, name="history"),
    path("group/<uuid:pk>/", views.duplicate_group_detail, name="group_detail"),
    path("group/<uuid:pk>/resolve/", views.resolve_group, name="resolve"),
    path("group/<uuid:pk>/resolve-htmx/", views.resolve_group_htmx, name="resolve_htmx"),
    path("group/<uuid:pk>/comics/", views.group_comics_partial, name="group_comics"),
]
