"""The issue filters of the list page, shared by the list, the CSV export and the saved filters.

A filter set is a query string (`?type=bug&status=open&…`), so a saved filter is just the query string plus a name.
Unknown or malformed values are ignored, never an error: the same rules as the list page.
"""

from django.db.models import Q

from . import workflow

SORTS = {
    "updated": "-updated_at",
    "created": "-created_at",
    "key": "number",
    "priority": "priority",
    "status": "status",
}
# Keys a saved filter may carry. Anything else in a query string is dropped when it is saved.
FILTER_KEYS = ("q", "jql", "type", "status", "priority", "assignee", "label", "component", "version", "epic", "sort")


def apply_issue_filters(project, qs, params, user):
    """Narrow and order `qs` (issues of `project`) with the query parameters in `params`."""
    if params.get("q"):
        q = params["q"].strip()
        cond = Q(title__icontains=q) | Q(description__icontains=q)
        if q.isdigit():
            cond |= Q(number=int(q))
        qs = qs.filter(cond)
    if params.get("type"):
        qs = qs.filter(issue_type=params["type"])
    if params.get("status") == "open":
        qs = qs.exclude(status__in=workflow.done_keys(project))
    elif params.get("status"):
        qs = qs.filter(status=params["status"])
    if params.get("priority"):
        qs = qs.filter(priority=params["priority"])
    if params.get("assignee") == "me":
        qs = qs.filter(assignee=user)
    elif params.get("assignee") == "none":
        qs = qs.filter(assignee__isnull=True)
    elif (params.get("assignee") or "").isdigit():
        qs = qs.filter(assignee_id=int(params["assignee"]))
    if (params.get("label") or "").isdigit():
        qs = qs.filter(labels__id=int(params["label"]))
    if (params.get("component") or "").isdigit():
        qs = qs.filter(components__id=int(params["component"]))
    if (params.get("version") or "").isdigit():
        qs = qs.filter(fix_versions__id=int(params["version"]))
    if (params.get("epic") or "").isdigit():
        qs = qs.filter(epic__number=int(params["epic"]))
    return qs.order_by(SORTS.get(params.get("sort"), "-updated_at"), "-id").distinct()


def clean_query(params):
    """The part of a query string that a saved filter keeps: only known keys, with non-empty values."""
    return {key: params[key] for key in FILTER_KEYS if params.get(key)}


def apply_jql(qs, text, project, user):
    """Narrows `qs` with a query-language text (see query.py). Raises QueryError with a message for the user."""
    from .query import parse

    q, order = parse(text, project, user)
    qs = qs.filter(q)
    return qs.order_by(*order).distinct() if order else qs
