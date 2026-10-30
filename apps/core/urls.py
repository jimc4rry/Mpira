from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("healthz", views.healthz, name="healthz"),
    path("favicon.ico", views.favicon, name="favicon"),
    path("search/", views.search, name="search"),
    path("help/", views.help_page, name="help"),
    path("notifications/", views.notifications, name="notifications"),
    path("notifications/read-all/", views.notifications_mark_all, name="notifications_mark_all"),
    path("notifications/<int:pk>/", views.notification_open, name="notification_open"),
]
