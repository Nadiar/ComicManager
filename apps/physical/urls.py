from django.urls import path
from . import views

app_name = "physical"

urlpatterns = [
    path("", views.index, name="index"),
    path("add/", views.add_physical, name="add"),
    path("import/", views.import_csv, name="import_csv"),
]
