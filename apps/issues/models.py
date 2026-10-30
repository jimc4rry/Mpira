import os

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.projects.models import Component, Label, Project, Version


class IssueType(models.TextChoices):
    EPIC = "epic", _("Epic")
    STORY = "story", _("Story")
    TASK = "task", _("Task")
    BUG = "bug", _("Bug")
    SUBTASK = "subtask", _("Sub-task")
    TEST = "test", _("Test")


# Issue types a Test can cover - see apps.testmgmt coverage report.
REQUIREMENT_TYPES = {IssueType.STORY, IssueType.TASK, IssueType.BUG, IssueType.EPIC}
# Issue types that show up as cards on the agile boards.
BOARD_TYPES = {IssueType.STORY, IssueType.TASK, IssueType.BUG, IssueType.SUBTASK, IssueType.TEST}


class Status(models.TextChoices):
    """
    The four default workflow statuses. Every project starts with these (see
    apps.issues.workflow.ensure_default); projects can add more. Issue.status
    stores the status *key*, which for these defaults equals the value here.
    """

    TODO = "todo", _("To Do")
    IN_PROGRESS = "in_progress", _("In Progress")
    IN_REVIEW = "in_review", _("In Review")
    DONE = "done", _("Done")


# Default transitions copied into each new project's workflow.
DEFAULT_TRANSITIONS = {
    Status.TODO: [Status.IN_PROGRESS],
    Status.IN_PROGRESS: [Status.TODO, Status.IN_REVIEW],
    Status.IN_REVIEW: [Status.IN_PROGRESS, Status.DONE],
    Status.DONE: [Status.TODO, Status.IN_PROGRESS],
}


