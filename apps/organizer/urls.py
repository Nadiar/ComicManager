from django.urls import path
from . import views

app_name = "organizer"

urlpatterns = [
    # Profile CRUD
    path("profiles/", views.profile_list, name="profile_list"),
    path("profiles/create/", views.profile_create, name="profile_create"),
    path("profiles/<int:pk>/", views.profile_detail, name="profile_detail"),
    path("profiles/<int:pk>/edit/", views.profile_edit, name="profile_edit"),
    path("profiles/<int:pk>/delete/", views.profile_delete, name="profile_delete"),
    path("profiles/<int:pk>/duplicate/", views.profile_duplicate, name="profile_duplicate"),
    path("profiles/<int:pk>/toggle/", views.profile_toggle, name="profile_toggle"),
    path("profiles/reorder/", views.profile_reorder, name="profile_reorder"),

    # Import
    path("import/", views.import_view, name="import"),

    # Preview (for comics)
    path("preview/<uuid:pk>/", views.preview_view, name="preview"),

    # Path Audit
    path("path-audit/", views.path_audit, name="path_audit"),
    path("path-audit/start/", views.start_audit, name="start_audit"),
    path("path-audit/reorganize-all/", views.start_reorganize_all, name="start_reorganize_all"),
]
