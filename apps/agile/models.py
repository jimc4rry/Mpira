from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.projects.models import Project


class Sprint(models.Model):
    class State(models.TextChoices):
        FUTURE = "future", _("Future")
        ACTIVE = "active", _("Active")
        CLOSED = "closed", _("Closed")

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="sprints")
    name = models.CharField(_("Name"), max_length=100)
    goal = models.TextField(_("Sprint goal"), blank=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.FUTURE)
    start_date = models.DateField(_("Start date"), null=True, blank=True)
    end_date = models.DateField(_("End date"), null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    # Frozen at start: {issue_id: story_points} - the burndown baseline.
    committed_scope = models.JSONField(default=dict, blank=True)
    # Frozen at completion: {issue_id: story_points} of everything that was in
    # the sprint, since incomplete issues move out and their FK changes.
    final_scope = models.JSONField(default=dict, blank=True)
    completed_points = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["project"],
                condition=models.Q(state="active"),
                name="one_active_sprint_per_project",
            )
        ]

    def __str__(self):
        return self.name

    @property
    def committed_points(self):
        return sum(int(p or 0) for p in self.committed_scope.values())

    @property
    def is_active(self):
        return self.state == self.State.ACTIVE


class BoardColumn(models.Model):
    """
    A column on the project's Kanban board. Columns group the fixed workflow
    statuses (see apps.issues.models.Status): each status belongs to exactly
    one column, so no issue can disappear from the board. The workflow itself
    (which status may follow which) is unchanged.
    """

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="board_columns")
    name = models.CharField(_("Name"), max_length=60)
    position = models.PositiveSmallIntegerField(default=0)
    statuses = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return f"{self.project.key}: {self.name}"

    @property
    def first_status(self):
        return self.statuses[0] if self.statuses else None
