from django.urls import path

from . import views

app_name = "agile"

urlpatterns = [
    path("<str:key>/board/", views.board, name="board"),
    path("<str:key>/backlog/", views.backlog, name="backlog"),
    path("<str:key>/board/settings/", views.board_settings, name="board_settings"),
    path("<str:key>/reports/", views.reports, name="reports"),
    path("<str:key>/sprints/new/", views.sprint_create, name="sprint_create"),
    path("<str:key>/sprints/<int:pk>/", views.sprint_edit, name="sprint_edit"),
    path("<str:key>/sprints/<int:pk>/start/", views.sprint_start, name="sprint_start"),
    path("<str:key>/sprints/<int:pk>/complete/", views.sprint_complete, name="sprint_complete"),
]
