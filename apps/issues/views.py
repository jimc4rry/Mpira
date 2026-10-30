import csv
import mimetypes
import secrets
from urllib.parse import quote, urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _, ngettext
from django.views.decorators.http import require_POST

from apps.projects.permissions import can, get_project_or_404, visible_projects
from apps.projects.views import project_context

from . import importer, services
from .custom_fields import display_values
from .filters import apply_issue_filters, apply_jql, clean_query
from .query import QueryError
from .forms import AttachmentForm, CommentForm, IssueForm, LinkForm
from . import workflow
from .models import Attachment, Comment, Issue, IssueLink, IssueType, Priority, Rule, SavedFilter, Webhook, WorkflowStatus


def _issue_or_404(request, key, number, capability="view"):
    project = get_project_or_404(request.user, key, capability)
    issue = get_object_or_404(
        Issue.objects.select_related("project", "assignee", "reporter", "epic", "parent", "sprint"),
        project=project,
        number=number,
    )
    return project, issue


@login_required
def issue_list(request, key):
    project = get_project_or_404(request.user, key)
    qs = project.issues.select_related("assignee", "project", "sprint").prefetch_related("labels")
    saved_filters = project.saved_filters.filter(Q(owner=request.user) | Q(shared=True))
    g = request.GET
    if (g.get("saved") or "").isdigit():
        saved = saved_filters.filter(pk=int(g["saved"])).first()
        if saved:
            g = QueryDict(saved.query)
    qs = apply_issue_filters(project, qs, g, request.user)
    if (g.get("jql") or "").strip():
        try:
            qs = apply_jql(qs, g["jql"], project, request.user)
        except QueryError as exc:
            messages.error(request, str(exc))
    page = Paginator(qs, 50).get_page(g.get("page"))
    return render(
        request,
        "issues/issue_list.html",
        project_context(
            request,
            project,
            page=page,
            type_choices=IssueType.choices,
            status_choices=[(s.key, s.name) for s in workflow.statuses(project)],
            priority_choices=Priority.choices,
            members=project.members_qs(),
            labels=project.labels.all(),
            components=project.components.all(),
            versions=project.versions.all(),
            epics=project.issues.filter(issue_type=IssueType.EPIC).order_by("number"),
            filters=g,
            saved_filters=saved_filters,
            filter_query=g.urlencode(),
        ),
    )


@login_required
def issue_create(request, key):
    project = get_project_or_404(request.user, key, "edit_issues")
    initial = {"issue_type": request.GET.get("type") or IssueType.TASK}
    if (request.GET.get("parent") or "").isdigit():
        parent = project.issues.filter(number=int(request.GET["parent"])).first()
        if parent:
            initial.update({"parent": parent, "issue_type": IssueType.SUBTASK, "sprint": parent.sprint})
    if (request.GET.get("epic") or "").isdigit():
        initial["epic"] = project.issues.filter(number=int(request.GET["epic"]), issue_type=IssueType.EPIC).first()
    if (request.GET.get("sprint") or "").isdigit():
        initial["sprint"] = project.sprints.filter(pk=int(request.GET["sprint"])).first()
    form = IssueForm(request.POST or None, project=project, initial=initial)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            issue = form.save(commit=False)
            services.prepare_new_issue(issue, project, request.user)
            issue.save()
            form.save_m2m()
            services.after_create(issue, request.user)
        messages.success(request, _("Created %(key)s.") % {"key": issue.key})
        if request.POST.get("create_another"):
            return redirect(request.get_full_path())
        return redirect(issue.get_absolute_url())
    return render(request, "issues/issue_form.html", project_context(request, project, form=form, is_new=True))


@login_required
def issue_edit(request, key, number):
    project, issue = _issue_or_404(request, key, number, "edit_issues")
    form = IssueForm(request.POST or None, project=project, instance=issue)
    if request.method == "POST":
        before = services.snapshot(issue)
        if form.is_valid():
            with transaction.atomic():
                issue = form.save()
                services.record_changes(issue, request.user, before)
            messages.success(request, _("Saved."))
            return redirect(issue.get_absolute_url())
    return render(
        request, "issues/issue_form.html", project_context(request, project, form=form, issue=issue, is_new=False)
    )


