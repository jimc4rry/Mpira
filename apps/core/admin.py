from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["recipient", "actor", "kind", "target_label", "is_read", "created_at"]
    list_filter = ["kind", "is_read"]
