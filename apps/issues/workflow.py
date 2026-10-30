"""
Per-project workflow: the statuses an issue can be in and how it may move.

Every project gets the four default statuses on first use (ensure_default);
admins can then add, rename and remove statuses and edit which status may
follow which. Lookups are cached on the Project instance for the duration of
a request, so the board or a list doesn't query per issue.
"""

from collections import namedtuple

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _

from .models import DEFAULT_TRANSITIONS, Activity, Issue, Status, WorkflowStatus

Choice = namedtuple("Choice", "value label")


class WorkflowError(Exception):
    pass


def _cache(project):
    cache = getattr(project, "_workflow_cache", None)
    if cache is None:
        cache = project._workflow_cache = {}
    return cache


def forget(project):
    """Drop cached lookups after the workflow changed."""
    if hasattr(project, "_workflow_cache"):
        del project._workflow_cache


@transaction.atomic
def ensure_default(project):
    if WorkflowStatus.objects.filter(project=project).exists():
        return
    created = {}
    names = {
        Status.TODO: _("To Do"),
        Status.IN_PROGRESS: _("In Progress"),
        Status.IN_REVIEW: _("In Review"),
        Status.DONE: _("Done"),
    }
    for position, status in enumerate(Status):
        created[status.value] = WorkflowStatus.objects.create(
            project=project,
            key=status.value,
            name=str(names[status]),
            position=position,
            is_initial=status == Status.TODO,
            counts_as_done=status == Status.DONE,
        )
    for source, targets in DEFAULT_TRANSITIONS.items():
        created[source.value].next_statuses.set([created[t.value] for t in targets])
    _add_canceled_row(project)
    forget(project)


CANCELED_KEY = "canceled"


def _add_canceled_row(project):
    """Creates the Canceled status once. It counts as done (it leaves the open lists) and is reachable both ways."""
    if WorkflowStatus.objects.filter(project=project, key=CANCELED_KEY).exists():
        return None
    others = list(WorkflowStatus.objects.filter(project=project))
    status = WorkflowStatus.objects.create(
        project=project,
        key=CANCELED_KEY,
        name=str(_("Canceled")),
        position=len(others),
        counts_as_done=True,
    )
    status.next_statuses.set(others)
    for other in others:
        other.next_statuses.add(status)
    return status


@transaction.atomic
def add_canceled(project):
    """For existing projects: adds the Canceled status if it is missing. Returns the status it created, or None."""
    ensure_default(project)
    status = _add_canceled_row(project)
    forget(project)
    return status


def statuses(project):
    """All statuses of the project, in board/workflow order."""
    cache = _cache(project)
    if "statuses" not in cache:
        ensure_default(project)
        cache["statuses"] = list(WorkflowStatus.objects.filter(project=project).prefetch_related("next_statuses"))
    return cache["statuses"]


def status_map(project):
    cache = _cache(project)
    if "map" not in cache:
        cache["map"] = {s.key: s for s in statuses(project)}
    return cache["map"]


def label(project, key):
    s = status_map(project).get(key)
    return s.name if s else key


def done_keys(project):
    cache = _cache(project)
    if "done" not in cache:
        cache["done"] = {s.key for s in statuses(project) if s.counts_as_done}
    return cache["done"]


def is_done_key(project, key):
    return key in done_keys(project)


def initial_key(project):
    for s in statuses(project):
        if s.is_initial:
            return s.key
    return statuses(project)[0].key


def transition_map(project):
    """{from_key: [to_key, ...]}"""
    cache = _cache(project)
    if "transitions" not in cache:
        cache["transitions"] = {s.key: [n.key for n in s.next_statuses.all()] for s in statuses(project)}
    return cache["transitions"]


def next_choices(project, key):
    names = status_map(project)
    return [Choice(k, names[k].name) for k in transition_map(project).get(key, []) if k in names]


def _slug_for(project, name):
    base = slugify(name)[:36] or "status"
    key, n = base, 2
    existing = {s.key for s in WorkflowStatus.objects.filter(project=project)}
    while key in existing:
        key = f"{base}-{n}"
        n += 1
    return key


