from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Notification(models.Model):
    class Kind(models.TextChoices):
        MENTION = "mention", _("mentioned you")
        ASSIGNED = "assigned", _("assigned you")
        COMMENT = "comment", _("commented on")
        STATUS = "status", _("changed the status of")
        PAGE_MENTION = "page_mention", _("mentioned you on a page")

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    target_label = models.CharField(max_length=300)
    target_url = models.CharField(max_length=300)
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.actor} {self.kind} → {self.recipient}"