@login_required
def issue_detail(request, key, number):
    project, issue = _issue_or_404(request, key, number)
    # Links may cross projects; hide the ones pointing into projects this viewer can't see.
    visible = visible_projects(request.user)
    links_out = issue.outward_links.filter(target__project__in=visible).select_related("target__project")
    links_in = issue.inward_links.filter(source__project__in=visible).select_related("source__project")
    members = list(project.members_qs())
    if issue.assignee and issue.assignee not in members:
        members.append(issue.assignee)  # a former member stays selected until someone else is chosen
    ctx = project_context(
        request,
        project,
        issue=issue,
        members=members,
        comments=issue.comments.select_related("author"),
        attachments=issue.attachments.select_related("uploaded_by"),
        activity=issue.activity.select_related("actor")[:100],
        subtasks=issue.subtasks.select_related("assignee").order_by("number"),
        epic_children=issue.epic_children.select_related("assignee").order_by("number")
        if issue.issue_type == IssueType.EPIC
        else [],
        links_out=links_out,
        links_in=links_in,
        watchers=issue.watchers.all(),
        is_watching=issue.watchers.filter(pk=request.user.pk).exists(),
        custom_values=display_values(issue),
        comment_form=CommentForm(),
        attachment_form=AttachmentForm(),
        link_form=LinkForm(),
        transitions=issue.allowed_transitions,
        wiki_pages=[p for p in issue.wiki_pages.select_related("space__project") if can(request.user, p.space.project, "view")],
    )
    # Test management panels (apps.testmgmt) - imported lazily to keep apps decoupled.
    from apps.testmgmt.views import issue_test_panel

    ctx.update(issue_test_panel(issue, request.user))
    return render(request, "issues/issue_detail.html", ctx)


@login_required
@require_POST
def issue_delete(request, key, number):
    project, issue = _issue_or_404(request, key, number, "delete_issues")
    issue_key = issue.key
    for att in issue.attachments.all():
        att.delete()
    issue.delete()
    messages.success(request, _("Deleted %(key)s.") % {"key": issue_key})
    return redirect("issues:list", key=project.key)


@login_required
@require_POST
def issue_transition(request, key, number):
    project, issue = _issue_or_404(request, key, number, "edit_issues")
    try:
        services.transition_issue(issue, request.user, request.POST.get("status"))
    except services.WorkflowError as exc:
        messages.error(request, str(exc))
    return redirect(issue.get_absolute_url())


@login_required
@require_POST
def comment_add(request, key, number):
    project, issue = _issue_or_404(request, key, number, "comment")
    form = CommentForm(request.POST)
    if form.is_valid():
        services.add_comment(issue, request.user, form.cleaned_data["body"])
    else:
        messages.error(request, _("The comment cannot be empty."))
    return redirect(issue.get_absolute_url() + "#comments")


@login_required
@require_POST
def comment_delete(request, key, number, pk):
    project, issue = _issue_or_404(request, key, number)
    comment = get_object_or_404(Comment, pk=pk, issue=issue)
    if comment.author_id != request.user.pk and not can(request.user, project, "manage_project"):
        raise PermissionDenied
    comment.delete()
    messages.success(request, _("Comment deleted."))
    return redirect(issue.get_absolute_url() + "#comments")


@login_required
@require_POST
def attachment_upload(request, key, number):
    project, issue = _issue_or_404(request, key, number, "edit_issues")
    form = AttachmentForm(request.POST, request.FILES)
    if form.is_valid():
        f = form.cleaned_data["file"]
        Attachment.objects.create(
            issue=issue, file=f, filename=f.name[:255], size=f.size, uploaded_by=request.user
        )
        issue.activity.create(actor=request.user, kind="attachment", new_value=f.name[:200])
        messages.success(request, _("File attached."))
    else:
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
    return redirect(issue.get_absolute_url() + "#attachments")


@login_required
def attachment_download(request, key, number, pk):
    project, issue = _issue_or_404(request, key, number)
    att = get_object_or_404(Attachment, pk=pk, issue=issue)
    try:
        handle = att.file.open("rb")
    except FileNotFoundError:
        raise Http404
    content_type = mimetypes.guess_type(att.filename)[0] or "application/octet-stream"
    inline = content_type.startswith("image/") or content_type == "application/pdf"
    response = FileResponse(handle, content_type=content_type, as_attachment=not inline, filename=att.filename)
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
    return response


@login_required
@require_POST
def attachment_delete(request, key, number, pk):
    project, issue = _issue_or_404(request, key, number, "edit_issues")
    att = get_object_or_404(Attachment, pk=pk, issue=issue)
    if att.uploaded_by_id != request.user.pk and not can(request.user, project, "manage_project"):
        raise PermissionDenied
    att.delete()
    messages.success(request, _("Attachment deleted."))
    return redirect(issue.get_absolute_url() + "#attachments")


