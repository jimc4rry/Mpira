from django.urls import path

from . import views

app_name = "projects"

urlpatterns = [
    path("", views.project_list, name="list"),
    path("new/", views.project_create, name="create"),
    path("<str:key>/", views.project_detail, name="detail"),
    path("<str:key>/settings/", views.project_settings, name="settings"),
    path("<str:key>/delete/", views.project_delete, name="delete"),
    path("<str:key>/settings/members/add/", views.member_add, name="member_add"),
    path("<str:key>/settings/members/<int:pk>/", views.member_update, name="member_update"),
    path("<str:key>/settings/<str:kind>/new/", views.settings_item, name="settings_item_new"),
    path("<str:key>/settings/<str:kind>/<int:pk>/", views.settings_item, name="settings_item"),
]
