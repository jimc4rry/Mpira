from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.api.urls")),
    path("", include("apps.core.urls")),
    path("projects/", include("apps.projects.urls")),
    path("projects/", include("apps.issues.urls")),
    path("projects/", include("apps.agile.urls")),
    path("projects/", include("apps.wiki.urls")),
    path("projects/", include("apps.testmgmt.urls")),
]

handler404 = "apps.core.views.error_404"
handler403 = "apps.core.views.error_403"
handler500 = "apps.core.views.error_500"