@login_required
@require_POST
def link_add(request, key, number):
    project, issue = _issue_or_404(request, key, number, "edit_issues")
    form = LinkForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Invalid link."))
        return redirect(issue.get_absolute_url())
    target_key = form.cleaned_data["target_key"].strip().upper()
    try:
        tkey, tnum = target_key.rsplit("-", 1)
        target = Issue.objects.select_related("project").get(project__key=tkey, number=int(tnum))
    except (ValueError, Issue.DoesNotExist):
        target = None
    if target is None or not can(request.user, target.project, "view"):
        messages.error(request, _("Issue %(key)s not found.") % {"key": target_key})
        return redirect(issue.get_absolute_url())
    source, dest = issue, target
    if request.POST.get("direction") == "in":
        source, dest = target, issue
    try:
        services.link_issues(source, dest, form.cleaned_data["link_type"], request.user)
        messages.success(request, _("Link added."))
    except services.WorkflowError as exc:
        messages.error(request, str(exc))
    return redirect(issue.get_absolute_url())


@login_required
@require_POST
def link_delete(request, key, number, pk):
    project, issue = _issue_or_404(request, key, number, "edit_issues")
    link = get_object_or_404(IssueLink, Q(source=issue) | Q(target=issue), pk=pk)
    link.delete()
    messages.success(request, _("Link removed."))
    return redirect(issue.get_absolute_url())


@login_required
@require_POST
def watch_toggle(request, key, number):
    project, issue = _issue_or_404(request, key, number)
    if issue.watchers.filter(pk=request.user.pk).exists():
        issue.watchers.remove(request.user)
    else:
        issue.watchers.add(request.user)
    return redirect(issue.get_absolute_url())


@login_required
def issue_import_template(request, key, fmt):
    get_project_or_404(request.user, key, "edit_issues")
    if fmt not in importer.FORMATS:
        raise Http404
    spec = importer.FORMATS[fmt]
    response = HttpResponse(importer.template_bytes(fmt), content_type=spec["mime"])
    response["Content-Disposition"] = f'attachment; filename="mpira-{key.lower()}-issues-template.{spec["ext"]}"'
    return response


@login_required
def issue_import(request, key):
    project = get_project_or_404(request.user, key, "edit_issues")
    result = None
    if request.method == "POST":
        upload = request.FILES.get("file")
        if not upload:
            messages.error(request, _("Choose a CSV file first."))
        else:
            try:
                parsed, errors, fmt = importer.parse(project, upload.read(), upload.name)
            except importer.ImportFormatError as exc:
                messages.error(request, str(exc))
            else:
                if errors:
                    messages.error(
                        request,
                        _("Nothing was imported. Fix the %(n)s row(s) below and upload the file again.")
                        % {"n": len(errors)},
                    )
                    result = {"errors": errors, "valid": len(parsed)}
                else:
                    created = importer.commit(project, request.user, parsed)
                    messages.success(request, _("Imported %(n)s issues.") % {"n": len(created)})
                    return redirect("issues:list", key=project.key)
    return render(
        request,
        "issues/issue_import.html",
        project_context(request, project, result=result, columns=importer.COLUMNS, formats=importer.FORMATS, notes=importer.COLUMN_NOTES),
    )