class WorkflowStatus(models.Model):
    """One status in a project's workflow, with the statuses it may move to."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="workflow_statuses")
    key = models.CharField(max_length=40)
    name = models.CharField(_("Name"), max_length=60)
    position = models.PositiveSmallIntegerField(default=0)
    # New issues start here.
    is_initial = models.BooleanField(_("Initial"), default=False)
    # Issues in a done status are resolved, leave open counts, and burn down.
    counts_as_done = models.BooleanField(_("Counts as done"), default=False)
    next_statuses = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="previous_statuses"
    )

    class Meta:
        ordering = ["position", "id"]
        unique_together = ("project", "key")

    def __str__(self):
        return f"{self.project.key}: {self.name}"


class Priority(models.TextChoices):
    HIGHEST = "highest", _("Highest")
    HIGH = "high", _("High")
    MEDIUM = "medium", _("Medium")
    LOW = "low", _("Low")
    LOWEST = "lowest", _("Lowest")


PRIORITY_ORDER = {p: i for i, p in enumerate(Priority.values)}


class CustomFieldDefinition(models.Model):
    """
    A project-level extra field, optionally limited to one issue type.
    Values live in Issue.custom_fields (JSON, keyed by `key`) and are
    validated by apps.issues.custom_fields for both the HTML forms and the API.
    """

    class FieldType(models.TextChoices):
        TEXT = "text", _("Text")
        NUMBER = "number", _("Number")
        DATE = "date", _("Date")
        SELECT = "select", _("Select")
        CHECKBOX = "checkbox", _("Checkbox")

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="custom_fields")
    issue_type = models.CharField(
        _("Issue type"),
        max_length=20,
        choices=IssueType.choices,
        blank=True,
        help_text=_("Leave empty to apply to every issue type."),
    )
    name = models.CharField(_("Name"), max_length=80)
    key = models.SlugField(_("Key"), max_length=40)
    field_type = models.CharField(_("Field type"), max_length=20, choices=FieldType.choices)
    options = models.CharField(
        _("Options"), max_length=500, blank=True, help_text=_("Comma-separated, for Select fields.")
    )
    required = models.BooleanField(_("Required"), default=False)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = ("project", "key")
        ordering = ["position", "name"]

    def __str__(self):
        return self.name

    @property
    def option_list(self):
        return [o.strip() for o in self.options.split(",") if o.strip()]


class Issue(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="issues")
    number = models.PositiveIntegerField(editable=False)
    issue_type = models.CharField(
        _("Type"), max_length=20, choices=IssueType.choices, default=IssueType.TASK
    )
    title = models.CharField(_("Summary"), max_length=255)
    description = models.TextField(_("Description"), blank=True)
    # A key of WorkflowStatus for this project (see apps.issues.workflow).
    status = models.CharField(_("Status"), max_length=40, default=Status.TODO)
    priority = models.CharField(
        _("Priority"), max_length=20, choices=Priority.choices, default=Priority.MEDIUM
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="reported_issues",
        verbose_name=_("Reporter"),
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_issues",
        verbose_name=_("Assignee"),
    )
    epic = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="epic_children",
        limit_choices_to={"issue_type": IssueType.EPIC},
        verbose_name=_("Epic"),
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="subtasks",
        verbose_name=_("Parent"),
    )
    sprint = models.ForeignKey(
        "agile.Sprint",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issues",
        verbose_name=_("Sprint"),
    )
    story_points = models.PositiveSmallIntegerField(_("Story points"), null=True, blank=True)
    labels = models.ManyToManyField(Label, blank=True, related_name="issues", verbose_name=_("Labels"))
    components = models.ManyToManyField(
        Component, blank=True, related_name="issues", verbose_name=_("Components")
    )
    fix_versions = models.ManyToManyField(
        Version, blank=True, related_name="issues", verbose_name=_("Fix versions")
    )
    watchers = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="watched_issues"
    )
    start_date = models.DateField(_("Start date"), null=True, blank=True)
    due_date = models.DateField(_("Due date"), null=True, blank=True)
    custom_fields = models.JSONField(default=dict, blank=True)
    # Ordering on boards/backlog; floats so a drop between two cards is one UPDATE.
    rank = models.FloatField(default=0, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("project", "number")
        ordering = ["rank", "id"]
        indexes = [models.Index(fields=["project", "status"]), models.Index(fields=["project", "issue_type"])]

    def __str__(self):
        return f"{self.key} {self.title}"

    @property
    def key(self):
        return f"{self.project.key}-{self.number}"

    def get_absolute_url(self):
        return reverse("issues:detail", args=[self.project.key, self.number])

    @property
    def allowed_transitions(self):
        """Choices (value, label) this issue may move to next."""
        from . import workflow

        return workflow.next_choices(self.project, self.status)

    @property
    def is_done(self):
        from . import workflow

        return workflow.is_done_key(self.project, self.status)

    def get_status_display(self):
        from . import workflow

        return workflow.label(self.project, self.status)


class Comment(models.Model):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    body = models.TextField(_("Comment"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment by {self.author} on {self.issue.key}"


def attachment_upload_to(instance, filename):
    return f"attachments/{instance.issue.project.key}/{instance.issue.number}/{filename}"


class Attachment(models.Model):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=attachment_upload_to)
    filename = models.CharField(max_length=255)
    size = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.filename

    def delete(self, *args, **kwargs):
        storage, name = self.file.storage, self.file.name
        super().delete(*args, **kwargs)
        if name and storage.exists(name):
            storage.delete(name)

    @property
    def extension(self):
        return os.path.splitext(self.filename)[1].lower().lstrip(".")


class IssueLink(models.Model):
    class LinkType(models.TextChoices):
        BLOCKS = "blocks", _("blocks")
        RELATES = "relates", _("relates to")
        DUPLICATES = "duplicates", _("duplicates")
        TESTS = "tests", _("tests")

    # The reverse ("inward") phrase shown on the target issue.
    INWARD = {
        LinkType.BLOCKS: _("is blocked by"),
        LinkType.RELATES: _("relates to"),
        LinkType.DUPLICATES: _("is duplicated by"),
        LinkType.TESTS: _("is tested by"),
    }

    source = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="outward_links")
    target = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="inward_links")
    link_type = models.CharField(_("Link type"), max_length=20, choices=LinkType.choices)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("source", "target", "link_type")

    def __str__(self):
        return f"{self.source.key} {self.link_type} {self.target.key}"

    @property
    def inward_label(self):
        return self.INWARD[self.LinkType(self.link_type)]


class Activity(models.Model):
    """
    Append-only history of everything that happens to an issue. Also the data
    source for the sprint burndown (status transitions over time).
    """

    class Kind(models.TextChoices):
        CREATED = "created", _("created the issue")
        FIELD = "field", _("changed")
        TRANSITION = "transition", _("changed the status")
        COMMENT = "comment", _("commented")
        ATTACHMENT = "attachment", _("attached a file")
        LINK = "link", _("linked an issue")

    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="activity")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    field = models.CharField(max_length=50, blank=True)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name_plural = "activities"

    def __str__(self):
        return f"{self.issue.key}: {self.kind} {self.field}"

    def display(self, value):
        """Human text for a stored value of this activity's field."""
        if not value:
            return "—"
        if self.field == "status":
            from . import workflow

            return workflow.label(self.issue.project, value)
        enums = {"issue_type": IssueType, "priority": Priority}
        if self.field in enums:
            try:
                return enums[self.field](value).label
            except ValueError:
                return value
        return value

    @property
    def old_display(self):
        return self.display(self.old_value)

    @property
    def new_display(self):
        return self.display(self.new_value)


