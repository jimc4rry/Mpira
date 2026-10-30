"""Bulk actions on a list of issues: move, assign, set priority, or delete.

Each issue is changed in its own transaction, through the same services as a single change (workflow rules, activity
log, notifications). One issue that cannot change is reported and the others still change.
"""

from django.db import transaction
from django.utils.translation import gettext as _

from apps.projects.permissions import can

from . import services, workflow
from .models import Priority
from .workflow import WorkflowError

MAX_ISSUES = 200
ACTIONS = ("transition", "assign", "priority", "delete")


class BulkError(Exception):
    pass


def _check_value(project, action, value):
    if action == "transition":
        if value not in workflow.status_map(project):
            raise BulkError(_("Choose a status."))
    elif action == "assign":
        allowed = {"none"} | {str(m.pk) for m in project.members_qs()}
        if value not in allowed:
            raise BulkError(_("Choose a member of the project, or nobody."))
    elif action == "priority":
        if value not in Priority.values:
            raise BulkError(_("Choose a priority."))


def bulk_apply(project, user, issues, action, value=""):
    """Applies `action` to each issue. Returns (changed, [(issue key, reason)])."""
    if action not in ACTIONS:
        raise BulkError(_("Choose an action."))
    if len(issues) > MAX_ISSUES:
        raise BulkError(_("At most %(n)d issues at a time.") % {"n": MAX_ISSUES})
    if action == "delete" and not can(user, project, "delete_issues"):
        raise BulkError(_("You cannot delete issues in this project."))
    if action != "delete":
        _check_value(project, action, value)

    changed, failed = 0, []
    for issue in issues:
        try:
            with transaction.atomic():
                if action == "transition":
                    services.transition_issue(issue, user, value)
                elif action == "assign":
                    before = services.snapshot(issue)
                    issue.assignee = None if value == "none" else project.members_qs().get(pk=int(value))
                    issue.save(update_fields=["assignee", "updated_at"])
                    services.record_changes(issue, user, before)
                elif action == "priority":
                    before = services.snapshot(issue)
                    issue.priority = value
                    issue.save(update_fields=["priority", "updated_at"])
                    services.record_changes(issue, user, before)
                elif action == "delete":
                    issue.delete()
            changed += 1
        except WorkflowError as exc:
            failed.append((issue.key, str(exc)))
    return changed, failed
