from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts.models import Role
from apps.agile.models import Sprint
from apps.issues import workflow
from apps.issues.models import Attachment, CustomFieldDefinition, IssueType

from .forms import (
    ComponentForm,
    CustomFieldForm,
    LabelForm,
    MembershipForm,
    ProjectCreateForm,
    ProjectEditForm,
    VersionForm,
)
from .models import Component, Label, ProjectMembership, ProjectRole, Version
from .permissions import capabilities_for, get_project_or_404, visible_projects


def project_context(request, project, **extra):
    """Common context for every page inside a project (nav + capabilities)."""
    ctx = {"project": project, "caps": capabilities_for(request.user, project)}
    ctx.update(extra)
    return ctx


def settings_url(project, tab):
    return reverse("projects:settings", args=[project.key]) + f"?tab={tab}"


def can_create_projects(user):
    return user.is_workspace_admin or user.role == Role.PROJECT_MANAGER


@login_required
def project_list(request):
    projects = visible_projects(request.user).annotate(
        member_count=Count("memberships", distinct=True),
    )
    for p in projects:
        p.open_count = p.issues.exclude(status__in=workflow.done_keys(p)).count()
    return render(
        request,
        "projects/project_list.html",
        {"projects": projects, "can_create": can_create_projects(request.user)},
    )


@login_required
def project_create(request):
    if not can_create_projects(request.user):
        raise PermissionDenied
    form = ProjectCreateForm(request.POST or None, initial={"lead": request.user})
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            project = form.save()
            ProjectMembership.objects.get_or_create(
                project=project, user=request.user, defaults={"role": ProjectRole.PROJECT_MANAGER}
            )
            if project.lead_id and project.lead_id != request.user.pk:
                ProjectMembership.objects.get_or_create(
                    project=project, user=project.lead, defaults={"role": ProjectRole.PROJECT_MANAGER}
                )
        messages.success(request, _("Project %(key)s created.") % {"key": project.key})
        return redirect(project.get_absolute_url())
    return render(request, "projects/project_form.html", {"form": form})


@login_required
def project_detail(request, key):
    project = get_project_or_404(request.user, key)
    issues = project.issues.all()
    by_status = {row["status"]: row["n"] for row in issues.values("status").annotate(n=Count("id"))}
    by_type = {row["issue_type"]: row["n"] for row in issues.values("issue_type").annotate(n=Count("id"))}
    epics = []
    for epic in issues.filter(issue_type=IssueType.EPIC).order_by("number"):
        children = epic.epic_children.all()
        total = children.count()
        done = children.filter(status__in=workflow.done_keys(project)).count()
        epics.append({"epic": epic, "total": total, "done": done, "percent": round(100 * done / total) if total else 0})
    active_sprint = project.sprints.filter(state=Sprint.State.ACTIVE).first()
    sprint_stats = None
    if active_sprint:
        agg = active_sprint.issues.aggregate(
            total=Sum("story_points"),
            done=Sum("story_points", filter=Q(status__in=workflow.done_keys(project))),
        )
        sprint_stats = {"total": agg["total"] or 0, "done": agg["done"] or 0}
    return render(
        request,
        "projects/project_detail.html",
        project_context(
            request,
            project,
            status_counts=[(s.key, s.name, by_status.get(s.key, 0)) for s in workflow.statuses(project)],
            type_counts=[(t, label, by_type.get(t, 0)) for t, label in IssueType.choices],
            epics=epics,
            active_sprint=active_sprint,
            sprint_stats=sprint_stats,
            members=project.memberships.select_related("user"),
            recent=issues.select_related("assignee").order_by("-updated_at")[:10],
            total_issues=sum(by_status.values()),
        ),
    )