@login_required
def workflow_settings(request, key):
    """Statuses and the transitions between them (project managers and admins)."""
    project = get_project_or_404(request.user, key, "manage_project")
    from apps.agile import board as board_service
    from apps.agile.models import BoardColumn

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "add":
                status = workflow.add_status(
                    project,
                    request.POST.get("name"),
                    counts_as_done=bool(request.POST.get("counts_as_done")),
                )
                column_pk = request.POST.get("column", "")
                if column_pk.isdigit():
                    board_service.place_status(project, status.key, int(column_pk))
                else:
                    board_service.ensure_columns(project)
                messages.success(request, _("Status added."))
            elif action == "update":
                status = _status(project, request.POST.get("status"))
                workflow.update_status(
                    status,
                    name=request.POST.get("name", status.name),
                    counts_as_done=bool(request.POST.get("counts_as_done")),
                    is_initial=True if request.POST.get("is_initial") else None,
                )
                messages.success(request, _("Status saved."))
            elif action == "delete":
                status = _status(project, request.POST.get("status"))
                move_to = None
                if request.POST.get("move_to", "").isdigit():
                    move_to = _status(project, request.POST.get("move_to"), by_pk=True)
                workflow.delete_status(status, move_to)
                board_service.ensure_columns(project)
                messages.success(request, _("Status deleted."))
            elif action == "transitions":
                allowed = {s.key: set() for s in workflow.statuses(project)}
                for name in request.POST:
                    if name.startswith("next|"):
                        _prefix, source, target = name.split("|", 2)
                        if source in allowed:
                            allowed[source].add(target)
                workflow.save_transitions(project, allowed)
                messages.success(request, _("Transitions saved."))
        except workflow.WorkflowError as exc:
            messages.error(request, str(exc))
        return redirect("issues:workflow", key=project.key)

    all_statuses = workflow.statuses(project)
    keys = [s.key for s in all_statuses]
    names = workflow.status_map(project)
    nxt = workflow.transition_map(project)
    matrix = [
        {
            "status": s,
            "cells": [{"to": t, "checked": t in nxt.get(s.key, []), "self": t == s.key} for t in keys],
        }
        for s in all_statuses
    ]
    return render(
        request,
        "issues/workflow.html",
        project_context(
            request,
            project,
            statuses=all_statuses,
            matrix=matrix,
            matrix_targets=[names[k] for k in keys],
            columns=board_service.ensure_columns(project),
            in_use={s.key: Issue.objects.filter(project=project, status=s.key).count() for s in all_statuses},
        ),
    )


def _status(project, value, by_pk=False):
    from django.http import Http404

    lookup = {"pk": int(value)} if by_pk and str(value).isdigit() else {"key": value or ""}
    status = WorkflowStatus.objects.filter(project=project, **lookup).first()
    if status is None:
        raise Http404
    return status


# ---------- CSV export and saved filters ----------

EXPORT_LIMIT = 5000
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value):
    """A spreadsheet must not run what a user typed: a cell that starts like a formula gets a quote in front."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


@login_required
def issue_export(request, key):
    """The issues of the current filters as CSV (UTF-8 with a BOM, so Excel shows Greek correctly)."""
    project = get_project_or_404(request.user, key)
    qs = project.issues.select_related("assignee", "reporter").prefetch_related("labels", "fix_versions")
    qs = apply_issue_filters(project, qs, request.GET, request.user)
    if (request.GET.get("jql") or "").strip():
        try:
            qs = apply_jql(qs, request.GET["jql"], project, request.user)
        except QueryError as exc:
            messages.error(request, str(exc))
    qs = qs[:EXPORT_LIMIT]
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{project.key}-issues.csv"'
    response.write("﻿")
    writer = csv.writer(response)
    writer.writerow(["key", "type", "title", "status", "priority", "assignee", "reporter", "created", "updated",
                     "due_date", "labels", "fix_versions"])
    for issue in qs:
        writer.writerow([
            csv_cell(issue.key),
            csv_cell(issue.issue_type),
            csv_cell(issue.title),
            csv_cell(issue.status),
            csv_cell(issue.priority),
            csv_cell(issue.assignee.display_name if issue.assignee else ""),
            csv_cell(issue.reporter.display_name if issue.reporter else ""),
            issue.created_at.date().isoformat(),
            issue.updated_at.date().isoformat(),
            issue.due_date.isoformat() if issue.due_date else "",
            csv_cell(", ".join(label.name for label in issue.labels.all())),
            csv_cell(", ".join(v.name for v in issue.fix_versions.all())),
        ])
    return response


@login_required
@require_POST
def filter_save(request, key):
    """Saves the filters of the page the user is on (the hidden `query` field) under a name."""
    project = get_project_or_404(request.user, key)
    name = (request.POST.get("name") or "").strip()[:80]
    if not name:
        messages.error(request, _("Give the filter a name."))
    else:
        query = clean_query(QueryDict(request.POST.get("query", "")))
        if not query:
            messages.error(request, _("There are no filters to save."))
        else:
            saved, created = SavedFilter.objects.update_or_create(
                project=project, owner=request.user, name=name,
                defaults={"query": urlencode(query), "shared": request.POST.get("shared") == "on"},
            )
            messages.success(request, _("Filter saved.") if created else _("Filter updated."))
    return redirect(reverse("issues:list", args=[project.key]) + ("?" + request.POST.get("query", "") if request.POST.get("query") else ""))


@login_required
@require_POST
def filter_delete(request, key, pk):
    """Only the owner deletes a saved filter, shared or not."""
    project = get_project_or_404(request.user, key)
    saved = get_object_or_404(SavedFilter, project=project, pk=pk, owner=request.user)
    saved.delete()
    messages.success(request, _("Filter deleted."))
    return redirect(reverse("issues:list", args=[project.key]))


# ---------- webhooks (settings page) ----------

@login_required
def webhooks_page(request, key):
    """Add, test and delete the project's webhooks. Only project managers and admins (capability manage_project)."""
    from .webhooks import address_problem, send

    project = get_project_or_404(request.user, key, "manage_project")
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add":
            url = (request.POST.get("url") or "").strip()[:300]
            events = [e for e in request.POST.getlist("events") if e in Webhook.Event.values]
            problem = address_problem(url) if url else _("The address is required.")
            if problem:
                messages.error(request, problem)
            elif not events:
                messages.error(request, _("Choose at least one event."))
            else:
                secret = secrets.token_urlsafe(32)
                Webhook.objects.create(project=project, url=url, secret=secret, events=",".join(events))
                messages.success(request, _("Webhook added. Its signing secret is shown once, copy it now: %(secret)s")
                                 % {"secret": secret})
        elif action in ("delete", "test"):
            hook = get_object_or_404(Webhook, project=project, pk=request.POST.get("pk"))
            if action == "delete":
                hook.delete()
                messages.success(request, _("Webhook deleted."))
            else:
                ok = send(hook, "webhook.ping", {"project": project.key})
                messages.success(request, _("The address answered.") if ok else _("The address did not answer: %(error)s")
                                 % {"error": hook.last_error or hook.last_status})
        return redirect("issues:webhooks", key=project.key)
    return render(request, "issues/webhooks.html", project_context(
        request, project, hooks=project.webhooks.all(), event_choices=Webhook.Event.choices,
    ))


