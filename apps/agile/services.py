"""
Sprint lifecycle, burndown and velocity.

Burndown model (kept intentionally simple and deterministic):
- Ideal line: committed points at start → 0, linear over the sprint's days.
- Actual line: for each day, the points of in-scope issues that were NOT in
  Done at the end of that day, reconstructed from the issue Activity log
  (status transitions), so it never depends on daily cron snapshots.
- Scope: the issues currently in the sprint (active) or the frozen
  `final_scope` (closed). Story points use the frozen values where available.
"""

import datetime

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.issues import workflow
from apps.issues.models import Activity, Issue

from .models import Sprint


class SprintError(Exception):
    pass


def _scope(sprint):
    return {str(i.pk): i.story_points or 0 for i in sprint.issues.all()}


@transaction.atomic
def start_sprint(sprint, start_date=None, end_date=None):
    if sprint.state != Sprint.State.FUTURE:
        raise SprintError(_("Only a future sprint can be started."))
    if Sprint.objects.filter(project=sprint.project, state=Sprint.State.ACTIVE).exists():
        raise SprintError(_("This project already has an active sprint."))
    if not sprint.issues.exists():
        raise SprintError(_("Add at least one issue to the sprint before starting it."))
    today = timezone.localdate()
    sprint.start_date = start_date or sprint.start_date or today
    sprint.end_date = end_date or sprint.end_date or sprint.start_date + datetime.timedelta(days=13)
    if sprint.end_date < sprint.start_date:
        raise SprintError(_("The end date must be after the start date."))
    sprint.state = Sprint.State.ACTIVE
    sprint.started_at = timezone.now()
    sprint.committed_scope = _scope(sprint)
    sprint.save()
    return sprint


@transaction.atomic
def complete_sprint(sprint, move_to=None):
    """
    Close the sprint. Done issues stay attached to it; everything else moves
    to `move_to` (another non-closed sprint of the same project) or the backlog.
    """
    if sprint.state != Sprint.State.ACTIVE:
        raise SprintError(_("Only the active sprint can be completed."))
    if move_to is not None and (
        move_to.project_id != sprint.project_id or move_to.state == Sprint.State.CLOSED or move_to.pk == sprint.pk
    ):
        raise SprintError(_("Incomplete issues can only move to an open sprint of the same project."))
    issues = list(sprint.issues.all())
    sprint.final_scope = {str(i.pk): i.story_points or 0 for i in issues}
    done = workflow.done_keys(sprint.project)
    sprint.completed_points = sum(i.story_points or 0 for i in issues if i.status in done)
    sprint.state = Sprint.State.CLOSED
    sprint.completed_at = timezone.now()
    sprint.save()
    incomplete = [i.pk for i in issues if i.status not in done]
    Issue.objects.filter(pk__in=incomplete).update(sprint=move_to)
    return len(incomplete)


def sprint_points(sprint):
    total = sprint.issues.aggregate(s=Sum("story_points"))["s"] or 0
    done = sprint.issues.filter(status__in=workflow.done_keys(sprint.project)).aggregate(s=Sum("story_points"))["s"] or 0
    return total, done


def burndown(sprint, today=None):
    """
    Returns {"days": [date...], "ideal": [float...], "actual": [int|None...],
    "committed": int, "scope": int}. `actual` is None for future days.
    """
    if not sprint.start_date or not sprint.end_date:
        return None
    today = today or timezone.localdate()
    if sprint.state == Sprint.State.CLOSED:
        scope = {int(k): int(v or 0) for k, v in sprint.final_scope.items()}
        last_day = timezone.localtime(sprint.completed_at).date() if sprint.completed_at else sprint.end_date
    else:
        scope = {i.pk: i.story_points or 0 for i in sprint.issues.all()}
        last_day = today

    committed = sprint.committed_points or sum(scope.values())
    days = []
    d = sprint.start_date
    while d <= sprint.end_date:
        days.append(d)
        d += datetime.timedelta(days=1)
    n = max(len(days) - 1, 1)
    ideal = [round(committed - committed * i / n, 1) for i in range(len(days))]

    done_keys = workflow.done_keys(sprint.project)
    # Status of each in-scope issue at end of day, from the transition log.
    transitions = {}
    for a in (
        Activity.objects.filter(issue_id__in=scope.keys(), kind=Activity.Kind.TRANSITION)
        .order_by("created_at", "id")
        .values("issue_id", "new_value", "created_at")
    ):
        transitions.setdefault(a["issue_id"], []).append((timezone.localtime(a["created_at"]).date(), a["new_value"]))
    initial = dict(Issue.objects.filter(pk__in=scope.keys()).values_list("pk", "created_at"))

    def status_at(issue_id, day):
        status = workflow.initial_key(sprint.project)
        for when, new in transitions.get(issue_id, []):
            if when <= day:
                status = new
            else:
                break
        return status

    actual = []
    for day in days:
        if day > last_day:
            actual.append(None)
            continue
        remaining = 0
        for issue_id, points in scope.items():
            created = initial.get(issue_id)
            if created and timezone.localtime(created).date() > day:
                continue
            if status_at(issue_id, day) not in done_keys:
                remaining += points
        actual.append(remaining)
    return {"days": days, "ideal": ideal, "actual": actual, "committed": committed, "scope": sum(scope.values())}


