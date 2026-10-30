import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.issues import workflow
from apps.issues.models import BOARD_TYPES, IssueType
from apps.projects.permissions import can, get_project_or_404
from apps.projects.views import project_context

from . import board as board_service
from . import services
from .forms import SprintForm, StartSprintForm
from .models import BoardColumn, Sprint

BOARD_DONE_WINDOW_DAYS = 14


def _card_qs(project):
    return project.issues.filter(issue_type__in=BOARD_TYPES).select_related(
        "assignee", "epic", "project", "parent"
    ).prefetch_related("labels")


@login_required
def board(request, key):
    project = get_project_or_404(request.user, key)
    active = project.sprints.filter(state=Sprint.State.ACTIVE).first()
    scope = request.GET.get("scope") or ("sprint" if active else "all")
    issues = _card_qs(project)
    if scope == "sprint" and active:
        issues = issues.filter(sprint=active)
    else:
        scope = "all"
        cutoff = timezone.now() - datetime.timedelta(days=BOARD_DONE_WINDOW_DAYS)
        issues = issues.filter(~Q(status__in=workflow.done_keys(project)) | Q(resolved_at__gte=cutoff))
    issues = list(issues.order_by("rank", "id"))
    board_columns = board_service.ensure_columns(project)

    def build_columns(subset):
        built = []
        for col in board_columns:
            col_issues = [i for i in subset if i.status in col.statuses]
            built.append(
                {
                    "pk": col.pk,
                    "label": col.name,
                    # Cards dropped here become this status; empty columns take no drops.
                    "status": col.first_status or "",
                    "statuses": col.statuses,
                    "issues": col_issues,
                    "points": sum(i.story_points or 0 for i in col_issues),
                }
            )
        return built

    swimlane = request.GET.get("swimlane") if request.GET.get("swimlane") in ("epic", "assignee") else ""
    columns = build_columns(issues)
    lanes = [{"name": "", "columns": columns}]
    if swimlane:
        groups = {}
        for issue in issues:
            if swimlane == "assignee":
                name = issue.assignee.display_name if issue.assignee else _("Unassigned")
            else:
                name = f"{issue.epic.key} {issue.epic.title}" if issue.epic else _("No epic")
            groups.setdefault(name, []).append(issue)
        # Named lanes first, alphabetically; the "no epic" / "unassigned" lane goes last.
        fallback = _("Unassigned") if swimlane == "assignee" else _("No epic")
        ordered = sorted(groups.items(), key=lambda kv: (kv[0] == fallback, kv[0]))
        lanes = [{"name": name, "columns": build_columns(subset)} for name, subset in ordered]
    transitions = workflow.transition_map(project)
    return render(
        request,
        "agile/board.html",
        project_context(
            request,
            project,
            columns=columns,
            lanes=lanes,
            swimlane=swimlane,
            active_sprint=active,
            scope=scope,
            transitions=transitions,
            members=project.members_qs(),
            can_configure=can(request.user, project, "manage_project"),
        ),
    )


@login_required
def backlog(request, key):
    project = get_project_or_404(request.user, key)
    sprints = list(project.sprints.exclude(state=Sprint.State.CLOSED))
    sprints.sort(key=lambda s: (0 if s.is_active else 1, s.created_at))
    items = _card_qs(project).filter(Q(sprint__in=sprints) | Q(sprint__isnull=True))
    items = items.exclude(Q(sprint__isnull=True) & Q(status__in=workflow.done_keys(project))).order_by("rank", "id")
    by_sprint = {}
    for issue in items:
        by_sprint.setdefault(issue.sprint_id, []).append(issue)
    sprint_rows = []
    for s in sprints:
        lst = by_sprint.get(s.pk, [])
        sprint_rows.append(
            {
                "sprint": s,
                "issues": lst,
                "points": sum(i.story_points or 0 for i in lst),
                "done_points": sum(i.story_points or 0 for i in lst if i.is_done),
            }
        )
    backlog_items = by_sprint.get(None, [])
    today = timezone.localdate()
    return render(
        request,
        "agile/backlog.html",
        project_context(
            request,
            project,
            sprint_rows=sprint_rows,
            backlog_items=backlog_items,
            backlog_points=sum(i.story_points or 0 for i in backlog_items),
            sprint_form=SprintForm(initial={"name": _("%(key)s Sprint %(n)s") % {"key": project.key, "n": project.sprints.count() + 1}}),
            start_form=StartSprintForm(initial={"start_date": today, "end_date": today + datetime.timedelta(days=13)}),
            future_sprints=[s for s in sprints if not s.is_active],
            has_active=any(s.is_active for s in sprints),
            velocity=services.velocity(project)["average"],
        ),
    )


@login_required
@require_POST
def sprint_create(request, key):
    project = get_project_or_404(request.user, key, "manage_sprints")
    form = SprintForm(request.POST)
    if form.is_valid():
        sprint = form.save(commit=False)
        sprint.project = project
        sprint.save()
        messages.success(request, _("Sprint created."))
    else:
        messages.error(request, form.errors.as_text())
    return redirect("agile:backlog", key=project.key)


@login_required
def sprint_edit(request, key, pk):
    project = get_project_or_404(request.user, key, "manage_sprints")
    sprint = get_object_or_404(Sprint, pk=pk, project=project)
    form = SprintForm(request.POST or None, instance=sprint)
    if request.method == "POST":
        if request.POST.get("delete") and sprint.state == Sprint.State.FUTURE:
            sprint.issues.update(sprint=None)
            sprint.delete()
            messages.success(request, _("Sprint deleted; its issues moved to the backlog."))
            return redirect("agile:backlog", key=project.key)
        if form.is_valid():
            form.save()
            messages.success(request, _("Sprint updated."))
            return redirect("agile:backlog", key=project.key)
    return render(request, "agile/sprint_form.html", project_context(request, project, form=form, sprint=sprint))