# ---------- releases: progress and release notes ----------

@login_required
def releases_page(request, key):
    project = get_project_or_404(request.user, key)
    done = workflow.done_keys(project)
    rows = []
    for version in project.versions.all():
        issues = version.issues.all()
        total = issues.count()
        finished = issues.filter(status__in=done).count()
        rows.append({
            "version": version,
            "total": total,
            "done": finished,
            "percent": round(100 * finished / total) if total else 0,
        })
    return render(request, "issues/releases.html", project_context(request, project, rows=rows))


@login_required
def release_notes(request, key, pk):
    """Release notes as Markdown: finished issues grouped by type, then what is still open."""
    project = get_project_or_404(request.user, key)
    version = get_object_or_404(project.versions, pk=pk)
    done = workflow.done_keys(project)
    issues = list(version.issues.select_related("assignee").order_by("issue_type", "number"))
    finished = [i for i in issues if i.status in done]
    open_items = [i for i in issues if i.status not in done]

    lines = [f"# {project.key} {version.name}", ""]
    if version.release_date:
        lines += [f"{_('Release date')}: {version.release_date.isoformat()}", ""]
    for value, label in IssueType.choices:
        group = [i for i in finished if i.issue_type == value]
        if group:
            lines += [f"## {label}", ""]
            lines += [f"- {i.key} {i.title}" for i in group]
            lines.append("")
    if open_items:
        lines += [f"## {_('Not done')}", ""]
        lines += [f"- {i.key} {i.title} ({workflow.label(project, i.status)})" for i in open_items]
        lines.append("")
    response = HttpResponse("\n".join(lines), content_type="text/markdown; charset=utf-8")
    if request.GET.get("download"):
        # The version name may hold non-ASCII letters: filename* carries the real name, the plain one is the fallback.
        name = f"{project.key}-{version.name}.md"
        response["Content-Disposition"] = f"attachment; filename=\"{project.key}-release-{version.pk}.md\"; filename*=UTF-8''{quote(name)}"
    return response


# ---------- bulk actions on the list ----------

@login_required
@require_POST
def issues_bulk(request, key):
    from .bulk import BulkError, bulk_apply

    project = get_project_or_404(request.user, key, "edit_issues")
    numbers = [int(n) for n in request.POST.getlist("issues") if n.isdigit()]
    issues = list(project.issues.filter(number__in=numbers[:201]))
    action = request.POST.get("action", "")
    value = request.POST.get("value", "")
    try:
        changed, failed = bulk_apply(project, request.user, issues, action, value)
    except BulkError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, ngettext("%(n)d issue changed.", "%(n)d issues changed.", changed) % {"n": changed})
        for key_, reason in failed[:10]:
            messages.error(request, f"{key_}: {reason}")
    target = reverse("issues:list", args=[project.key])
    query = request.POST.get("query", "")
    return redirect(target + ("?" + query if query else ""))


