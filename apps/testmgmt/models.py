from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy

from apps.issues.models import Issue, IssueType
from apps.projects.models import Project, Version


class TestStep(models.Model):
    """Manual steps of a Test issue (issue_type == test)."""

    test = models.ForeignKey(
        Issue,
        on_delete=models.CASCADE,
        related_name="test_steps",
        limit_choices_to={"issue_type": IssueType.TEST},
    )
    order = models.PositiveSmallIntegerField(default=0)
    action = models.TextField(_("Action"))
    data = models.TextField(_("Test data"), blank=True)
    expected_result = models.TextField(_("Expected result"), blank=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.test.key} step {self.order}"


class TestPlan(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="test_plans")
    name = models.CharField(_("Name"), max_length=200)
    description = models.TextField(_("Description"), blank=True)
    fix_version = models.ForeignKey(
        Version, on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("Version")
    )
    tests = models.ManyToManyField(
        Issue,
        blank=True,
        related_name="test_plans",
        limit_choices_to={"issue_type": IssueType.TEST},
        verbose_name=_("Tests"),
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("testmgmt:plan_detail", args=[self.project.key, self.pk])


class RunStatus(models.TextChoices):
    TODO = "todo", pgettext_lazy("test run", "To Do")
    PASS = "pass", _("Pass")
    FAIL = "fail", _("Fail")
    BLOCKED = "blocked", _("Blocked")
    # Not executed by design: a manual test, a missing precondition, or not applicable.
    SKIPPED = "skipped", _("Skipped")
    NA = "na", _("N/A")


class RunState(models.TextChoices):
    """Whether an automated runner should pick the execution up (see the Mpira API)."""

    IDLE = "idle", _("Idle")
    QUEUED = "queued", _("Queued")
    RUNNING = "running", _("Running")
    DONE = "done", _("Done")


class TestExecution(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="test_executions")
    plan = models.ForeignKey(
        TestPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="executions",
        verbose_name=_("Test plan"),
    )
    name = models.CharField(_("Name"), max_length=200)
    environment = models.CharField(_("Environment"), max_length=100, blank=True)
    fix_version = models.ForeignKey(
        Version, on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("Version")
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    run_state = models.CharField(_("Automated run"), max_length=10, choices=RunState.choices, default=RunState.IDLE)
    run_requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    run_requested_at = models.DateTimeField(null=True, blank=True)
    run_finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("testmgmt:execution_detail", args=[self.project.key, self.pk])

    def summary(self):
        counts = {s: 0 for s in RunStatus.values}
        for status in self.runs.values_list("status", flat=True):
            counts[status] += 1
        total = sum(counts.values())
        counts["total"] = total
        counts["executed"] = total - counts[RunStatus.TODO]
        counts["percent_pass"] = round(100 * counts[RunStatus.PASS] / total) if total else 0
        return counts


class TestRun(models.Model):
    execution = models.ForeignKey(TestExecution, on_delete=models.CASCADE, related_name="runs")
    test = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="test_runs")
    status = models.CharField(
        _("Status"), max_length=10, choices=RunStatus.choices, default=RunStatus.TODO
    )
    comment = models.TextField(_("Comment"), blank=True)
    executed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    executed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("execution", "test")
        ordering = ["test__number"]

    def __str__(self):
        return f"{self.test.key} in {self.execution}: {self.status}"