@login_required
@require_POST
def project_delete(request, key):
    """
    Permanently delete a project and everything in it. Workspace admins only,
    and the project key must be typed to confirm. Attachment files are removed
    from disk too, because the database cascade doesn't touch them.
    """
    project = get_project_or_404(request.user, key, "manage_project")
    if not request.user.is_workspace_admin:
        raise PermissionDenied
    if request.POST.get("confirm", "").strip().upper() != project.key:
        messages.error(request, _("Type the project key to confirm the deletion."))
        return redirect(settings_url(project, "general"))
    name = project.name
    with transaction.atomic():
        for attachment in Attachment.objects.filter(issue__project=project):
            if attachment.file and attachment.file.storage.exists(attachment.file.name):
                attachment.file.storage.delete(attachment.file.name)
        project.delete()
    messages.success(request, _("Project %(name)s was deleted.") % {"name": name})
    return redirect("projects:list")


@login_required
def project_settings(request, key):
    project = get_project_or_404(request.user, key, "manage_project")
    form = ProjectEditForm(request.POST or None, instance=project)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Project updated."))
        return redirect("projects:settings", key=project.key)
    return render(
        request,
        "projects/settings.html",
        project_context(
            request,
            project,
            form=form,
            member_form=MembershipForm(project=project),
            members=project.memberships.select_related("user"),
            role_choices=ProjectRole.choices,
            component_form=ComponentForm(project=project),
            version_form=VersionForm(project=project),
            label_form=LabelForm(project=project),
            custom_field_form=CustomFieldForm(project=project),
            components=project.components.all(),
            versions=project.versions.all(),
            labels=project.labels.all(),
            custom_fields=project.custom_fields.all(),
            tab=request.GET.get("tab", "general"),
        ),
    )


@login_required
@require_POST
def member_add(request, key):
    project = get_project_or_404(request.user, key, "manage_project")
    form = MembershipForm(request.POST, project=project)
    if form.is_valid():
        membership = form.save(commit=False)
        membership.project = project
        membership.save()
        messages.success(request, _("Member added."))
    else:
        messages.error(request, _("Could not add member: %(err)s") % {"err": form.errors.as_text()})
    return redirect(settings_url(project, "members"))


@login_required
@require_POST
def member_update(request, key, pk):
    project = get_project_or_404(request.user, key, "manage_project")
    membership = get_object_or_404(ProjectMembership, pk=pk, project=project)
    if request.POST.get("remove"):
        if membership.user_id == request.user.pk and not request.user.is_workspace_admin:
            messages.error(request, _("You cannot remove yourself."))
        else:
            membership.delete()
            messages.success(request, _("Member removed."))
    else:
        role = request.POST.get("role")
        if role in ProjectRole.values:
            membership.role = role
            membership.save(update_fields=["role"])
            messages.success(request, _("Role updated."))
    return redirect(settings_url(project, "members"))


SETTINGS_ITEMS = {
    "component": (Component, ComponentForm, "components"),
    "version": (Version, VersionForm, "versions"),
    "label": (Label, LabelForm, "labels"),
    "customfield": (CustomFieldDefinition, CustomFieldForm, "fields"),
}


@login_required
def settings_item(request, key, kind, pk=None):
    """Create / edit / delete for the small per-project lookup tables."""
    if kind not in SETTINGS_ITEMS:
        raise PermissionDenied
    project = get_project_or_404(request.user, key, "manage_project")
    model, form_class, tab = SETTINGS_ITEMS[kind]
    instance = get_object_or_404(model, pk=pk, project=project) if pk else model(project=project)
    back = settings_url(project, tab)
    if request.method == "POST" and request.POST.get("delete") and pk:
        instance.delete()
        messages.success(request, _("Deleted."))
        return redirect(back)
    form = form_class(request.POST or None, instance=instance, project=project)
    if request.method == "POST":
        if form.is_valid():
            obj = form.save(commit=False)
            obj.project = project
            obj.save()
            messages.success(request, _("Saved."))
            return redirect(back)
        if not pk:
            messages.error(request, form.errors.as_text())
            return redirect(back)
    return render(
        request,
        "projects/settings_item.html",
        project_context(request, project, form=form, kind=kind, instance=instance, back=back),
    )
