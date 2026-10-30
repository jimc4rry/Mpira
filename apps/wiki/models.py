from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.issues.models import Issue
from apps.projects.models import Project


class Space(models.Model):
    """One wiki space per project, created automatically with the project."""

    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="space")
    name = models.CharField(_("Name"), max_length=120)
    description = models.TextField(_("Description"), blank=True)

    def __str__(self):
        return self.name


class Page(models.Model):
    space = models.ForeignKey(Space, on_delete=models.CASCADE, related_name="pages")
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        verbose_name=_("Parent page"),
    )
    title = models.CharField(_("Title"), max_length=200)
    body = models.TextField(_("Content"), blank=True)
    version = models.PositiveIntegerField(default=1)
    position = models.PositiveIntegerField(default=0)
    # Issues referenced as [[KEY-123]] in the body - kept in sync on save so
    # an issue can list the wiki pages that mention it.
    linked_issues = models.ManyToManyField(Issue, blank=True, related_name="wiki_pages")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "title"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("wiki:page", args=[self.space.project.key, self.pk])

    def ancestors(self):
        chain, node = [], self.parent
        while node is not None:
            chain.append(node)
            node = node.parent
        return list(reversed(chain))

    def descendant_ids(self):
        ids, frontier = set(), [self.pk]
        while frontier:
            children = list(Page.objects.filter(parent_id__in=frontier).values_list("pk", flat=True))
            frontier = [c for c in children if c not in ids]
            ids.update(frontier)
        return ids


class PageVersion(models.Model):
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    change_note = models.CharField(_("Change note"), max_length=200, blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("page", "version")
        ordering = ["-version"]

    def __str__(self):
        return f"{self.page} v{self.version}"
