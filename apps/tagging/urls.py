from django.urls import path
from . import views

app_name = "tagging"

urlpatterns = [
    # Ruleset CRUD
    path("rulesets/", views.ruleset_list, name="ruleset_list"),
    path("rulesets/create/", views.ruleset_create, name="ruleset_create"),
    path("rulesets/<int:pk>/", views.ruleset_detail, name="ruleset_detail"),
    path("rulesets/<int:pk>/edit/", views.ruleset_edit, name="ruleset_edit"),
    path("rulesets/<int:pk>/delete/", views.ruleset_delete, name="ruleset_delete"),
    path("rulesets/<int:pk>/duplicate/", views.ruleset_duplicate, name="ruleset_duplicate"),
    path("rulesets/<int:pk>/toggle/", views.ruleset_toggle, name="ruleset_toggle"),

    # Import/Export
    path("import/", views.import_datamanager, name="import"),
    path("export/", views.export_datamanager, name="export"),
]
