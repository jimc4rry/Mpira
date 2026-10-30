from django.contrib import admin

from .models import Sprint


@admin.register(Sprint)
class SprintAdmin(admin.ModelAdmin):
    list_display = ["name", "project", "state", "start_date", "end_date", "completed_points"]
    list_filter = ["project", "state"]