@login_required
@require_POST
def sprint_start(request, key, pk):
    project = get_project_or_404(request.user, key, "manage_sprints")
    sprint = get_object_or_404(Sprint, pk=pk, project=project)
    form = StartSprintForm(request.POST)
    if not form.is_valid():
        messages.error(request, form.errors.as_text())
        return redirect("agile:backlog", key=project.key)
    try:
        services.start_sprint(sprint, form.cleaned_data["start_date"], form.cleaned_data["end_date"])
        messages.success(request, _("%(name)s started.") % {"name": sprint.name})
        return redirect("agile:board", key=project.key)
    except services.SprintError as exc:
        messages.error(request, str(exc))
    return redirect("agile:backlog", key=project.key)


@login_required
@require_POST
def sprint_complete(request, key, pk):
    project = get_project_or_404(request.user, key, "manage_sprints")
    sprint = get_object_or_404(Sprint, pk=pk, project=project)
    move_to = None
    target = request.POST.get("move_to")
    if target and target.isdigit():
        move_to = get_object_or_404(Sprint, pk=int(target), project=project)
    try:
        moved = services.complete_sprint(sprint, move_to)
        messages.success(
            request,
            _("%(name)s completed. %(n)s incomplete issue(s) moved.") % {"name": sprint.name, "n": moved},
        )
        return redirect(reverse("agile:reports", args=[project.key]) + f"?sprint={sprint.pk}")
    except services.SprintError as exc:
        messages.error(request, str(exc))
    return redirect("agile:backlog", key=project.key)


@login_required
def reports(request, key):
    project = get_project_or_404(request.user, key)
    sprints = list(project.sprints.exclude(state=Sprint.State.FUTURE).order_by("-created_at"))
    selected = None
    if (request.GET.get("sprint") or "").isdigit():
        selected = next((s for s in sprints if s.pk == int(request.GET["sprint"])), None)
    if selected is None and sprints:
        selected = next((s for s in sprints if s.is_active), sprints[0])
    burn = services.burndown(selected) if selected else None
    vel = services.velocity(project)
    report = None
    if selected:
        if selected.state == Sprint.State.CLOSED:
            scope_ids = [int(k) for k in selected.final_scope.keys()]
            scope = project.issues.filter(pk__in=scope_ids).select_related("assignee")
        else:
            scope = selected.issues.select_related("assignee")
        scope = list(scope.order_by("number"))
        committed_ids = {int(k) for k in selected.committed_scope.keys()}
        if selected.state == Sprint.State.CLOSED:
            # Completion moved unfinished issues out, so whatever still points
            # at this sprint was Done at close time (their status may differ now).
            def was_done(i):
                return i.sprint_id == selected.pk
        else:
            def was_done(i):
                return i.is_done
        report = {
            "completed": [i for i in scope if was_done(i)],
            "incomplete": [i for i in scope if not was_done(i)],
            "added": [i for i in scope if i.pk not in committed_ids and committed_ids],
        }
    return render(
        request,
        "agile/reports.html",
        project_context(
            request,
            project,
            sprints=sprints,
            selected=selected,
            burn=burn,
            burn_chart=services.chart_geometry(burn),
            velocity=vel,
            velocity_chart=services.velocity_geometry(vel),
            report=report,
            open_points=project.issues.exclude(status__in=workflow.done_keys(project))
            .exclude(issue_type__in=[IssueType.EPIC, IssueType.TEST])
            .aggregate(s=Sum("story_points"))["s"]
            or 0,
        ),
    )


@login_required
def board_settings(request, key):
    project = get_project_or_404(request.user, key, "manage_project")
    columns = board_service.ensure_columns(project)
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "add":
                board_service.add_column(project, request.POST.get("name"))
                messages.success(request, _("Column added."))
            elif action == "rename":
                board_service.rename_column(_column(project, request), request.POST.get("name"))
                messages.success(request, _("Column renamed."))
            elif action == "move":
                board_service.move_column(_column(project, request), request.POST.get("direction"))
            elif action == "delete":
                target = None
                if request.POST.get("move_to", "").isdigit():
                    target = _column(project, request, field="move_to")
                board_service.delete_column(_column(project, request), target)
                messages.success(request, _("Column deleted."))
            elif action == "assign":
                assignment = {}
                for status in workflow.status_map(project):
                    value = request.POST.get(f"status_{status}", "")
                    if not value.isdigit():
                        raise board_service.BoardError(_("Every status must be placed in a column."))
                    assignment[status] = int(value)
                board_service.set_status_assignment(project, assignment)
                messages.success(request, _("Board saved."))
        except board_service.BoardError as exc:
            messages.error(request, str(exc))
        return redirect("agile:board_settings", key=project.key)

    columns = board_service.ensure_columns(project)
    column_of = board_service.status_to_column(columns)
    names = workflow.status_map(project)
    for col in columns:
        col.status_pairs = [(st, names[st].name) for st in col.statuses if st in names]
    return render(
        request,
        "agile/board_settings.html",
        project_context(
            request,
            project,
            columns=columns,
            status_rows=[
                {"value": s, "label": st.name, "column": column_of.get(s)} for s, st in names.items()
            ],
        ),
    )


def _column(project, request, field="column"):
    pk = request.POST.get(field, "")
    if not pk.isdigit():
        raise board_service.BoardError(_("Unknown column."))
    return get_object_or_404(BoardColumn, pk=int(pk), project=project)
