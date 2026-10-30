from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.db.models import F
from django.urls import reverse
from django.utils.translation import gettext_lazy as _


class ProjectRole(models.TextChoices):
    PROJECT_MANAGER = "pm", _("Project Manager")
    DEVELOPER = "developer", _("Developer")
    TESTER = "tester", _("Tester")
    VIEWER = "viewer", _("Viewer")


class Project(models.Model):
    key = models.CharField(
        _("Key"),
        max_length=10,
        unique=True,
        validators=[
            RegexValidator(
                r"^[A-Z][A-Z0-9]{1,9}$",
                _("2-10 uppercase letters/digits, starting with a letter (e.g. MPR)."),
            )
        ],
        help_text=_("Prefix for issue keys, e.g. MPR → MPR-42. Cannot be changed later."),
    )
    name = models.CharField(_("Name"), max_length=120)
    description = models.TextField(_("Description"), blank=True)
    lead = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="led_projects",
        verbose_name=_("Project lead"),
    )
    # Monotonic counter for issue numbers; incremented with an F() update
    # inside a transaction so two concurrent creates never get the same key.
    issue_counter = models.PositiveIntegerField(default=0, editable=False)
    is_archived = models.BooleanField(_("Archived"), default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.key} · {self.name}"

    def get_absolute_url(self):
        return reverse("projects:detail", args=[self.key])

    def next_issue_number(self):
        with transaction.atomic():
            Project.objects.filter(pk=self.pk).update(issue_counter=F("issue_counter") + 1)
            self.refresh_from_db(fields=["issue_counter"])
            return self.issue_counter

    def members_qs(self):
        from django.contrib.auth import get_user_model

        return get_user_model().objects.filter(
            project_memberships__project=self, is_active=True
        ).distinct()


class ProjectMembership(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="project_memberships"
    )
    role = models.CharField(_("Role"), max_length=20, choices=ProjectRole.choices)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("project", "user")
        ordering = ["user__first_name", "user__username"]

    def __str__(self):
        return f"{self.user} @ {self.project.key} ({self.role})"


class Component(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="components")
    name = models.CharField(_("Name"), max_length=80)
    description = models.CharField(_("Description"), max_length=255, blank=True)

    class Meta:
        unique_together = ("project", "name")
        ordering = ["name"]

    def __str__(self):
        return self.name


class Version(models.Model):
    class Status(models.TextChoices):
        UNRELEASED = "unreleased", _("Unreleased")
        RELEASED = "released", _("Released")
        ARCHIVED = "archived", _("Archived")

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="versions")
    name = models.CharField(_("Name"), max_length=80)
    description = models.CharField(_("Description"), max_length=255, blank=True)
    release_date = models.DateField(_("Release date"), null=True, blank=True)
    status = models.CharField(
        _("Status"), max_length=20, choices=Status.choices, default=Status.UNRELEASED
    )

    class Meta:
        unique_together = ("project", "name")
        ordering = ["release_date", "name"]

    def __str__(self):
        return self.name


class Label(models.Model):
    """Project-scoped so two teams don't share (and fight over) one label namespace."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="labels")
    name = models.CharField(_("Name"), max_length=50)
    color = models.CharField(_("Color"), max_length=7, default="#3b82f6")

    class Meta:
        unique_together = ("project", "name")
        ordering = ["name"]

    def __str__(self):
        return self.name