def velocity(project, limit=8):
    sprints = list(
        Sprint.objects.filter(project=project, state=Sprint.State.CLOSED).order_by("-completed_at")[:limit]
    )
    sprints.reverse()
    rows = [{"sprint": s, "committed": s.committed_points, "completed": s.completed_points} for s in sprints]
    average = round(sum(r["completed"] for r in rows) / len(rows), 1) if rows else 0
    return {"rows": rows, "average": average}


def chart_geometry(data, width=640, height=240, pad=36):
    """
    Pre-computes SVG polyline points so the template stays dumb. Returns
    None when there's nothing to draw.
    """
    if not data or not data["days"]:
        return None
    max_y = max([data["committed"], data["scope"]] + [a for a in data["actual"] if a is not None] + [1])
    n = max(len(data["days"]) - 1, 1)
    inner_w, inner_h = width - pad * 2, height - pad * 2

    def xy(i, v):
        return round(pad + inner_w * i / n, 1), round(pad + inner_h * (1 - v / max_y), 1)

    ideal = " ".join(f"{x},{y}" for x, y in (xy(i, v) for i, v in enumerate(data["ideal"])))
    actual_pts = [xy(i, v) for i, v in enumerate(data["actual"]) if v is not None]
    actual = " ".join(f"{x},{y}" for x, y in actual_pts)
    step = max(1, len(data["days"]) // 7)
    x_labels = [
        {"x": xy(i, 0)[0], "label": d.strftime("%d/%m")} for i, d in enumerate(data["days"]) if i % step == 0
    ]
    y_ticks = []
    for frac in (0, 0.25, 0.5, 0.75, 1):
        v = round(max_y * frac)
        y_ticks.append({"y": xy(0, v)[1], "label": v})
    return {
        "width": width,
        "height": height,
        "pad": pad,
        "ideal": ideal,
        "actual": actual,
        "dots": [{"x": x, "y": y} for x, y in actual_pts],
        "x_labels": x_labels,
        "y_ticks": y_ticks,
        "baseline_y": height - pad,
        "right_x": width - pad,
    }


def velocity_geometry(vel, width=640, height=240, pad=36):
    rows = vel["rows"]
    if not rows:
        return None
    max_y = max([max(r["committed"], r["completed"]) for r in rows] + [1])
    inner_w, inner_h = width - pad * 2, height - pad * 2
    group_w = inner_w / len(rows)
    bar_w = min(28, group_w / 3)
    bars = []
    for i, r in enumerate(rows):
        gx = pad + group_w * i + group_w / 2
        for offset, value, kind in ((-bar_w - 2, r["committed"], "committed"), (2, r["completed"], "completed")):
            h = inner_h * value / max_y
            bars.append(
                {"x": round(gx + offset, 1), "y": round(height - pad - h, 1), "w": round(bar_w, 1), "h": round(h, 1), "kind": kind, "value": value}
            )
    labels = [{"x": round(pad + group_w * i + group_w / 2, 1), "label": r["sprint"].name} for i, r in enumerate(rows)]
    return {"width": width, "height": height, "bars": bars, "labels": labels, "baseline_y": height - pad, "pad": pad, "right_x": width - pad}
