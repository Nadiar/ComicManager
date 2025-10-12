from django.urls import path
from . import views

app_name = "dashboard"
urlpatterns = [
    path("", views.index, name="index"),
    path("smartlists/", views.smartlist_index, name="smartlist_index"),
    path("smartlists/create/", views.smartlist_create, name="smartlist_create"),
    path("smartlists/cv-search/", views.smartlist_cv_search, name="smartlist_cv_search"),
    path("smartlists/<uuid:pk>/", views.smartlist_detail, name="smartlist_detail"),
    path("smartlists/<uuid:pk>/edit/", views.smartlist_edit, name="smartlist_edit"),
    path("smartlists/<uuid:pk>/delete/", views.smartlist_delete, name="smartlist_delete"),
    path("smartlists/<uuid:pk>/missing/", views.smartlist_missing, name="smartlist_missing"),
]
