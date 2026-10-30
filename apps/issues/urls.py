from django.urls import path

from . import views

app_name = "issues"

P = "<str:key>/issues/<int:number>/"

urlpatterns = [
    path("<str:key>/issues/", views.issue_list, name="list"),
    path("<str:key>/workflow/", views.workflow_settings, name="workflow"),
    path("<str:key>/issues/new/", views.issue_create, name="create"),
    path("<str:key>/issues/import/", views.issue_import, name="import"),
    path("<str:key>/issues/export.csv", views.issue_export, name="export"),
    path("<str:key>/issues/bulk/", views.issues_bulk, name="bulk"),
    path(P + "inline/", views.issue_inline, name="inline"),
    path("<str:key>/filters/save/", views.filter_save, name="filter_save"),
    path("<str:key>/webhooks/", views.webhooks_page, name="webhooks"),
    path("<str:key>/automation/", views.automation_page, name="automation"),
    path("<str:key>/releases/", views.releases_page, name="releases"),
    path("<str:key>/timeline/", views.timeline_page, name="timeline"),
    path("<str:key>/releases/<int:pk>/notes/", views.release_notes, name="release_notes"),
    path("<str:key>/filters/<int:pk>/delete/", views.filter_delete, name="filter_delete"),
    path("<str:key>/issues/import/template.<str:fmt>", views.issue_import_template, name="import_template"),
    path(P, views.issue_detail, name="detail"),
    path(P + "edit/", views.issue_edit, name="edit"),
    path(P + "delete/", views.issue_delete, name="delete"),
    path(P + "transition/", views.issue_transition, name="transition"),
    path(P + "watch/", views.watch_toggle, name="watch"),
    path(P + "comments/", views.comment_add, name="comment_add"),
    path(P + "comments/<int:pk>/delete/", views.comment_delete, name="comment_delete"),
    path(P + "attachments/", views.attachment_upload, name="attachment_upload"),
    path(P + "attachments/<int:pk>/", views.attachment_download, name="attachment_download"),
    path(P + "attachments/<int:pk>/delete/", views.attachment_delete, name="attachment_delete"),
    path(P + "links/", views.link_add, name="link_add"),
    path(P + "links/<int:pk>/delete/", views.link_delete, name="link_delete"),
]
