from django.contrib import admin

from .models import Activity, Attachment, Comment, CustomFieldDefinition, Issue, IssueLink


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = ["__str__", "project", "issue_type", "status", "priority", "assignee", "updated_at"]
    list_filter = ["project", "issue_type", "status", "priority"]
    search_fields = ["title", "description"]
    raw_id_fields = ["epic", "parent", "sprint", "assignee", "reporter"]


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ["issue", "actor", "kind", "field", "created_at"]
    list_filter = ["kind"]
    raw_id_fields = ["issue"]


admin.site.register([Comment, Attachment, IssueLink, CustomFieldDefinition])
