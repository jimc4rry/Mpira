from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.projects.permissions import can, get_project_or_404, visible_projects
from apps.projects.views import project_context

from . import services
from .forms import PageForm
from .models import Page, Space


def _space(request, key, capability="view"):
    project = get_project_or_404(request.user, key, capability)
    space, _created = Space.objects.get_or_create(project=project, defaults={"name": project.name})
    return project, space


def _ctx(request, project, space, **extra):
    return project_context(request, project, space=space, tree=services.page_tree(space), **extra)


@login_required
def space_home(request, key):
    project, space = _space(request, key)
    q = request.GET.get("q", "").strip()
    results = services.search_pages(Space.objects.filter(pk=space.pk), q) if q else None
    recent = space.pages.select_related("updated_by").order_by("-updated_at")[:10]
    return render(request, "wiki/space_home.html", _ctx(request, project, space, q=q, results=results, recent=recent))


@login_required
def page_detail(request, key, pk):
    project, space = _space(request, key)
    page = get_object_or_404(Page.objects.select_related("updated_by", "created_by"), pk=pk, space=space)
    return render(
        request,
        "wiki/page_detail.html",
        _ctx(
            request,
            project,
            space,
            page=page,
            children=page.children.all(),
            # A page may reference issues of other projects; only list the ones this viewer may see.
            linked=page.linked_issues.filter(project__in=visible_projects(request.user)).select_related("project"),
        ),
    )


@login_required
def page_create(request, key):
    project, space = _space(request, key, "edit_wiki")
    initial = {}
    if (request.GET.get("parent") or "").isdigit():
        initial["parent"] = space.pages.filter(pk=int(request.GET["parent"])).first()
    form = PageForm(request.POST or None, space=space, initial=initial)
    if request.method == "POST" and form.is_valid():
        page, _changed = services.save_page(
            Page(space=space, position=space.pages.count()),
            request.user,
            title=form.cleaned_data["title"],
            body=form.cleaned_data["body"],
            parent=form.cleaned_data["parent"],
            change_note=form.cleaned_data["change_note"] or _("Created"),
        )
        messages.success(request, _("Page created."))
        return redirect(page.get_absolute_url())
    return render(request, "wiki/page_form.html", _ctx(request, project, space, form=form, is_new=True))


@login_required
def page_edit(request, key, pk):
    project, space = _space(request, key, "edit_wiki")
    page = get_object_or_404(Page, pk=pk, space=space)
    form = PageForm(
        request.POST or None,
        space=space,
        page=page,
        initial={"title": page.title, "body": page.body, "parent": page.parent},
    )
    if request.method == "POST":
        # Optimistic concurrency: refuse to overwrite someone else's newer save.
        base_version = request.POST.get("base_version")
        if base_version and base_version.isdigit() and int(base_version) != page.version:
            messages.error(
                request,
                _("Someone saved a newer version (v%(v)s) while you were editing. Copy your changes, reload and try again.")
                % {"v": page.version},
            )
        elif form.is_valid():
            page, changed = services.save_page(
                page,
                request.user,
                title=form.cleaned_data["title"],
                body=form.cleaned_data["body"],
                parent=form.cleaned_data["parent"],
                change_note=form.cleaned_data["change_note"],
            )
            messages.success(request, _("Page saved (v%(v)s).") % {"v": page.version} if changed else _("No changes."))
            return redirect(page.get_absolute_url())
    return render(request, "wiki/page_form.html", _ctx(request, project, space, form=form, page=page, is_new=False))


@login_required
def page_history(request, key, pk):
    project, space = _space(request, key)
    page = get_object_or_404(Page, pk=pk, space=space)
    return render(
        request,
        "wiki/page_history.html",
        _ctx(request, project, space, page=page, versions=page.versions.select_related("author")),
    )


@login_required
def page_version(request, key, pk, version):
    project, space = _space(request, key)
    page = get_object_or_404(Page, pk=pk, space=space)
    ver = get_object_or_404(page.versions.select_related("author"), version=version)
    prev = page.versions.filter(version__lt=version).order_by("-version").first()
    diff = services.diff_lines(prev.body if prev else "", ver.body)
    return render(
        request,
        "wiki/page_version.html",
        _ctx(request, project, space, page=page, ver=ver, prev=prev, diff=diff),
    )


@login_required
@require_POST
def page_restore(request, key, pk, version):
    project, space = _space(request, key, "edit_wiki")
    page = get_object_or_404(Page, pk=pk, space=space)
    ver = get_object_or_404(page.versions, version=version)
    services.restore_version(page, ver, request.user)
    messages.success(request, _("Restored version %(v)s.") % {"v": version})
    return redirect(page.get_absolute_url())


@login_required
@require_POST
def page_delete(request, key, pk):
    project, space = _space(request, key, "edit_wiki")
    page = get_object_or_404(Page, pk=pk, space=space)
    if page.created_by_id != request.user.pk and not can(request.user, project, "manage_project"):
        raise PermissionDenied
    # Children move up one level instead of being deleted with the page.
    page.children.update(parent=page.parent)
    page.delete()
    messages.success(request, _("Page deleted."))
    return redirect("wiki:home", key=project.key)
