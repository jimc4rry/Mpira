from django.contrib import admin

from .models import Page, PageVersion, Space


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ["title", "space", "version", "updated_at"]
    search_fields = ["title", "body"]


admin.site.register([Space, PageVersion])
