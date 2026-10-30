from django.urls import path

from . import views

app_name = "wiki"

urlpatterns = [
    path("<str:key>/wiki/", views.space_home, name="home"),
    path("<str:key>/wiki/new/", views.page_create, name="page_create"),
    path("<str:key>/wiki/<int:pk>/", views.page_detail, name="page"),
    path("<str:key>/wiki/<int:pk>/edit/", views.page_edit, name="page_edit"),
    path("<str:key>/wiki/<int:pk>/delete/", views.page_delete, name="page_delete"),
    path("<str:key>/wiki/<int:pk>/history/", views.page_history, name="page_history"),
    path("<str:key>/wiki/<int:pk>/v/<int:version>/", views.page_version, name="page_version"),
    path("<str:key>/wiki/<int:pk>/v/<int:version>/restore/", views.page_restore, name="page_restore"),
]