@login_required
@require_POST
def issue_inline(request, key, number):
    """One change from the list row (status, priority or assignee). Same rules as the bulk actions: JSON answer."""
    from django.http import JsonResponse

    from .bulk import BulkError, bulk_apply

    project, issue = _issue_or_404(request, key, number, "edit_issues")
    action = {"status": "transition", "priority": "priority", "assignee": "assign"}.get(request.POST.get("field"))
    if action is None:
        return JsonResponse({"error": _("Choose a status.")}, status=400)
    try:
        changed, failed = bulk_apply(project, request.user, [issue], action, request.POST.get("value", ""))
    except BulkError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    if failed:
        return JsonResponse({"error": failed[0][1]}, status=400)
    return JsonResponse({"ok": changed == 1, "key": issue.key})


# ---------- timeline with swimlanes ----------

@login_required
def timeline_page(request, key):
    """Bars from start to due date. Swimlanes group the bars by epic (default) or by assignee."""
    from datetime import timedelta

    project = get_project_or_404(request.user, key)
    group = request.GET.get("group") if request.GET.get("group") in ("epic", "assignee") else "epic"
    dated = (project.issues.exclude(issue_type=IssueType.EPIC)
             .filter(Q(start_date__isnull=False) | Q(due_date__isnull=False))
             .select_related("assignee", "epic").order_by("due_date", "number"))
    spans = []
    for issue in dated:
        start = issue.start_date or issue.due_date
        end = issue.due_date or issue.start_date
        spans.append((issue, start, max(start, end)))
    lanes, first, last = {}, None, None
    if spans:
        first = min(s for _, s, _ in spans)
        last = max(e for _, _, e in spans)
        total = max(1, (last - first).days + 1)
        for issue, start, end in spans:
            if group == "assignee":
                name = issue.assignee.display_name if issue.assignee else _("Unassigned")
            else:
                name = f"{issue.epic.key} {issue.epic.title}" if issue.epic else _("No epic")
            width = ((end - start).days + 1) * 100 / total
            lanes.setdefault(name, []).append({
                "issue": issue,
                "left": round((start - first).days * 100 / total, 2),
                "width": max(round(width, 2), 0.8),
                "done": issue.is_done,
                "span": f"{start.isoformat()} → {end.isoformat()}",
            })
    undated = project.issues.exclude(issue_type=IssueType.EPIC).filter(start_date__isnull=True, due_date__isnull=True).count()
    return render(request, "issues/timeline.html", project_context(
        request, project,
        lanes=[{"name": name, "rows": rows} for name, rows in sorted(lanes.items())],
        first=first, last=last, group=group, undated=undated,
    ))


# ---------- automation rules (settings page) ----------

@login_required
def automation_page(request, key):
    """Lists the project's rules and adds, switches or deletes them. Project managers and admins only."""
    from .automation import validate

    project = get_project_or_404(request.user, key, "manage_project")
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add":
            # The "Then" select is "rule_action": a field called "action" is the page's own command (add, toggle, delete).
            data = {name: (request.POST.get(name) or "").strip() for name in ("name", "trigger", "condition", "value")}
            data["action"] = (request.POST.get("rule_action") or "").strip()
            problem = None
            if not data["name"]:
                problem = _("Give the rule a name.")
            else:
                problem = validate(project, data["trigger"], data["condition"], data["action"], data["value"], request.user)
            if problem:
                messages.error(request, problem)
            else:
                Rule.objects.create(project=project, created_by=request.user, name=data["name"][:80], trigger=data["trigger"],
                                    condition=data["condition"][:500], action=data["action"], value=data["value"][:500])
                messages.success(request, _("Rule added."))
        elif action in ("toggle", "delete"):
            rule = get_object_or_404(Rule, project=project, pk=request.POST.get("pk"))
            if action == "delete":
                rule.delete()
                messages.success(request, _("Rule deleted."))
            else:
                rule.enabled = not rule.enabled
                rule.save(update_fields=["enabled"])
        return redirect("issues:automation", key=project.key)
    return render(request, "issues/automation.html", project_context(
        request, project, rules=project.automation_rules.all(),
        trigger_choices=Rule.Trigger.choices, action_choices=Rule.Action.choices,
    ))
