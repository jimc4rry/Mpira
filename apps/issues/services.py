"""
Every write to an Issue goes through here (HTML views and the REST API alike)
so the activity log, workflow rules and notifications stay consistent.
"""

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import Notification
from apps.core.notifications import mentioned_users, notify
from apps.projects.permissions import can

from . import workflow
from .models import Activity, Comment, Issue, IssueLink, IssueType
from .webhooks import emit, issue_payload
from .workflow import WorkflowError

RANK_STEP = 1000.0

TRACKED_FIELDS = [
    "title",
    "description",
    "issue_type",
    "priority",
    "assignee",
    "epic",
    "parent",
    "sprint",
    "story_points",
    "due_date",
]
TRACKED_M2M = ["labels", "components", "fix_versions"]



def _value(issue, field):
    value = getattr(issue, field)
    if value is None:
        return ""
    if hasattr(value, "pk"):
        return getattr(value, "key", None) if isinstance(value, Issue) else str(value)
    return str(value)


def snapshot(issue):
    """Display values of every tracked field, for diffing after an edit."""
    data = {f: _value(issue, f) for f in TRACKED_FIELDS}
    data["custom_fields"] = dict(issue.custom_fields or {})
    if issue.pk:
        for f in TRACKED_M2M:
            data[f] = ", ".join(sorted(str(o) for o in getattr(issue, f).all()))
    return data


def _visible_to(users, project):
    return [u for u in users if can(u, project, "view")]


def next_rank(project):
    top = Issue.objects.filter(project=project).aggregate(m=Max("rank"))["m"]
    return (top or 0) + RANK_STEP


def prepare_new_issue(issue, project, reporter):
    issue.project = project
    issue.reporter = reporter
    issue.number = project.next_issue_number()
    issue.rank = next_rank(project)
    issue.status = workflow.initial_key(project)
    if issue.issue_type != IssueType.SUBTASK:
        issue.parent = None


def after_create(issue, user):
    Activity.objects.create(issue=issue, actor=user, kind=Activity.Kind.CREATED)
    issue.watchers.add(user)
    if issue.assignee_id:
        issue.watchers.add(issue.assignee)
        if issue.assignee_id != user.pk:
            notify([issue.assignee], user, Notification.Kind.ASSIGNED, str(issue), issue.get_absolute_url())
    _notify_mentions(issue, user, issue.description)
    emit(issue.project, "issue.created", issue_payload(issue))
    from .automation import run as run_automation

    run_automation(issue, "issue.created", user)


@transaction.atomic
def create_issue(project, user, *, labels=(), components=(), fix_versions=(), **fields):
    issue = Issue(**fields)
    prepare_new_issue(issue, project, user)
    issue.save()
    issue.labels.set(labels)
    issue.components.set(components)
    issue.fix_versions.set(fix_versions)
    after_create(issue, user)
    return issue


def record_changes(issue, user, before):
    """Write one Activity row per changed field, and fire notifications."""
    after = snapshot(issue)
    rows = []
    for field, old in before.items():
        new = after.get(field)
        if field == "custom_fields":
            for key in sorted(set(old) | set(new)):
                if old.get(key) != new.get(key):
                    rows.append(
                        Activity(
                            issue=issue,
                            actor=user,
                            kind=Activity.Kind.FIELD,
                            field=f"cf:{key}",
                            old_value="" if old.get(key) is None else str(old.get(key)),
                            new_value="" if new.get(key) is None else str(new.get(key)),
                        )
                    )
            continue
        if old != new:
            rows.append(
                Activity(
                    issue=issue,
                    actor=user,
                    kind=Activity.Kind.FIELD,
                    field=field,
                    old_value=old if field != "description" else "",
                    new_value=new if field != "description" else "",
                )
            )
    Activity.objects.bulk_create(rows)

    if before.get("assignee") != after.get("assignee") and issue.assignee_id:
        issue.watchers.add(issue.assignee)
        notify([issue.assignee], user, Notification.Kind.ASSIGNED, str(issue), issue.get_absolute_url())
    if before.get("description") != after.get("description"):
        _notify_mentions(issue, user, issue.description, old_text=before.get("description", ""))
    return rows