class SavedFilter(models.Model):
    """A named set of issue-list filters. Private ones belong to their owner; shared ones show to the whole project."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="saved_filters")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_filters")
    name = models.CharField(_("Name"), max_length=80)
    query = models.CharField(_("Filters"), max_length=500)
    shared = models.BooleanField(_("Shared with the project"), default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("project", "owner", "name")
        ordering = ["name"]

    def __str__(self):
        return self.name


class Webhook(models.Model):
    """An https address that receives a signed JSON POST when issues of the project change."""

    class Event(models.TextChoices):
        CREATED = "issue.created", _("Issue created")
        TRANSITIONED = "issue.transitioned", _("Issue moved to another status")
        COMMENTED = "issue.commented", _("Comment added")

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="webhooks")
    url = models.URLField(_("Address"), max_length=300)
    secret = models.CharField(_("Signing secret"), max_length=64)
    events = models.CharField(_("Events"), max_length=200, help_text="comma-separated Event values")
    active = models.BooleanField(_("Active"), default=True)
    last_status = models.IntegerField(_("Last HTTP status"), null=True, blank=True)
    last_error = models.CharField(_("Last error"), max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["url"]

    def __str__(self):
        return self.url

    @property
    def event_list(self):
        return [e for e in self.events.split(",") if e]


class Rule(models.Model):
    """An automation rule: when a trigger happens and the condition matches, do one action on the issue."""

    class Trigger(models.TextChoices):
        CREATED = "issue.created", _("Issue created")
        TRANSITIONED = "issue.transitioned", _("Issue moved to another status")
        COMMENTED = "issue.commented", _("Comment added")
        SCHEDULED = "schedule.daily", _("Every day, for the issues the condition matches")

    class Action(models.TextChoices):
        SET_STATUS = "set_status", _("Move to status")
        SET_PRIORITY = "set_priority", _("Set priority")
        ASSIGN = "assign", _("Assign to (member id, or none)")
        COMMENT = "comment", _("Add a comment")

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="automation_rules")
    name = models.CharField(_("Name"), max_length=80)
    enabled = models.BooleanField(_("Enabled"), default=True)
    trigger = models.CharField(_("When"), max_length=30, choices=Trigger.choices)
    condition = models.CharField(_("If (query)"), max_length=500, blank=True,
                                 help_text=_("A query in the list's language, for example type = bug. Empty means always."))
    action = models.CharField(_("Then"), max_length=20, choices=Action.choices)
    value = models.CharField(_("Value"), max_length=500, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="automation_rules")
    last_error = models.CharField(_("Last error"), max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