@transaction.atomic
def add_status(project, name, *, counts_as_done=False):
    ensure_default(project)
    name = (name or "").strip()
    if not name:
        raise WorkflowError(_("Give the status a name."))
    if any(s.name.lower() == name.lower() for s in statuses(project)):
        raise WorkflowError(_("A status with that name already exists."))
    existing = statuses(project)
    status = WorkflowStatus.objects.create(
        project=project,
        key=_slug_for(project, name),
        name=name[:60],
        position=len(existing),
        counts_as_done=counts_as_done,
    )
    # New statuses are reachable from and can move to every other status by
    # default; the transition matrix refines this.
    others = list(WorkflowStatus.objects.filter(project=project).exclude(pk=status.pk))
    status.next_statuses.set(others)
    for other in others:
        other.next_statuses.add(status)
    forget(project)
    return status


@transaction.atomic
def update_status(status, *, name=None, counts_as_done=None, is_initial=None):
    project = status.project
    if name is not None:
        name = name.strip()
        if not name:
            raise WorkflowError(_("Give the status a name."))
        if any(s.pk != status.pk and s.name.lower() == name.lower() for s in statuses(project)):
            raise WorkflowError(_("A status with that name already exists."))
        status.name = name[:60]
    if counts_as_done is not None:
        if not counts_as_done and status.counts_as_done and len(done_keys(project)) <= 1:
            raise WorkflowError(_("At least one status must count as done."))
        status.counts_as_done = counts_as_done
    if is_initial:
        WorkflowStatus.objects.filter(project=project).exclude(pk=status.pk).update(is_initial=False)
        status.is_initial = True
    elif is_initial is False and status.is_initial:
        raise WorkflowError(_("Choose another initial status instead."))
    status.save()
    forget(project)
    return status


@transaction.atomic
def delete_status(status, move_to=None):
    project = status.project
    all_statuses = statuses(project)
    if len(all_statuses) <= 2:
        raise WorkflowError(_("A workflow needs at least two statuses."))
    if status.is_initial:
        raise WorkflowError(_("The initial status can't be deleted. Make another status initial first."))
    if status.counts_as_done and len([s for s in all_statuses if s.counts_as_done]) <= 1:
        raise WorkflowError(_("At least one status must count as done."))
    in_use = Issue.objects.filter(project=project, status=status.key)
    if in_use.exists():
        if move_to is None or move_to.pk == status.pk or move_to.project_id != project.pk:
            raise WorkflowError(_("Choose another status to move the issues of this status to."))
        moved = list(in_use.values_list("pk", flat=True))
        Activity.objects.bulk_create(
            [
                Activity(
                    issue_id=pk,
                    kind=Activity.Kind.FIELD,
                    field="status",
                    old_value=status.key,
                    new_value=move_to.key,
                )
                for pk in moved
            ]
        )
        in_use.update(status=move_to.key)
        if move_to.counts_as_done != status.counts_as_done:
            # Keep resolved_at consistent with the new status' done-ness.
            Issue.objects.filter(pk__in=moved).update(
                resolved_at=timezone.now() if move_to.counts_as_done else None
            )
    status.delete()
    forget(project)
    _renumber(project)


def _renumber(project):
    for position, s in enumerate(WorkflowStatus.objects.filter(project=project).order_by("position", "id")):
        if s.position != position:
            s.position = position
            s.save(update_fields=["position"])


@transaction.atomic
def save_transitions(project, allowed):
    """
    `allowed` is {from_key: set(to_keys)}. Self-loops are ignored. Every status
    needs at least one way out, otherwise issues could get stuck.
    """
    by_key = status_map(project)
    for source_key, targets in allowed.items():
        source = by_key.get(source_key)
        if source is None:
            raise WorkflowError(_("Unknown status."))
        chosen = [by_key[t] for t in targets if t in by_key and t != source_key]
        if not chosen:
            raise WorkflowError(_("%(name)s needs at least one status it can move to.") % {"name": source.name})
        source.next_statuses.set(chosen)
    forget(project)