def _notify_mentions(issue, user, text, old_text=""):
    users = _visible_to(mentioned_users(text, old_text), issue.project)
    for u in users:
        issue.watchers.add(u)
    notify(users, user, Notification.Kind.MENTION, str(issue), issue.get_absolute_url())


@transaction.atomic
def transition_issue(issue, user, new_status):
    statuses = workflow.status_map(issue.project)
    if new_status not in statuses:
        raise WorkflowError(_("Unknown status."))
    old_key = issue.status
    if new_status == old_key:
        return issue
    if new_status not in workflow.transition_map(issue.project).get(old_key, []):
        raise WorkflowError(
            _("Cannot move from %(old)s to %(new)s.")
            % {"old": workflow.label(issue.project, old_key), "new": statuses[new_status].name}
        )
    issue.status = new_status
    issue.resolved_at = timezone.now() if workflow.is_done_key(issue.project, new_status) else None
    issue.save(update_fields=["status", "resolved_at", "updated_at"])
    Activity.objects.create(
        issue=issue,
        actor=user,
        kind=Activity.Kind.TRANSITION,
        field="status",
        old_value=old_key,
        new_value=new_status,
    )
    notify(issue.watchers.all(), user, Notification.Kind.STATUS, str(issue), issue.get_absolute_url())
    emit(issue.project, "issue.transitioned", {**issue_payload(issue), "from": old_key})
    from .automation import run as run_automation

    run_automation(issue, "issue.transitioned", user)
    return issue


def rank_between(before, after):
    """Rank for an item dropped between `before` (above) and `after` (below)."""
    if before is not None and after is not None:
        return (before.rank + after.rank) / 2
    if before is not None:
        return before.rank + RANK_STEP
    if after is not None:
        return after.rank - RANK_STEP
    return None


@transaction.atomic
def move_issue(issue, user, *, status=None, before=None, after=None, sprint=...):
    """
    Board / backlog drag & drop: optional status transition (workflow-checked),
    optional sprint change, and a new rank between two neighbours.
    """
    if status is not None and status != issue.status:
        transition_issue(issue, user, status)
    if sprint is not ...:
        before_snapshot = snapshot(issue)
        issue.sprint = sprint
        issue.save(update_fields=["sprint", "updated_at"])
        record_changes(issue, user, before_snapshot)
    new_rank = rank_between(before, after)
    if new_rank is not None:
        issue.rank = new_rank
        issue.save(update_fields=["rank"])
    return issue


@transaction.atomic
def add_comment(issue, user, body):
    comment = Comment.objects.create(issue=issue, author=user, body=body)
    Activity.objects.create(issue=issue, actor=user, kind=Activity.Kind.COMMENT, new_value=body[:200])
    mentioned = _visible_to(mentioned_users(body), issue.project)
    for u in mentioned:
        issue.watchers.add(u)
    notify(mentioned, user, Notification.Kind.MENTION, str(issue), issue.get_absolute_url())
    others = [w for w in issue.watchers.all() if w not in mentioned]
    notify(others, user, Notification.Kind.COMMENT, str(issue), issue.get_absolute_url())
    issue.watchers.add(user)
    emit(issue.project, "issue.commented", {**issue_payload(issue), "comment": body[:500]})
    from .automation import run as run_automation

    run_automation(issue, "issue.commented", user)
    return comment


def link_issues(source, target, link_type, user):
    if source.pk == target.pk:
        raise WorkflowError(_("An issue cannot be linked to itself."))
    if link_type == IssueLink.LinkType.TESTS and source.issue_type != IssueType.TEST:
        raise WorkflowError(_("Only Test issues can use the 'tests' link."))
    link, created = IssueLink.objects.get_or_create(
        source=source, target=target, link_type=link_type, defaults={"created_by": user}
    )
    if created:
        Activity.objects.create(
            issue=source,
            actor=user,
            kind=Activity.Kind.LINK,
            field=link_type,
            new_value=target.key,
        )
    return link
