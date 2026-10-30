"""
Board column configuration.

Rules that keep the board honest:
- Every workflow status of the project belongs to exactly one column, so no
  issue can vanish. A new status lands in the last column until placed.
- A project always has at least one column.
- Removing a column moves its statuses to another column chosen by the user.
- Dropping a card on a column moves it to that column's first status, and
  the normal workflow check still applies.
"""

from django.db import transaction
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.issues import workflow
from apps.issues.models import Status

from .models import BoardColumn


class BoardError(Exception):
    pass


DEFAULT_COLUMNS = [
    (gettext_lazy("To Do"), [Status.TODO]),
    (gettext_lazy("In Progress"), [Status.IN_PROGRESS]),
    (gettext_lazy("In Review"), [Status.IN_REVIEW]),
    (gettext_lazy("Done"), [Status.DONE]),
]


@transaction.atomic
def ensure_columns(project):
    """
    Return the project's columns, creating the defaults the first time and
    keeping the status assignment in step with the workflow.
    """
    workflow.ensure_default(project)
    if not BoardColumn.objects.filter(project=project).exists():
        for position, (name, keys) in enumerate(DEFAULT_COLUMNS):
            BoardColumn.objects.create(
                project=project, name=str(name), position=position, statuses=[s.value for s in keys]
            )
    columns = list(BoardColumn.objects.filter(project=project))
    valid = set(workflow.status_map(project))
    assigned = set()
    for col in columns:
        kept = [k for k in col.statuses if k in valid and k not in assigned]
        if kept != list(col.statuses):
            col.statuses = kept
            col.save(update_fields=["statuses"])
        assigned.update(kept)
    missing = [s.key for s in workflow.statuses(project) if s.key not in assigned]
    if missing:
        last = columns[-1]
        last.statuses = list(last.statuses) + missing
        last.save(update_fields=["statuses"])
    return columns


def status_to_column(columns):
    return {status: col for col in columns for status in col.statuses}


def _renumber(columns):
    for position, col in enumerate(columns):
        if col.position != position:
            col.position = position
            col.save(update_fields=["position"])


@transaction.atomic
def add_column(project, name):
    name = (name or "").strip()
    if not name:
        raise BoardError(_("Give the column a name."))
    columns = ensure_columns(project)
    if any(c.name.lower() == name.lower() for c in columns):
        raise BoardError(_("A column with that name already exists."))
    return BoardColumn.objects.create(project=project, name=name, position=len(columns), statuses=[])


@transaction.atomic
def rename_column(column, name):
    name = (name or "").strip()
    if not name:
        raise BoardError(_("Give the column a name."))
    column.name = name
    column.save(update_fields=["name"])


@transaction.atomic
def move_column(column, direction):
    columns = list(BoardColumn.objects.filter(project=column.project))
    idx = columns.index(column)
    target = idx - 1 if direction == "up" else idx + 1
    if direction not in ("up", "down") or not 0 <= target < len(columns):
        return
    columns[idx], columns[target] = columns[target], columns[idx]
    _renumber(columns)


@transaction.atomic
def delete_column(column, move_to=None):
    columns = list(BoardColumn.objects.filter(project=column.project))
    if len(columns) <= 1:
        raise BoardError(_("A board needs at least one column."))
    if column.statuses:
        if move_to is None or move_to.pk == column.pk or move_to.project_id != column.project_id:
            raise BoardError(_("Choose another column to receive the statuses of this column."))
        move_to.statuses = list(move_to.statuses) + list(column.statuses)
        move_to.save(update_fields=["statuses"])
    column.delete()
    _renumber(list(BoardColumn.objects.filter(project=column.project)))


@transaction.atomic
def set_status_assignment(project, assignment):
    """`assignment` is {status_key: column_pk}; every status must be placed once."""
    columns = {c.pk: c for c in BoardColumn.objects.filter(project=project)}
    keys = list(workflow.status_map(project))
    if set(assignment) != set(keys):
        raise BoardError(_("Every status must be placed in a column."))
    for column_pk in assignment.values():
        if column_pk not in columns:
            raise BoardError(_("Unknown column."))
    for col in columns.values():
        col.statuses = [k for k in keys if assignment[k] == col.pk]
        col.save(update_fields=["statuses"])


@transaction.atomic
def place_status(project, key, column_pk):
    """Move one status (e.g. a newly added one) into the chosen column."""
    columns = ensure_columns(project)
    target = next((c for c in columns if c.pk == column_pk), None)
    if target is None:
        raise BoardError(_("Unknown column."))
    for col in columns:
        if key in col.statuses:
            col.statuses = [k for k in col.statuses if k != key]
            col.save(update_fields=["statuses"])
    target.statuses = list(target.statuses) + [key]
    target.save(update_fields=["statuses"])
