"""
The single source of truth for "who may do what inside a project".

Every view, API endpoint and template check goes through `can()` / `role_for()`
instead of inspecting roles ad hoc. Workspace Admins are implicitly allowed
everything in every project; everyone else needs a ProjectMembership.
Non-members get a 404 (never a 403) so a project's existence isn't revealed;
members lacking a capability get a 403.
"""

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404

from .models import Project, ProjectRole

ADMIN = "admin"
PM = ProjectRole.PROJECT_MANAGER
DEV = ProjectRole.DEVELOPER
TESTER = ProjectRole.TESTER
VIEWER = ProjectRole.VIEWER

CONTRIBUTORS = {ADMIN, PM, DEV, TESTER}

CAPABILITIES = {
    "view": {ADMIN, PM, DEV, TESTER, VIEWER},
    "edit_issues": CONTRIBUTORS,
    "comment": CONTRIBUTORS,
    "delete_issues": {ADMIN, PM},
    "manage_sprints": {ADMIN, PM},
    "manage_project": {ADMIN, PM},
    "edit_wiki": CONTRIBUTORS,
    "manage_tests": {ADMIN, PM, TESTER},
    "execute_tests": {ADMIN, PM, TESTER, DEV},
}


def role_for(user, project):
    if not user.is_authenticated or not user.is_active:
        return None
    if user.is_workspace_admin:
        return ADMIN
    cache = getattr(user, "_project_role_cache", None)
    if cache is None:
        cache = user._project_role_cache = {}
    if project.pk not in cache:
        membership = project.memberships.filter(user=user).only("role").first()
        cache[project.pk] = membership.role if membership else None
    return cache[project.pk]


def can(user, project, capability):
    role = role_for(user, project)
    return role is not None and role in CAPABILITIES[capability]


def visible_projects(user):
    qs = Project.objects.filter(is_archived=False)
    if user.is_workspace_admin:
        return qs
    return qs.filter(memberships__user=user).distinct()


def get_project_or_404(user, key, capability="view"):
    project = get_object_or_404(Project, key=key.upper())
    if not can(user, project, "view"):
        raise Http404
    if capability != "view" and not can(user, project, capability):
        # A member already knows the project exists, so a 403 is honest here.
        raise PermissionDenied
    return project


def capabilities_for(user, project):
    role = role_for(user, project)
    return {cap: role in roles for cap, roles in CAPABILITIES.items()} if role else {}
