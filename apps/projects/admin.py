from django.contrib import admin

from .models import Component, Label, Project, ProjectMembership, Version


class MembershipInline(admin.TabularInline):
    model = ProjectMembership
    extra = 0


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["key", "name", "lead", "is_archived", "created_at"]
    search_fields = ["key", "name"]
    inlines = [MembershipInline]


admin.site.register([Component, Version, Label])
