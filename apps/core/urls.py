from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    path("", views.comic_list, name="list"),
    path("convert-all/", views.convert_all_cbr, name="convert_all"),
    path("accept-all/", views.accept_all_comics, name="accept_all"),
    path("scrape-all/", views.scrape_all_comics, name="scrape_all"),
    path("tag-all/", views.tag_all_comics, name="tag_all"),
    path("deduplicate-all/", views.deduplicate_all_comics, name="deduplicate_all"),
    path("organize-all/", views.organize_all_comics, name="organize_all"),
    path("write-all/", views.write_all_comics, name="write_all"),
    path("<uuid:pk>/", views.comic_detail, name="detail"),
    path("<uuid:pk>/edit/", views.comic_edit, name="edit"),
    path("<uuid:pk>/cover/", views.comic_cover, name="cover"),
    path("<uuid:pk>/convert/", views.convert_cbr, name="convert"),
    path("<uuid:pk>/accept/", views.accept_comic, name="accept"),
    path("<uuid:pk>/scrape/", views.scrape_comic, name="scrape"),
    path("<uuid:pk>/scrape/preview/", views.scrape_preview, name="scrape_preview"),
    path("<uuid:pk>/tag/", views.tag_comic, name="tag"),
]
